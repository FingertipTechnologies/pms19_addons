# -*- coding: utf-8 -*-
"""Data for the Navigation, Activity log, Model analytics and Reports screens.

Same rules as ``adoption.dashboard``: scope is resolved on the server
(``_scope`` / ``_range``), detail rows are read as the CALLER so ACLs and record
rules apply a second time, and every number is computed from the database.
Methods take keyword arguments so the JavaScript cannot mis-order them.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from ..services import activity_aggregator as agg
from ..services import report_utils

PAGE_EVENTS = ('page_view', 'list_view', 'report_view', 'dashboard_view')
MAX_ROWS = 200            # per page on screen
MAX_EXPORT_ROWS = 5000    # spreadsheet export


def _cap(limit, ceiling):
    try:
        return max(1, min(int(limit), ceiling))
    except (TypeError, ValueError):
        return 40


class AdoptionDashboardScreens(models.AbstractModel):
    _inherit = 'adoption.dashboard'

    # ------------------------------------------------------------------ navigation
    @api.model
    def get_navigation(self, date_from=None, date_to=None, user_id=None, model_name=None,
                       event_type=None, limit=40, offset=0):
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        labels = self._labels()
        Nav = self.env['adoption.navigation.log']
        domain = [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end)]
        if model_name:
            domain.append(('model_name', '=', model_name))

        by_type = dict(Nav._read_group(domain, ['event_type'], ['__count']))
        distinct = Nav._read_group(domain, [], ['session_identifier:count_distinct', 'user_id:count_distinct'])
        sessions, users = (distinct[0] if distinct else (0, 0))

        # daily trend per type
        per_day = {}
        for day, etype, n in Nav._read_group(domain, ['activity_date:day', 'event_type'], ['__count']):
            row = per_day.setdefault(day, {'events': 0, 'records': 0, 'pages': 0, 'reports': 0})
            if etype in ('session_start', 'search', 'action_click'):
                continue
            row['events'] += n
            if etype == 'record_view':
                row['records'] += n
            elif etype in ('page_view', 'list_view'):
                row['pages'] += n
            else:
                row['reports'] += n
        trend, day = [], start
        while day <= end:
            r = per_day.get(day, {})
            trend.append({'date': fields.Date.to_string(day), 'events': r.get('events', 0),
                          'records': r.get('records', 0), 'pages': r.get('pages', 0)})
            day += timedelta(days=1)

        top_pages = Nav._read_group(domain + [('event_type', 'in', PAGE_EVENTS)], ['page_name'],
                                    ['__count'], order='__count desc', limit=10)
        top_models = Nav._read_group(
            domain + [('model_name', '!=', False), ('event_type', 'in', ('record_view', 'list_view'))],
            ['model_name'], ['__count'], order='__count desc', limit=10)

        per_user = {}
        for user, etype, n in Nav._read_group(domain, ['user_id', 'event_type'], ['__count']):
            if not user:
                continue
            row = per_user.setdefault(user.id, {'name': user.name, 'events': 0, 'records': 0, 'pages': 0,
                                                'reports': 0, 'searches': 0})
            if etype == 'record_view':
                row['records'] += n
                row['events'] += n
            elif etype in ('page_view', 'list_view'):
                row['pages'] += n
                row['events'] += n
            elif etype in ('report_view', 'dashboard_view'):
                row['reports'] += n
                row['events'] += n
            elif etype == 'search':
                row['searches'] += n

        rows_domain = domain + ([('event_type', '=', event_type)] if event_type else [])
        limit = _cap(limit, MAX_ROWS)
        events = Nav.search(rows_domain, limit=limit, offset=int(offset or 0))
        return {
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'kpis': {
                'total': sum(n for t, n in by_type.items() if t not in ('session_start', 'search', 'action_click')),
                'pages': by_type.get('page_view', 0), 'lists': by_type.get('list_view', 0),
                'records': by_type.get('record_view', 0), 'reports': by_type.get('report_view', 0),
                'dashboards': by_type.get('dashboard_view', 0), 'searches': by_type.get('search', 0),
                'attempts': by_type.get('action_click', 0), 'sessions': sessions, 'users': users,
            },
            'trend': trend,
            'top_pages': [{'label': p or _('(untitled)'), 'value': n} for p, n in top_pages],
            'top_models': [{'label': labels.get(m, m), 'value': n} for m, n in top_models],
            'by_user': sorted(per_user.values(), key=lambda r: -r['events'])[:15],
            'events': [{
                'id': e.id, 'when': fields.Datetime.to_string(e.navigation_datetime), 'user': e.user_id.name or '',
                'type': e.event_type, 'model': labels.get(e.model_name, e.model_name) if e.model_name else '',
                'record': e.record_name or '', 'page': e.page_name or '', 'view': e.action_type or '',
                'action': e.action_identifier or '',
            } for e in events],
            'total_events': Nav.search_count(rows_domain),
            'offset': int(offset or 0), 'limit': limit,
        }

    # ------------------------------------------------------------------ activity log
    @api.model
    def _activity_domain(self, start, end, scope, model_name, operation, source, origin, search):
        domain = [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end)]
        if model_name:
            domain.append(('model_name', '=', model_name))
        if operation in ('create', 'update', 'delete'):
            domain.append(('operation', '=', operation))
        if source in ('web', 'api', 'import', 'automation', 'other'):
            domain.append(('source', '=', source))
        if origin == 'human':
            domain.append(('is_automated', '=', False))
        elif origin == 'automated':
            domain.append(('is_automated', '=', True))
        if search and search.strip():
            domain.append(('record_name', 'ilike', search.strip()))
        return domain

    @api.model
    def get_activity_log(self, date_from=None, date_to=None, user_id=None, model_name=None, operation=None,
                         source=None, origin=None, search=None, limit=50, offset=0, export=False):
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        Log = self.env['adoption.activity.log']
        domain = self._activity_domain(start, end, scope, model_name, operation, source, origin, search)
        limit = _cap(limit, MAX_EXPORT_ROWS if export else MAX_ROWS)
        rows = Log.search(domain, limit=limit, offset=int(offset or 0))
        counts = dict(Log._read_group(domain, ['operation'], ['__count']))
        origin_counts = {('automated' if k else 'human'): v
                         for k, v in Log._read_group(domain, ['is_automated'], ['__count'])}
        return {
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'total': Log.search_count(domain), 'offset': int(offset or 0), 'limit': limit,
            'counts': {'create': counts.get('create', 0), 'update': counts.get('update', 0),
                       'delete': counts.get('delete', 0)},
            'origin': {'human': origin_counts.get('human', 0), 'automated': origin_counts.get('automated', 0)},
            'rows': [{
                'id': a.id, 'when': fields.Datetime.to_string(a.activity_datetime), 'user': a.user_name or a.user_id.name or '',
                'model': a.model_label or a.model_name, 'model_name': a.model_name,
                'record': a.record_name or ('#%s' % a.record_id), 'record_id': a.record_id,
                'operation': a.operation, 'type': a.activity_type, 'source': a.source,
                'automated': a.is_automated, 'changes': a.field_change_count,
                'meaningful': a.meaningful_change_count, 'points': a.adoption_points,
                'transaction': a.transaction_id or '',
            } for a in rows],
        }

    @api.model
    def get_activity_changes(self, activity_id=None):
        """Old/new values of one event.  Read as the caller: another user's
        values come back empty unless the caller is a manager."""
        changes = self.env['adoption.field.change'].search([('activity_log_id', '=', int(activity_id or 0))])
        return [{
            'id': c.id, 'field': c.field_label or c.field_name, 'name': c.field_name, 'kind': c.change_kind,
            'old': c.old_value, 'new': c.new_value, 'meaningful': c.is_meaningful, 'masked': c.is_masked,
        } for c in changes]

    # ------------------------------------------------------------------ model analytics
    @api.model
    def get_model_analytics(self, date_from=None, date_to=None, user_id=None, model_name=None):
        self._require_manager()
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        labels = self._labels()
        statuses = {c.model_name: c.status for c in
                    self.env['adoption.tracking.config'].sudo().with_context(active_test=False).search([])}
        per_um = agg.aggregate(self.env, start, end, ('user_id', 'model_name'), scope, None, level='model')
        names = self._user_names(scope)

        models_map = {}
        for (uid, model), v in per_um.items():
            m = models_map.setdefault(model, {k: 0.0 for k in agg.MEASURES})
            m['_users'] = m.get('_users', set())
            for k in agg.MEASURES:
                m[k] += v[k]
            if v['records_created'] + v['records_updated'] + v['records_deleted'] + v['records_viewed'] > 0:
                m['_users'].add(uid)

        Session = self.env['adoption.active.session']
        time_rows = {m: (s or 0, c) for m, s, c in Session._read_group(
            [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end),
             ('kind', '=', 'record'), ('model_name', '!=', False)],
            ['model_name'], ['active_seconds:sum', '__count'])}

        rows = []
        for model in sorted(set(models_map) | set(statuses)):
            m = models_map.get(model, {})
            secs, visits = time_rows.get(model, (0, 0))
            rows.append({
                'model': model, 'label': labels.get(model, model), 'status': statuses.get(model, 'untracked'),
                'created': int(m.get('records_created', 0)), 'updated': int(m.get('records_updated', 0)),
                'deleted': int(m.get('records_deleted', 0)), 'viewed': int(m.get('records_viewed', 0)),
                'field_edits': int(m.get('field_edits', 0)), 'meaningful': int(m.get('meaningful_field_edits', 0)),
                'automated': int(m.get('automated_changes', 0)), 'users': len(m.get('_users', ())),
                'points': round(m.get('adoption_points', 0.0), 1),
                'minutes': round(secs / 60.0, 1), 'visits': visits,
            })
        rows.sort(key=lambda r: -(r['created'] + r['updated'] + r['deleted'] + r['viewed']))
        result = {'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
                  'rows': rows, 'detail': None}
        if not model_name:
            return result

        by_day = agg.aggregate(self.env, start, end, ('summary_date',), scope, model_name, level='model')
        trend, day = [], start
        while day <= end:
            v = by_day.get((day,), {})
            trend.append({'date': fields.Date.to_string(day),
                          'events': int(v.get('records_created', 0) + v.get('records_updated', 0) + v.get('records_deleted', 0)),
                          'field_edits': int(v.get('field_edits', 0))})
            day += timedelta(days=1)
        top_users = sorted(({
            'name': names.get(uid, ''), 'created': int(v['records_created']), 'updated': int(v['records_updated']),
            'deleted': int(v['records_deleted']), 'field_edits': int(v['field_edits']),
            'meaningful': int(v['meaningful_field_edits']), 'viewed': int(v['records_viewed']),
        } for (uid, model), v in per_um.items() if model == model_name),
            key=lambda r: -(r['created'] + r['updated'] + r['deleted'] + r['field_edits']))[:10]
        sessions = Session._read_group(
            [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end),
             ('kind', '=', 'record'), ('model_name', '=', model_name)],
            ['record_id', 'record_name'], ['active_seconds:sum', '__count'],
            order='active_seconds:sum desc', limit=10)
        sources = self.env['adoption.activity.log']._read_group(
            [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end),
             ('model_name', '=', model_name)], ['source'], ['__count'])
        fields_data = self.get_field_adoption(model_name, date_from, date_to, user_id)
        cfg = self.env['adoption.tracking.config'].sudo().with_context(active_test=False).search(
            [('model_name', '=', model_name)], limit=1)
        result['detail'] = {
            'model': model_name, 'label': labels.get(model_name, model_name), 'trend': trend,
            'top_users': top_users,
            'time_on_records': [{'record': n or ('#%s' % rid), 'record_id': rid, 'minutes': round((s or 0) / 60.0, 1), 'visits': c}
                                for rid, n, s, c in sessions],
            'sources': [{'label': s, 'value': n} for s, n in sources],
            'fields': {'most': fields_data['most_maintained'], 'least': fields_data['least_maintained'],
                       'unused': len(fields_data['unused']), 'unknown': len(fields_data['unknown']),
                       'underused': len(fields_data['underused']), 'warnings': fields_data['warnings'],
                       'tracking_enabled': fields_data['tracking_enabled']},
            'config': {
                'status': cfg.status if cfg else 'untracked',
                'create': bool(cfg and cfg.track_create), 'update': bool(cfg and cfg.track_update),
                'delete': bool(cfg and cfg.track_delete), 'read': bool(cfg and cfg.track_read),
                'view_time': bool(cfg and cfg.track_view_time), 'field_changes': bool(cfg and cfg.track_field_changes),
                'weight': cfg.weight if cfg else 1.0,
            },
        }
        return result

    # ------------------------------------------------------------------ reports: summary
    @api.model
    def get_summary_report(self, date_from=None, date_to=None, user_id=None, model_name=None, granularity='day'):
        """Daily / weekly / monthly statistics from the daily summaries (plus the
        live computation for days not yet rolled up)."""
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        granularity = granularity if granularity in report_utils.GRANULARITIES else 'day'
        per_day_model = agg.aggregate(self.env, start, end, ('summary_date',), scope, model_name, level='model')
        per_day_level = agg.aggregate(self.env, start, end, ('summary_date',), scope, None, level='day')
        per_user_day = agg.aggregate(self.env, start, end, ('user_id', 'summary_date'), scope, None, level='both')

        def blank():
            return {'created': 0, 'updated': 0, 'deleted': 0, 'viewed': 0, 'field_edits': 0, 'meaningful': 0,
                    'automated': 0, 'points': 0.0, 'pages': 0, 'reports': 0, 'dashboards': 0, 'searches': 0,
                    'active_minutes': 0.0, 'logins': 0, 'users': set()}

        buckets = {b: blank() for b in report_utils.iter_buckets(start, end, granularity)}
        for (day,), v in per_day_model.items():
            b = buckets.get(report_utils.bucket_start(day, granularity))
            if b is None:
                continue
            b['created'] += v['records_created']
            b['updated'] += v['records_updated']
            b['deleted'] += v['records_deleted']
            b['field_edits'] += v['field_edits']
            b['meaningful'] += v['meaningful_field_edits']
            b['automated'] += v['automated_changes']
            b['points'] += v['adoption_points']
        for (day,), v in per_day_level.items():
            b = buckets.get(report_utils.bucket_start(day, granularity))
            if b is None:
                continue
            b['viewed'] += v['records_viewed']
            b['pages'] += v['pages_viewed']
            b['reports'] += v['reports_viewed']
            b['dashboards'] += v['dashboards_viewed']
            b['searches'] += v['searches']
            b['active_minutes'] += v['active_minutes']
            b['logins'] += v['login_count']
        for (uid, day), v in per_user_day.items():
            b = buckets.get(report_utils.bucket_start(day, granularity))
            if b is not None and self._is_active(v):
                b['users'].add(uid)

        rows, totals = [], blank()
        all_users = set()
        for start_day, b in sorted(buckets.items()):
            rows.append({
                'bucket': fields.Date.to_string(start_day), 'date': fields.Date.to_string(start_day),
                'label': report_utils.bucket_label(start_day, granularity),
                'events': b['created'] + b['updated'] + b['deleted'],
                **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in b.items() if k != 'users'},
                'active_users': len(b['users']),
            })
            for k, v in b.items():
                if k == 'users':
                    all_users |= v
                else:
                    totals[k] += v
        total_row = {k: (round(v, 1) if isinstance(v, float) else v) for k, v in totals.items() if k != 'users'}
        total_row['active_users'] = len(all_users)
        total_row['events'] = total_row['created'] + total_row['updated'] + total_row['deleted']
        return {
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'granularity': granularity, 'rows': rows, 'totals': total_row,
            'model_filtered': bool(model_name),
            'last_rollup_date': fields.Date.to_string(self.env['adoption.settings']._get().last_rollup_date) or False,
        }

    # ------------------------------------------------------------------ reports: field changes
    @api.model
    def get_field_change_report(self, date_from=None, date_to=None, user_id=None, model_name=None,
                                meaningful_only=False, include_automated=False, kind=None,
                                limit=50, offset=0, export=False):
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        labels = self._labels()
        Change = self.env['adoption.field.change']
        domain = [('user_id', 'in', scope), ('activity_date', '>=', start), ('activity_date', '<=', end)]
        if model_name:
            domain.append(('model_name', '=', model_name))
        if meaningful_only:
            domain.append(('is_meaningful', '=', True))
        if not include_automated:
            domain.append(('is_automated', '=', False))
        if kind in ('update', 'initial', 'final'):
            domain.append(('change_kind', '=', kind))
        limit = _cap(limit, MAX_EXPORT_ROWS if export else MAX_ROWS)
        summary = Change._read_group(
            domain, ['model_name', 'field_name', 'field_label'],
            ['__count', 'user_id:count_distinct', 'change_datetime:max'], order='__count desc', limit=20)
        rows = Change.search(domain, limit=limit, offset=int(offset or 0))
        return {
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'total': Change.search_count(domain), 'offset': int(offset or 0), 'limit': limit,
            'summary': [{'model': labels.get(m, m), 'model_name': m, 'field': flabel or fname, 'name': fname,
                         'edits': n, 'users': u, 'last': fields.Datetime.to_string(last) if last else False}
                        for m, fname, flabel, n, u, last in summary],
            'rows': [{
                'id': c.id, 'when': fields.Datetime.to_string(c.change_datetime), 'user': c.user_id.name or '',
                'model': labels.get(c.model_name, c.model_name), 'record': c.record_name or ('#%s' % c.record_id),
                'field': c.field_label or c.field_name, 'old': c.old_value, 'new': c.new_value,
                'kind': c.change_kind, 'meaningful': c.is_meaningful, 'masked': c.is_masked,
                'automated': c.is_automated,
            } for c in rows],
        }
