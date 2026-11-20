# -*- coding: utf-8 -*-
"""Centralised, configuration-driven CRUD tracking.

Entry points are called from ``models/base_tracking.py``, which overrides
create / write / unlink once on the ``base`` model (so no per-model code).

Transaction model (read this first)
-----------------------------------
Audit rows are written with the ORM *inside the business transaction*:

* the business operation succeeds  -> rows commit together with it;
* the business transaction rolls back -> the rows roll back too, so a rolled
  back save can never be reported as having happened;
* the logging code itself fails    -> it runs in a SAVEPOINT, is rolled back
  alone, the business operation proceeds, and the failure is recorded in
  ``adoption.error.log`` through an independent cursor ("fail-open").

An alternative (write after commit in a new transaction) was rejected: it can
lose events on a crash between commit and write, and cannot be made atomic
with the business operation.  The trade-off is accepted and documented.

Recursion
---------
``adoption.*`` models are never tracked and every write performed here carries
``adoption_skip_tracking``; either alone prevents audit-of-audit loops.

Attribution (PRIMARY / SECONDARY)
---------------------------------
Per transaction we remember which (model, id) were already logged.  The first
operation on a record is the person's (primary).  Any later operation on the
same record in the same transaction, or a record created/written through
``_inherits`` delegation by a tracked parent call, is secondary: counted as
automation, earning no points.  This is *structural* (same transaction), never
inferred from timing.
"""
import hashlib
import logging
import uuid

from . import value_utils

_logger = logging.getLogger(__name__)

SKIP_CTX = 'adoption_skip_tracking'
INTERNAL_CTX = 'adoption_internal'
MAX_DIFF_RECORDS = 2000      # larger batches are logged record-level only
MAX_NAMES = 500              # display names are not resolved for huge batches
SOURCES = ('web', 'api', 'import', 'automation', 'other')
_TABLES = ('adoption_settings', 'adoption_tracking_config', 'adoption_activity_log',
           'adoption_field_change')
_READY = set()


# --------------------------------------------------------------------------- state
def txn_state(env):
    """Dict that lives exactly as long as the current database transaction.
    ``cr.precommit.data`` is cleared on commit *and* rollback."""
    cr = env.cr
    data = getattr(getattr(cr, 'precommit', None), 'data', None)
    if data is not None:
        return data.setdefault('adoption_state', {})
    return cr.__dict__.setdefault('_adoption_state', {})


def _txn_id(env):
    state = txn_state(env)
    if 'txn' not in state:
        state['txn'] = uuid.uuid4().hex[:16]
    return state['txn']


def enter(env, model_name, op):
    stack = txn_state(env).setdefault('stack', [])
    stack.append((model_name, op))
    return len(stack)


def leave(env, token):
    stack = txn_state(env).setdefault('stack', [])
    del stack[token - 1:]


# --------------------------------------------------------------------------- gate
def _tables_ready(env):
    key = env.cr.dbname
    if key in _READY:
        return True
    env.cr.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = current_schema() AND table_name IN %s", [_TABLES])
    if env.cr.fetchone()[0] == len(_TABLES):
        _READY.add(key)
        return True
    return False


def get_config(env, model_name, op):
    """Return the cached config dict when ``op`` on ``model_name`` must be
    tracked, else None.  This runs on *every* create/write/unlink in the system,
    so the untracked path is a few attribute reads and a dict lookup."""
    if model_name.startswith('adoption.') or env.context.get(SKIP_CTX):
        return None
    registry = env.registry
    if getattr(registry, '_init', False) or 'adoption.tracking.config' not in registry:
        return None                               # module loading / upgrade
    if not _tables_ready(env):
        return None
    cfg = env['adoption.tracking.config']._tracking_map().get(model_name)
    if not cfg or not cfg.get(op):
        return None
    if not env['adoption.settings']._runtime()['tracking_enabled']:
        return None
    return cfg


def _user_allowed(env, rt):
    state = txn_state(env)
    key = ('user', env.uid)
    if key not in state:
        ok = env.uid not in rt['excluded_user_ids']
        if ok and rt['internal_only']:
            ok = not env['res.users'].sudo().browse(env.uid).share
        state[key] = ok
    return state[key]


def _safe(env, context, model_name, func):
    """Run logging code so that it can never harm the business operation."""
    try:
        with env.cr.savepoint(flush=False):
            return func()
    except Exception as exc:  # noqa: BLE001 - deliberate fail-open
        _logger.exception('Adoption Intelligence: tracking failed (%s on %s)', context, model_name)
        env['adoption.error.log']._log(context, exc, model_name=model_name,
                                       transaction_id=_txn_id(env))
        return None


# --------------------------------------------------------------------------- context
def _current_request():
    try:
        from odoo.http import request
        if request and getattr(request, 'httprequest', None) is not None:
            return request
    except Exception:  # noqa: BLE001
        pass
    return None


def detect_source(env):
    forced = env.context.get('adoption_source')
    if forced in SOURCES:
        return forced
    if env.context.get('import_file'):
        return 'import'
    request = _current_request()
    if request is None:
        # No HTTP request: cron, queue job, server-side script, test.
        return 'automation' if env.context.get('active_model') == 'ir.cron' else 'other'
    path = request.httprequest.path or ''
    if path.startswith(('/xmlrpc', '/jsonrpc', '/json/', '/api/')):
        return 'api'
    return 'web'


def _session_identifier(env):
    request = _current_request()
    try:
        sid = request.session.sid if request else None
    except Exception:  # noqa: BLE001
        sid = None
    return hashlib.sha256(sid.encode()).hexdigest()[:16] if sid else False


def _event_context(env, rt):
    from odoo import fields
    now = fields.Datetime.now()
    user = env['res.users'].sudo().browse(env.uid)
    local = fields.Datetime.context_timestamp(user, now)
    return {
        'now': now, 'date': local.date(), 'uid': env.uid, 'user_name': user.name,
        'company_id': env.company.id, 'source': detect_source(env),
        'txn': _txn_id(env), 'session': _session_identifier(env),
    }


def _classify(env, rt, model_name, record_id, source):
    """-> (activity_type, is_automated)."""
    state = txn_state(env)
    seen = state.setdefault('seen', set())
    key = (model_name, record_id)
    secondary = key in seen
    if not secondary:
        for outer_model, _op in state.get('stack', ()):
            outer = env.registry.get(outer_model)
            if outer is not None and model_name in (getattr(outer, '_inherits', None) or {}):
                secondary = True            # _inherits delegation, not a user action
                break
    seen.add(key)
    automated = (secondary or source in ('automation', 'other')
                 or (source == 'import' and rt['import_automated']))
    return ('secondary' if secondary else 'primary'), automated


# --------------------------------------------------------------------------- fields
def _eligible(field, name, cfg, rt):
    if name in rt['excluded_field_names']:
        return False
    if value_utils.is_system_field(name) or value_utils.is_sensitive_name(name):
        return False
    if field.type in value_utils.SKIPPED_TYPES:
        return False
    if not (field.store or getattr(field, 'inherited', False)):
        return False                                  # computed/related: not an independent change
    if field.type in value_utils.X2MANY_TYPES and not cfg['x2many']:
        return False
    fc = cfg['fields'].get(name)
    if fc is not None:
        return bool(fc['tracked'])
    return bool(cfg['all_fields'])


def _select_fields(records, names, cfg, rt):
    fields_map = records._fields
    return [n for n in names if n in fields_map and _eligible(fields_map[n], n, cfg, rt)]


def _display_map(env, field, ids):
    if field.type != 'many2one' or not ids:
        return {}
    try:
        recs = env[field.comodel_name].sudo().browse(list(ids)[:50]).exists()
        return {r.id: r.display_name for r in recs}
    except Exception:  # noqa: BLE001
        return {}


def _selection_map(env, field):
    if field.type != 'selection':
        return {}
    try:
        return dict(field._description_selection(env))
    except Exception:  # noqa: BLE001
        return {}


def _make_change(env, records, name, kind, old_raw, new_raw, cfg, rt, maps):
    field = records._fields[name]
    fc = cfg['fields'].get(name, {})
    masked = bool(fc.get('mask'))
    old_c = value_utils.comparable(field.type, old_raw)
    new_c = value_utils.comparable(field.type, new_raw)
    delta = None
    if field.type in value_utils.X2MANY_TYPES:
        delta = value_utils.x2many_delta(old_c, new_c)
    if name not in maps:
        maps[name] = ({}, _selection_map(env, field))
    display, selection = maps[name]
    missing = {v for v in (old_c, new_c) if isinstance(v, int) and v not in display}
    if missing:                      # extend per record: a batch has many different ids
        display.update(_display_map(env, field, missing))
    limit = rt['max_value_length']
    return {
        'name': name, 'label': field.string or name, 'ftype': field.type, 'kind': kind,
        'old': value_utils.format_value(field.type, old_c, display=display, selection=selection,
                                        masked=masked, max_len=limit, delta=None if kind != 'update' else delta),
        'new': value_utils.format_value(field.type, new_c, display=display, selection=selection,
                                        masked=masked, max_len=limit, delta=None if kind != 'update' else delta),
        'masked': masked, 'meaningful': bool(fc.get('meaningful')),
        'weight': fc.get('weight', 1.0), 'category': fc.get('category', ''),
    }


def _names(records):
    if len(records) > MAX_NAMES:
        return {}
    try:
        return {r.id: r.display_name for r in records.sudo()}
    except Exception:  # noqa: BLE001
        return {}


def _points(rt, cfg, op, changes):
    weight = cfg['weight']
    if op == 'create':
        return rt['points_create'] * weight
    if op == 'update':
        points = rt['points_update']
        for c in changes:
            if c['kind'] == 'update' and c['meaningful']:
                points += rt['points_meaningful'] * c['weight']
        return points * weight
    return 0.0


# --------------------------------------------------------------------------- persist
def _persist(env, rt, cfg, model_name, ctx, events):
    """events: [{'id', 'name', 'op', 'type', 'automated', 'changes': [...]}]"""
    if not events:
        return
    Log = env['adoption.activity.log'].sudo().with_context(**{INTERNAL_CTX: True, SKIP_CTX: True})
    Change = env['adoption.field.change'].sudo().with_context(**{INTERNAL_CTX: True, SKIP_CTX: True})
    log_vals = []
    for ev in events:
        counted = [c for c in ev['changes'] if c['kind'] != 'final']
        log_vals.append({
            'user_id': ctx['uid'], 'user_name': ctx['user_name'], 'company_id': ctx['company_id'],
            'model_name': model_name, 'model_label': cfg['label'], 'record_id': ev['id'],
            'record_name': ev['name'], 'operation': ev['op'],
            'activity_datetime': ctx['now'], 'activity_date': ctx['date'], 'source': ctx['source'],
            'activity_type': ev['type'], 'is_automated': ev['automated'],
            'session_identifier': ctx['session'], 'transaction_id': ctx['txn'],
            'field_change_count': len(counted),
            'meaningful_change_count': sum(1 for c in counted if c['meaningful']),
            'adoption_points': 0.0 if ev['automated'] else _points(rt, cfg, ev['op'], ev['changes']),
        })
    logs = Log.create(log_vals)
    change_vals = []
    for log, ev in zip(logs, events):
        for c in ev['changes']:
            change_vals.append({
                'activity_log_id': log.id, 'user_id': ctx['uid'], 'company_id': ctx['company_id'],
                'model_name': model_name, 'record_id': ev['id'], 'record_name': ev['name'],
                'field_name': c['name'], 'field_label': c['label'], 'field_type': c['ftype'],
                'change_kind': c['kind'], 'old_value': c['old'], 'new_value': c['new'],
                'is_masked': c['masked'], 'is_meaningful': c['meaningful'],
                'weight': c['weight'], 'category': c['category'],
                'change_datetime': ctx['now'], 'activity_date': ctx['date'],
                'is_automated': ev['automated'],
            })
    if change_vals:
        Change.create(change_vals)


def _meaningful_names(records, cfg, rt):
    wanted = [n for n, fc in cfg['fields'].items() if fc['meaningful'] and fc['tracked']]
    return _select_fields(records, wanted, cfg, rt)


# --------------------------------------------------------------------------- CREATE
def after_create(records, vals_list, cfg):
    env = records.env

    def work():
        rt = env['adoption.settings']._runtime()
        if not records or not _user_allowed(env, rt):
            return
        ctx = _event_context(env, rt)
        names = _meaningful_names(records, cfg, rt) if cfg['field_changes'] else []
        explicit = {n for vals in vals_list for n in vals}
        names = [n for n in names if n in explicit]
        rows = {}
        if names:
            rows = {row['id']: row for row in records.sudo().read(names, load=None)}
        titles = _names(records)
        maps, events = {}, []
        for record, vals in zip(records, vals_list):
            atype, automated = _classify(env, rt, records._name, record.id, ctx['source'])
            changes = []
            row = rows.get(record.id, {})
            for name in names:
                if name not in vals:
                    continue
                comp = value_utils.comparable(records._fields[name].type, row.get(name))
                if comp in (None, (), False):
                    continue                          # nothing was actually entered
                changes.append(_make_change(env, records, name, 'initial', None, row.get(name), cfg, rt, maps))
            events.append({'id': record.id, 'name': titles.get(record.id), 'op': 'create',
                           'type': atype, 'automated': automated, 'changes': changes})
        _persist(env, rt, cfg, records._name, ctx, events)

    _safe(env, 'create', records._name, work)


# --------------------------------------------------------------------------- UPDATE
def before_write(records, vals, cfg):
    """Capture old values *before* the write (the cache is overwritten by it)."""
    env = records.env

    def work():
        rt = env['adoption.settings']._runtime()
        if not _user_allowed(env, rt):
            return None
        pre = {'names': [], 'old': {}, 'oversize': False, 'skip': False}
        if not cfg['field_changes']:
            return pre                                 # record-level event only
        names = _select_fields(records, list(vals), cfg, rt)
        if not names:
            pre['skip'] = True                         # only excluded/system fields written
            return pre
        if len(records) > MAX_DIFF_RECORDS:
            pre['oversize'] = True
            return pre
        pre['names'] = names
        pre['old'] = {row['id']: row for row in records.sudo().read(names, load=None)}
        return pre

    return _safe(env, 'write', records._name, work)


def after_write(records, vals, cfg, pre):
    env = records.env
    if pre is None or pre['skip']:
        return

    def work():
        rt = env['adoption.settings']._runtime()
        ctx = _event_context(env, rt)
        existing = records.exists()
        names = pre['names']
        new_rows = {}
        if names and existing:
            new_rows = {row['id']: row for row in existing.sudo().read(names, load=None)}
        titles = _names(existing)
        maps, events = {}, []
        for record in existing:
            changes = []
            if names:
                old, new = pre['old'].get(record.id, {}), new_rows.get(record.id, {})
                for name in names:
                    if value_utils.changed(records._fields[name].type, old.get(name), new.get(name)):
                        changes.append(_make_change(env, records, name, 'update',
                                                    old.get(name), new.get(name), cfg, rt, maps))
                if not changes:
                    continue                           # nothing really changed -> no event
            atype, automated = _classify(env, rt, records._name, record.id, ctx['source'])
            events.append({'id': record.id, 'name': titles.get(record.id), 'op': 'update',
                           'type': atype, 'automated': automated, 'changes': changes})
        if pre['oversize']:
            env['adoption.error.log']._log(
                'write', 'Batch of %d records exceeds %d: logged without field detail.' % (
                    len(records), MAX_DIFF_RECORDS), model_name=records._name, severity='warning')
        _persist(env, rt, cfg, records._name, ctx, events)

    _safe(env, 'write', records._name, work)


# --------------------------------------------------------------------------- DELETE
def before_unlink(records, cfg):
    env = records.env

    def work():
        rt = env['adoption.settings']._runtime()
        if not _user_allowed(env, rt):
            return None
        names = _meaningful_names(records, cfg, rt) if cfg['field_changes'] else []
        rows = {}
        if names and len(records) <= MAX_DIFF_RECORDS:
            rows = {row['id']: row for row in records.sudo().read(names, load=None)}
        titles = _names(records)
        return {'ids': records.ids, 'titles': titles, 'rows': rows, 'names': names}

    return _safe(env, 'unlink', records._name, work)


def after_unlink(records, cfg, snap):
    env = records.env
    if not snap:
        return

    def work():
        rt = env['adoption.settings']._runtime()
        ctx = _event_context(env, rt)
        maps, events = {}, []
        for rid in snap['ids']:
            atype, automated = _classify(env, rt, records._name, rid, ctx['source'])
            changes = []
            row = snap['rows'].get(rid, {})
            for name in snap['names']:
                comp = value_utils.comparable(records._fields[name].type, row.get(name))
                if comp in (None, (), False):
                    continue
                changes.append(_make_change(env, records, name, 'final', row.get(name), None, cfg, rt, maps))
            events.append({'id': rid, 'name': snap['titles'].get(rid), 'op': 'delete',
                           'type': atype, 'automated': automated, 'changes': changes})
        _persist(env, rt, cfg, records._name, ctx, events)

    _safe(env, 'unlink', records._name, work)
