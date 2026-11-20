# -*- coding: utf-8 -*-
"""Ingestion API for the web-client tracker.

Exposed as ordinary model methods, called through Odoo's authenticated
``/web/dataset/call_kw`` route: the session cookie authenticates the caller and
``self.env.uid`` is the *only* source of the user id.  Nothing the browser sends
can name or impersonate another user.

``sudo()`` is used for exactly one thing here: writing the telemetry rows the
caller's own groups could not create.  Reads of business records (existence /
access check for record views) run as the caller.
"""
import logging
import time
from datetime import datetime, timezone

from odoo import api, fields, models

from ..services import payload_validation as pv
from ..services import session_math

_logger = logging.getLogger(__name__)
_LIMITER = pv.SlidingWindowLimiter(max_events=600, window_seconds=60.0)
UNATTRIBUTED_PREFIXES = ('ir.', 'res.config', 'base.', 'adoption.')


def _check_read(record):
    """Version tolerant 'may the caller read this record'."""
    if hasattr(record, 'check_access'):
        record.check_access('read')
    else:                                    # pragma: no cover - Odoo <= 17
        record.check_access_rights('read')
        record.check_access_rule('read')


class AdoptionTracker(models.AbstractModel):
    _name = 'adoption.tracker'
    _description = 'Adoption Browser Tracker API'

    # ------------------------------------------------------------------ config
    @api.model
    def _client_allowed(self, rt):
        if not rt['tracking_enabled'] or self.env.uid in rt['excluded_user_ids']:
            return False
        return not (rt['internal_only'] and self.env.user.share)

    @api.model
    def get_client_config(self):
        rt = self.env['adoption.settings']._runtime()
        if not self._client_allowed(rt):
            return {'enabled': False}
        record_models = {
            name: {'read': cfg['read'], 'time': cfg['view_time']}
            for name, cfg in self.env['adoption.tracking.config']._tracking_map().items()
            if cfg['read'] or cfg['view_time']}
        return {
            'enabled': True,
            'uid': self.env.uid,          # only used to label this browser's local storage; never trusted for identity
            'idle_seconds': rt['idle_seconds'],
            'heartbeat_seconds': rt['heartbeat_seconds'],
            'navigation': rt['client_navigation'],
            'record_views': rt['client_record_view'],
            'search': rt['client_search'],
            'actions': rt['client_actions'],
            'record_models': record_models,
            'max_batch': pv.MAX_EVENTS_PER_REQUEST,
        }

    # ------------------------------------------------------------------ ingestion
    @api.model
    def track(self, payload):
        rt = self.env['adoption.settings']._runtime()
        if not self._client_allowed(rt):
            return {'accepted': 0, 'rejected': 0, 'disabled': True}
        now_ms = int(time.time() * 1000)
        events, rejected, error = pv.validate_payload(payload, now_ms)
        if error:
            return {'accepted': 0, 'rejected': 0, 'error': error}
        if not _LIMITER.allow((self.env.cr.dbname, self.env.uid), max(len(events), 1)):
            return {'accepted': 0, 'rejected': len(events), 'throttled': True}
        accepted = self._ingest(events, rt)
        return {'accepted': accepted, 'rejected': rejected + (len(events) - accepted)}

    # ------------------------------------------------------------------ internals
    @api.model
    def _ingest(self, events, rt):
        user = self.env.user
        now = fields.Datetime.now()
        Nav = self.env['adoption.navigation.log'].sudo().with_context(adoption_internal=True)
        Session = self.env['adoption.active.session'].sudo().with_context(adoption_internal=True)
        record_models = self.env['adoption.tracking.config']._tracking_map()
        uid = self.env.uid

        keys = {e['key'] for e in events}
        known_nav = set(Nav.search([('user_id', '=', uid), ('event_key', 'in', list(keys))]).mapped('event_key'))
        sessions = {s.session_key: s for s in Session.search(
            [('user_id', '=', uid), ('session_key', 'in', list(keys))])}
        states = {}                              # session_key -> merged state (written once at the end)
        accepted = 0

        def local_date(dt):
            return fields.Datetime.context_timestamp(user, dt).date()

        for ev in events:
            kind = ev['t']
            if kind in ('visit', 'signal'):
                dt = datetime.fromtimestamp(ev['ts'] / 1000.0, tz=timezone.utc).replace(tzinfo=None)
                model = ev.get('model')
                if model and (model.startswith('adoption.') or model not in self.env.registry):
                    continue                                      # never track ourselves / unknown models
                if model and model.startswith(UNATTRIBUTED_PREFIXES):
                    model = None                                  # setup screens: page yes, object no
                etype = ev['event_type']

                if kind == 'signal':
                    if (etype == 'search' and not rt['client_search']) or \
                            (etype == 'action_click' and not rt['client_actions']):
                        continue
                    if ev['key'] in known_nav:
                        accepted += 1
                        continue
                    Nav.create({
                        'user_id': uid, 'company_id': self.env.company.id, 'event_key': ev['key'],
                        'event_type': etype, 'model_name': model,
                        'action_identifier': ev.get('action_identifier'),
                        'session_identifier': ev.get('browser_session'),
                        'navigation_datetime': dt, 'activity_date': local_date(dt)})
                    known_nav.add(ev['key'])
                    accepted += 1
                    continue

                # ----- visit -----------------------------------------------------
                cfg = record_models.get(model) if model else None
                record_id = ev.get('record_id')
                record_name = False
                if etype == 'record_view':
                    ok = bool(rt['client_record_view'] and cfg and cfg['read'] and model and record_id)
                    if ok:
                        try:
                            record = self.env[model].browse(record_id).exists()
                            if not record:
                                ok = False
                            else:
                                _check_read(record)               # caller must be able to read it
                                record_name = record.sudo().display_name
                        except Exception:  # noqa: BLE001 - not allowed / not found -> not a record view
                            ok = False
                    if not ok:
                        etype, record_id, record_name = 'page_view', None, False   # still a page view, no record detail
                if etype != 'record_view' and not rt['client_navigation'] and etype != 'session_start':
                    continue
                if etype == 'session_start' and not rt['client_navigation']:
                    continue

                if ev['key'] not in known_nav:
                    Nav.create({
                        'user_id': uid, 'company_id': self.env.company.id, 'event_key': ev['key'],
                        'event_type': etype, 'model_name': model,
                        'record_id': record_id or 0, 'record_name': record_name,
                        'action_type': ev.get('view_type'),
                        'action_identifier': ev.get('action_identifier'),
                        'page_name': ev.get('page_name'),
                        'session_identifier': ev.get('browser_session'),
                        'navigation_datetime': dt, 'activity_date': local_date(dt)})
                    known_nav.add(ev['key'])

                timed = etype != 'session_start' and (
                    (etype == 'record_view' and cfg and cfg['view_time'] and rt['client_record_view'])
                    or (etype != 'record_view' and rt['client_navigation']))
                if timed and ev['key'] not in sessions:
                    sessions[ev['key']] = Session.create({
                        'user_id': uid, 'company_id': self.env.company.id,
                        'session_key': ev['key'], 'browser_session': ev.get('browser_session'),
                        'kind': 'record' if etype == 'record_view' else ev.get('kind', 'other'),
                        'model_name': model, 'record_id': record_id or 0, 'record_name': record_name,
                        'view_type': ev.get('view_type'),
                        'action_identifier': ev.get('action_identifier'),
                        'page_name': ev.get('page_name'),
                        'started_at': dt, 'last_beat_at': now, 'activity_date': local_date(dt),
                        'state': 'open'})
                accepted += 1

            elif kind == 'beat':
                session = sessions.get(ev['key'])
                if not session:
                    continue
                state = states.get(ev['key']) or {
                    'started_at': session.started_at, 'elapsed_seconds': session.elapsed_seconds,
                    'active_seconds': session.active_seconds, 'heartbeat_count': session.heartbeat_count,
                    'last_seq': session.last_seq, 'state': session.state}
                if state['state'] == 'stale' and not ev['ended']:
                    state['state'] = 'open'              # the tab was only suspended, it is back
                states[ev['key']] = session_math.merge_beat(state, ev, now)
                accepted += 1

        for key, state in states.items():
            session = sessions[key]
            vals = {k: state[k] for k in ('elapsed_seconds', 'active_seconds', 'heartbeat_count',
                                           'last_seq', 'last_beat_at', 'state') if k in state}
            if state.get('ended_at'):
                vals['ended_at'] = state['ended_at']
            vals = {k: v for k, v in vals.items() if session[k] != v}
            if vals:
                session.write(vals)
        return accepted
