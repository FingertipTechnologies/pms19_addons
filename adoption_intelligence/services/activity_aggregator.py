# -*- coding: utf-8 -*-
"""Daily roll-up of detail rows into ``adoption.daily.summary``.

One implementation (``compute_day``) feeds both the nightly job and the
"today, live" path of the dashboards, so the two can never drift apart.

Row grain (same as the original ``Adoption_Daily_Summary__c``):
    one row per user x day x model, plus one day-level row per user x day with
    ``model_name == '__ALL__'`` holding the cross-model engagement metrics.

Idempotency / safety
--------------------
* ``persist_day`` upserts on (user, day, model) and is covered by a UNIQUE
  constraint; re-running a day can never create a duplicate.
* A transaction-level advisory lock stops the cron and a manual recalculation
  from racing each other.
* A day whose detail has already expired is never recomputed (that would
  overwrite a good summary with zeros).
* Stale rows (no longer backed by detail) are deleted only when the full day
  of detail is known to still exist.
"""
import logging
from collections import defaultdict
from datetime import timedelta

from .env_utils import in_test_mode

_logger = logging.getLogger(__name__)

ALL = '__ALL__'
LOCK_ID = 7406132001
MAX_LIVE_DAYS = 62
# Users live in many time zones: when the nightly job rolls up "yesterday" (server
# date), people in the Americas are still working that day.  So (a) every night
# the last LOOKBACK_DAYS days are re-rolled (idempotent), and (b) readers treat
# the most recent SAFE_LAG_DAYS rolled-up days as not-yet-final and compute them
# live instead of trusting the stored (possibly partial) rows.
SAFE_LAG_DAYS = 1
LOOKBACK_DAYS = 2
CHUNK = 1000
MAX_ACTIVE_MINUTES_PER_DAY = 1440

MEASURES = [
    'records_created', 'records_updated', 'records_deleted', 'records_viewed',
    'field_edits', 'meaningful_field_edits', 'distinct_fields_used',
    'automated_changes', 'adoption_points', 'pages_viewed', 'reports_viewed',
    'dashboards_viewed', 'searches', 'active_minutes', 'login_count',
    'session_count',
]
PAGE_EVENTS = ('page_view', 'list_view', 'record_view')


def _gid(value):
    return value.id if hasattr(value, 'id') else value


def _blank():
    return {m: 0.0 for m in MEASURES}


def compute_day(env, day, user_ids=None):
    """Return ``{(user_id, model_name): {measure: value}}`` for one day.
    Reads detail with sudo (aggregation only) and writes nothing."""
    Log = env['adoption.activity.log'].sudo()
    Change = env['adoption.field.change'].sudo()
    Nav = env['adoption.navigation.log'].sudo()
    Session = env['adoption.active.session'].sudo()
    Login = env['adoption.login.summary'].sudo()
    uf = [('user_id', 'in', list(user_ids))] if user_ids else [('user_id', '!=', False)]
    rows = defaultdict(_blank)

    # 1. Human CRUD, per model -------------------------------------------------
    op_col = {'create': 'records_created', 'update': 'records_updated', 'delete': 'records_deleted'}
    for user, model, op, _n, edits, meaningful, points in Log._read_group(
            [('activity_date', '=', day), ('is_automated', '=', False)] + uf,
            ['user_id', 'model_name', 'operation'],
            ['__count', 'field_change_count:sum', 'meaningful_change_count:sum', 'adoption_points:sum']):
        uid = _gid(user)
        if not uid:
            continue
        r = rows[(uid, model)]
        r[op_col[op]] += _n
        r['field_edits'] += edits or 0
        r['meaningful_field_edits'] += meaningful or 0
        r['adoption_points'] += points or 0.0

    # 2. Automated operations (counted, never credited) --------------------------
    for user, model, n in Log._read_group(
            [('activity_date', '=', day), ('is_automated', '=', True)] + uf,
            ['user_id', 'model_name'], ['__count']):
        if _gid(user):
            rows[(_gid(user), model)]['automated_changes'] += n

    # 3. Distinct fields maintained (value at deletion never counts) -----------------
    for user, model, n in Change._read_group(
            [('activity_date', '=', day), ('is_automated', '=', False),
             ('change_kind', '!=', 'final')] + uf,
            ['user_id', 'model_name'], ['field_name:count_distinct']):
        if _gid(user):
            rows[(_gid(user), model)]['distinct_fields_used'] += n

    # 4. Navigation: record views per model; page/report/dashboard counts day-level --
    for user, event, model, n in Nav._read_group(
            [('activity_date', '=', day)] + uf, ['user_id', 'event_type', 'model_name'], ['__count']):
        uid = _gid(user)
        if not uid:
            continue
        day_row = rows[(uid, ALL)]
        if event in PAGE_EVENTS:
            day_row['pages_viewed'] += n
        if event == 'record_view':
            day_row['records_viewed'] += n
            if model:
                rows[(uid, model)]['records_viewed'] += n
        elif event == 'report_view':
            day_row['reports_viewed'] += n
        elif event == 'dashboard_view':
            day_row['dashboards_viewed'] += n
        elif event == 'search':
            day_row['searches'] += n

    # 5. Estimated active minutes -------------------------------------------------------
    for user, seconds in Session._read_group(
            [('activity_date', '=', day)] + uf, ['user_id'], ['active_seconds:sum']):
        if _gid(user) and seconds:
            rows[(_gid(user), ALL)]['active_minutes'] += min(
                round(seconds / 60.0, 2), MAX_ACTIVE_MINUTES_PER_DAY)

    # 6. Logins ------------------------------------------------------------------------------
    for user, logins, sessions in Login._read_group(
            [('login_date', '=', day)] + uf, ['user_id'], ['login_count:sum', 'session_count:sum']):
        if _gid(user):
            r = rows[(_gid(user), ALL)]
            r['login_count'] += logins or 0
            r['session_count'] += sessions or 0
    return dict(rows)


def _protected_models(env, day):
    """Models whose *shorter* retention override already purged this day."""
    from odoo import fields
    today = fields.Date.context_today(env['adoption.settings'])
    return {name for name, cfg in env['adoption.tracking.config']._tracking_map().items()
            if cfg['retention_days'] and day < today - timedelta(days=cfg['retention_days'])}


def persist_day(env, day, rows, delete_stale=True):
    Summary = env['adoption.daily.summary'].sudo().with_context(adoption_internal=True)
    protected = _protected_models(env, day)
    existing = Summary.search([('summary_date', '=', day)])
    by_key = {(r.user_id.id, r.model_name): r for r in existing}
    to_create = []
    changed = 0
    for (uid, model), values in rows.items():
        if model in protected:
            by_key.pop((uid, model), None)
            continue
        values = {k: round(v, 2) for k, v in values.items()}
        rec = by_key.pop((uid, model), None)
        if rec:
            diff = {k: v for k, v in values.items() if abs((rec[k] or 0) - v) > 0.004}
            if diff:
                rec.write(diff)
                changed += 1
        else:
            to_create.append(dict(values, user_id=uid, summary_date=day, model_name=model))
    for i in range(0, len(to_create), CHUNK):
        Summary.create(to_create[i:i + CHUNK])
    stale = Summary.browse([r.id for k, r in by_key.items() if k[1] not in protected])
    if delete_stale and stale:
        stale.with_context(adoption_retention=True).unlink()
    return len(to_create), changed, len(stale) if delete_stale else 0


def acquire_lock(env):
    env.cr.execute('SELECT pg_try_advisory_xact_lock(%s)', [LOCK_ID])
    return bool(env.cr.fetchone()[0])


def rollup_day(env, day, force=False):
    """Roll up one day.  ``force`` (manual recalculation) refuses days whose
    detail may have expired."""
    from odoo import fields
    settings = env['adoption.settings']._runtime()
    today = fields.Date.context_today(env['adoption.settings'])
    if force and day < today - timedelta(days=settings['retention_days']):
        _logger.warning('Adoption rollup %s skipped: detail older than retention.', day)
        return None
    rows = compute_day(env, day)
    return persist_day(env, day, rows, delete_stale=True)


def rollup_pending(env, max_days=45):
    """Job 2: roll up every day after ``last_rollup_date`` up to yesterday.
    Safe to retry: it resumes from the last fully completed day."""
    from odoo import fields
    if not acquire_lock(env):
        _logger.info('Adoption rollup already running elsewhere; skipping.')
        return 0
    cfg = env['adoption.settings']._get()
    today = fields.Date.context_today(env['adoption.settings'])
    yesterday = today - timedelta(days=1)
    last = cfg.last_rollup_date or yesterday - timedelta(days=1)
    day = last - timedelta(days=LOOKBACK_DAYS - 1)       # re-roll the not-yet-final tail
    done = 0
    try:
        while day <= yesterday and done < max_days:
            rollup_day(env, day)
            cfg.sudo().with_context(adoption_internal=True).write({
                'last_rollup_date': max(day, cfg.last_rollup_date or day),
                'last_rollup_at': fields.Datetime.now(), 'last_rollup_status': 'ok: %s' % day})
            done += 1
            day += timedelta(days=1)
            if not in_test_mode(env):
                env.cr.commit()           # short transactions; resume point is persisted
    except Exception as exc:  # noqa: BLE001
        env.cr.rollback()
        cfg.sudo().with_context(adoption_internal=True).write({
            'last_rollup_status': 'FAILED at %s: %s' % (day, str(exc)[:200])})
        env['adoption.error.log']._log('rollup', exc, model_name='adoption.daily.summary')
        _logger.exception('Adoption rollup failed at %s', day)
        raise
    return done


def aggregate(env, date_from, date_to, groupby, user_ids=None, model_name=None, level='model'):
    """Totals from stored summaries (days <= last_rollup_date) plus a live
    computation for later days (today and any gap a failed job left).

    ``groupby`` is a tuple drawn from ('user_id', 'summary_date', 'model_name').
    ``level``: 'model' (per-model rows), 'day' (cross-model ``__ALL__`` rows)
    or 'both'.  Returns ``{key_tuple: {measure: value}}``.
    """
    from odoo import fields
    settings = env['adoption.settings'].sudo()._get()
    today = fields.Date.context_today(env['adoption.settings'])
    final_to = (settings.last_rollup_date - timedelta(days=SAFE_LAG_DAYS)) if settings.last_rollup_date else None
    stored_to = min(date_to, final_to) if final_to else date_from - timedelta(days=1)
    out = defaultdict(_blank)

    def keyfor(uid, day, model):
        parts = {'user_id': uid, 'summary_date': day, 'model_name': model}
        return tuple(parts[g] for g in groupby)

    def level_ok(model):
        return level == 'both' or (level == 'day') == (model == ALL)

    if stored_to >= date_from:
        domain = [('summary_date', '>=', date_from), ('summary_date', '<=', stored_to)]
        if user_ids:
            domain.append(('user_id', 'in', list(user_ids)))
        if level == 'model':
            domain.append(('model_name', '!=', ALL))
        elif level == 'day':
            domain.append(('model_name', '=', ALL))
        if model_name:
            domain.append(('model_name', '=', model_name))
        spec = [{'user_id': 'user_id', 'summary_date': 'summary_date:day',
                 'model_name': 'model_name'}[g] for g in groupby]
        Summary = env['adoption.daily.summary'].sudo()
        for row in Summary._read_group(domain, spec, ['%s:sum' % m for m in MEASURES]):
            keys, values = row[:len(groupby)], row[len(groupby):]
            key = tuple(_gid(k) for k in keys)
            target = out[key]
            for m, v in zip(MEASURES, values):
                target[m] += v or 0.0

    live_from = max(date_from, (final_to or date_from - timedelta(days=1)) + timedelta(days=1))
    live_to = min(date_to, today)
    if live_to >= live_from:
        live_from = max(live_from, live_to - timedelta(days=MAX_LIVE_DAYS))
        day = live_from
        while day <= live_to:
            for (uid, model), values in compute_day(env, day, user_ids).items():
                if not level_ok(model) or (model_name and model != model_name):
                    continue
                target = out[keyfor(uid, day, model)]
                for m in MEASURES:
                    target[m] += values.get(m, 0.0)
            day += timedelta(days=1)
    return dict(out)
