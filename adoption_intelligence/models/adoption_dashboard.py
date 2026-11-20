# -*- coding: utf-8 -*-
"""Read side of the dashboards (called from OWL through ``orm.call``).

Authorisation is enforced HERE, on the server, never in JavaScript:

* ``_visible_user_ids`` is the only place that decides whose data a caller may
  see.  Ordinary users resolve to themselves; managers to the active internal
  users of the companies they are currently allowed to see (the same boundary
  the record rules draw).
* Detail reads (activity, field changes, sessions) run as the *caller*, so ACLs
  and record rules apply a second time.
* Aggregates over summaries use ``sudo()`` only after the scope above has been
  resolved and always pass an explicit ``user_ids`` list.
"""
import logging
import statistics
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import activity_aggregator as agg
from ..services import activity_tracker as tracker
from ..services import score_calculator as sc

_logger = logging.getLogger(__name__)
GROUP_USER = 'adoption_intelligence.group_adoption_user'
GROUP_MANAGER = 'adoption_intelligence.group_adoption_manager'
GROUP_ADMIN = 'adoption_intelligence.group_adoption_admin'
MAX_RANGE_DAYS = 400
LOW_MAINTENANCE = 30     # % (original: "maintained below 30%")
UNUSED_COVERAGE = 25     # % (original: cleanup candidates below 25%)
BAND_LABELS = dict([('power_user', 'Power User'), ('healthy', 'Healthy'),
                    ('needs_improvement', 'Needs Improvement'), ('at_risk', 'At Risk'),
                    ('inactive', 'Inactive')])


class _Rollback(Exception):
    pass


class AdoptionDashboard(models.AbstractModel):
    _name = 'adoption.dashboard'
    _description = 'Adoption Dashboard Data Service'

    # ------------------------------------------------------------------ authz
    @api.model
    def _flags(self):
        user = self.env.user
        return {'is_admin': user.has_group(GROUP_ADMIN), 'is_manager': user.has_group(GROUP_MANAGER)}

    @api.model
    def _require_manager(self):
        if not self._flags()['is_manager']:
            raise AccessError(_('This view is only available to Adoption Intelligence managers.'))

    @api.model
    def _visible_user_ids(self):
        if not self._flags()['is_manager']:
            return [self.env.uid]
        return self.env['res.users'].sudo().search([
            ('share', '=', False), ('active', '=', True), ('adoption_excluded', '=', False),
            ('company_ids', 'in', self.env.companies.ids)]).ids

    @api.model
    def _scope(self, user_id=None):
        """-> list of user ids the caller may see for this request."""
        visible = self._visible_user_ids()
        if user_id:
            user_id = int(user_id)
            if user_id not in visible and user_id != self.env.uid:
                raise AccessError(_("You are not allowed to see this user's adoption data."))
            return [user_id]
        return visible

    @api.model
    def _range(self, date_from, date_to):
        end = fields.Date.to_date(date_to) or fields.Date.context_today(self)
        start = fields.Date.to_date(date_from) or end - timedelta(days=29)
        if start > end:
            start, end = end, start
        if (end - start).days > MAX_RANGE_DAYS:
            raise UserError(_('Please choose a range of at most %s days.', MAX_RANGE_DAYS))
        return start, end

    # ------------------------------------------------------------------ init
    @api.model
    def get_init(self):
        flags = self._flags()
        today = fields.Date.context_today(self)
        names = {u.id: u.name for u in self.env['res.users'].sudo().browse(self._visible_user_ids())}
        configs = self.env['adoption.tracking.config'].sudo().search([])
        settings = self.env['adoption.settings']._get()
        return dict(flags, **{
            'uid': self.env.uid, 'user_name': self.env.user.name,
            'users': sorted(({'id': k, 'name': v} for k, v in names.items()), key=lambda r: r['name'].lower()),
            'models': [{'name': c.model_name, 'label': c.model_label or c.model_name,
                        'tracking': c.status == 'active'} for c in configs],
            'today': fields.Date.to_string(today),
            'default_from': fields.Date.to_string(today - timedelta(days=29)),
            'month_start': fields.Date.to_string(today.replace(day=1)),
            'last_rollup_date': fields.Date.to_string(settings.last_rollup_date) if settings.last_rollup_date else False,
            'retention_days': settings.retention_days_detail,
            'bands': [{'key': k, 'label': v} for k, v in BAND_LABELS.items()],
        })

    # ------------------------------------------------------------------ helpers
    @api.model
    def _labels(self):
        return {c.model_name: (c.model_label or c.model_name) for c in
                self.env['adoption.tracking.config'].sudo().with_context(active_test=False).search([])}

    @api.model
    def _user_names(self, ids):
        return {u.id: u.name for u in self.env['res.users'].sudo().with_context(active_test=False).browse(list(ids))}

    @staticmethod
    def _is_active(v):
        return (v['records_created'] + v['records_updated'] + v['records_deleted'] + v['field_edits'] > 0
                or v['active_minutes'] > 0 or v['login_count'] > 0)

    @api.model
    def _score_rows(self, scope, anchor):
        start = self.env['adoption.user.score']._period_bounds('month', anchor)[0]
        return self.env['adoption.user.score'].sudo().search([
            ('user_id', 'in', scope), ('period_type', '=', 'month'), ('period_start', '=', start)])

    # ------------------------------------------------------------------ overview
    @api.model
    def get_overview(self, date_from=None, date_to=None, user_id=None, model_name=None):
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        labels = self._labels()
        per_um = agg.aggregate(self.env, start, end, ('user_id', 'model_name'), scope, model_name, level='model')
        per_u_day_level = agg.aggregate(self.env, start, end, ('user_id',), scope, None, level='day')

        user_tot, model_tot, model_users = {}, {}, {}
        crud = {'created': 0, 'updated': 0, 'deleted': 0}
        automated = field_edits = meaningful = 0
        for (uid, model), v in per_um.items():
            ut = user_tot.setdefault(uid, {k: 0.0 for k in agg.MEASURES})
            mt = model_tot.setdefault(model, {k: 0.0 for k in agg.MEASURES})
            for k in agg.MEASURES:
                ut[k] += v[k]
                mt[k] += v[k]
            if v['records_created'] + v['records_updated'] + v['records_deleted'] > 0:
                model_users.setdefault(model, set()).add(uid)
            crud['created'] += v['records_created']
            crud['updated'] += v['records_updated']
            crud['deleted'] += v['records_deleted']
            automated += v['automated_changes']
            field_edits += v['field_edits']
            meaningful += v['meaningful_field_edits']
        engagement = {k: 0.0 for k in agg.MEASURES}
        for (uid,), v in per_u_day_level.items():
            ut = user_tot.setdefault(uid, {k: 0.0 for k in agg.MEASURES})
            for k in agg.MEASURES:
                ut[k] += v[k]
                engagement[k] += v[k]

        total_users = len(scope)
        active_users = sum(1 for uid in scope if uid in user_tot and self._is_active(user_tot[uid]))
        human_events = sum(crud.values())
        events_total = human_events + automated

        scores = self._score_rows(scope, end)
        score_values = [s.total_score for s in scores]
        avg_score = round(statistics.fmean(score_values), 1) if score_values else None
        bands = {k: 0 for k in BAND_LABELS}
        for s in scores:
            bands[s.adoption_band] += 1
        at_risk = bands['at_risk'] + bands['inactive']
        health = ('No data' if avg_score is None else 'Healthy' if avg_score >= 80 else
                  'Steady' if avg_score >= 60 else 'Needs attention' if avg_score >= 40 else 'At risk')

        def pct(n):
            return round(100.0 * n / total_users) if total_users else 0

        factors = [
            {'key': 'login', 'label': _('Login activity'), 'value': pct(sum(1 for u in scope if user_tot.get(u, {}).get('login_count', 0) > 0))},
            {'key': 'engage', 'label': _('Record engagement'), 'value': pct(sum(1 for u in scope if user_tot.get(u, {}).get('field_edits', 0) > 0))},
            {'key': 'coverage', 'label': _('Active coverage'), 'value': pct(active_users)},
            {'key': 'quality', 'label': _('Meaningful-field upkeep'), 'value': pct(sum(1 for u in scope if user_tot.get(u, {}).get('meaningful_field_edits', 0) > 0))},
        ]
        objects = sorted(({
            'model': m, 'label': labels.get(m, m),
            'events': t['records_created'] + t['records_updated'] + t['records_deleted'],
            'field_edits': t['field_edits'], 'users': len(model_users.get(m, ())),
            'created': t['records_created'], 'updated': t['records_updated'], 'deleted': t['records_deleted'],
            'viewed': t['records_viewed'],
        } for m, t in model_tot.items()), key=lambda o: -(o['events'] + o['field_edits']))

        trend = self._trend(start, end, scope, model_name)
        return {
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'model_filtered': bool(model_name),
            'kpis': {
                'total_users': total_users, 'active_users': active_users, 'users_at_risk': at_risk,
                'events_total': int(events_total), 'human_events': int(human_events),
                'automated_events': int(automated), 'crud': {k: int(v) for k, v in crud.items()},
                'field_edits': int(field_edits), 'meaningful_edits': int(meaningful),
                'active_minutes': round(engagement['active_minutes'], 1),
                'logins': int(engagement['login_count']), 'pages': int(engagement['pages_viewed']),
                'reports': int(engagement['reports_viewed']), 'dashboards': int(engagement['dashboards_viewed']),
                'searches': int(engagement['searches']),
                'avg_score': avg_score, 'health': health,
                'human_pct': round(100.0 * human_events / events_total) if events_total else 0,
            },
            'bands': bands, 'scored_users': len(score_values), 'factors': factors,
            'objects': objects[:8], 'trend': trend,
            'insights': self._insights(total_users, active_users, at_risk, scores, objects, events_total, automated),
            'last_rollup_date': fields.Date.to_string(self.env['adoption.settings']._get().last_rollup_date) or False,
        }

    @api.model
    def _trend(self, start, end, scope, model_name):
        by_day = agg.aggregate(self.env, start, end, ('summary_date',), scope, model_name, level='model')
        by_day_level = agg.aggregate(self.env, start, end, ('summary_date',), scope, None, level='day')
        out, day = [], start
        while day <= end:
            m, e = by_day.get((day,), {}), by_day_level.get((day,), {})
            out.append({
                'date': fields.Date.to_string(day),
                'field_edits': int(m.get('field_edits', 0)),
                'records': int(m.get('records_created', 0) + m.get('records_updated', 0)),
                'events': int(m.get('records_created', 0) + m.get('records_updated', 0) + m.get('records_deleted', 0)),
                'active_minutes': round(e.get('active_minutes', 0.0), 1),
            })
            day += timedelta(days=1)
        return out

    @api.model
    def _insights(self, total, active, at_risk, scores, objects, events_total, automated):
        """Rule based (no AI): prioritised actions from the live numbers."""
        out = []
        if at_risk:
            out.append({'impact': 'High', 'title': _('Re-engage %s at-risk user(s)', at_risk),
                        'detail': _('They are in the At Risk or Inactive band: a leading indicator of adoption regression.')})
        idle = total - active
        if idle > 0:
            out.append({'impact': 'High' if idle > 5 else 'Low', 'title': _('Activate %s idle user(s)', idle),
                        'detail': _('No captured activity in this period.')})
        if scores:
            top = max(scores, key=lambda s: s.total_score)
            out.append({'impact': 'Low', 'title': _('Celebrate your power user, %s', top.user_id.name),
                        'detail': _('Leads on adoption score (%.1f). Recognising it spreads the behaviour.', top.total_score)})
        if events_total:
            auto_pct = round(100.0 * automated / events_total)
            if auto_pct >= 40:
                out.append({'impact': 'Medium', 'title': _('%s%% of changes come from automation', auto_pct),
                            'detail': _('A high automation share can mask low human adoption. Confirm people enter the data that drives reporting.')})
            else:
                out.append({'impact': 'Low', 'title': _('%s%% of changes are human-driven', 100 - auto_pct),
                            'detail': _('Healthy balance between people and automation.')})
        if objects:
            out.append({'impact': 'Low', 'title': _('%s is your most-used model', objects[0]['label']),
                        'detail': _('Focus data-quality and coaching where usage is already highest.')})
        out.append({'impact': 'Low', 'title': _('Review field adoption monthly'),
                    'detail': _('Fields maintained by fewer than %s%% of users are candidates for cleanup or better guidance.', UNUSED_COVERAGE)})
        return out

    # ------------------------------------------------------------------ leaderboard
    @api.model
    def get_leaderboard(self, period_start=None, period_type='month', search=None):
        flags = self._flags()
        Score = self.env['adoption.user.score']
        today = fields.Date.context_today(self)
        start, end = Score._period_bounds(period_type if period_type in ('month', 'week') else 'month',
                                          period_start or today)
        scope = self._scope()
        scores = Score.sudo().search([('user_id', 'in', scope), ('period_type', '=', period_type),
                                      ('period_start', '=', start)], order='total_score desc, active_days desc')
        needle = (search or '').strip().lower()
        rows = []
        for rank, s in enumerate(scores, 1):
            if needle and needle not in s.user_id.name.lower():
                continue
            rows.append({
                'id': s.id, 'rank': rank, 'user_id': s.user_id.id, 'name': s.user_id.name,
                'total_score': s.total_score, 'band': s.adoption_band, 'band_label': BAND_LABELS[s.adoption_band],
                'active_days': s.active_days, 'records_created': s.records_created,
                'records_updated': s.records_updated, 'meaningful_edits': s.meaningful_edits,
                'active_minutes': s.active_minutes, 'logins': s.logins,
                'components': {c: getattr(s, '%s_score' % c) for c in sc.COMPONENTS},
                'notes': s.notes or '',
            })
        last = max(scores.mapped('calculation_datetime')) if scores else False
        return {
            'period': {'start': fields.Date.to_string(start), 'end': fields.Date.to_string(end), 'type': period_type},
            'rows': rows, 'weights': sc.WEIGHTS, 'restricted': not flags['is_manager'],
            'is_final': bool(scores) and all(scores.mapped('is_final')),
            'calculated_at': fields.Datetime.to_string(last) if last else False,
            'points': self._points_ranking(start, min(end, today), scope, needle),
            'can_recalculate': flags['is_admin'],
        }

    @api.model
    def _points_ranking(self, start, end, scope, needle=''):
        """Second, simpler ranking carried over from the original: activity
        points (create/update/meaningful, object-weighted, automation earns 0)
        plus a small credit per page, report and dashboard opened."""
        rt = self.env['adoption.settings']._runtime()
        per_u_model = agg.aggregate(self.env, start, end, ('user_id',), scope, None, level='model')
        per_u_day = agg.aggregate(self.env, start, end, ('user_id',), scope, None, level='day')
        names = self._user_names(scope)
        rows = []
        for uid in scope:
            m = per_u_model.get((uid,), {})
            d = per_u_day.get((uid,), {})
            pts = m.get('adoption_points', 0.0) + rt['points_page'] * (
                d.get('pages_viewed', 0) + d.get('reports_viewed', 0) + d.get('dashboards_viewed', 0))
            if pts <= 0 and not needle:
                continue
            if needle and needle not in names.get(uid, '').lower():
                continue
            rows.append({'user_id': uid, 'name': names.get(uid, ''), 'points': round(pts, 1),
                         'created': int(m.get('records_created', 0)), 'updated': int(m.get('records_updated', 0)),
                         'pages': int(d.get('pages_viewed', 0))})
        rows.sort(key=lambda r: -r['points'])
        for i, r in enumerate(rows, 1):
            r['rank'] = i
            r['medal'] = {1: 'gold', 2: 'silver', 3: 'bronze'}.get(i, '')
        return rows

    # ------------------------------------------------------------------ user explorer
    @api.model
    def get_user_explorer(self, user_id=None, date_from=None, date_to=None, model_name=None,
                          operation=None, limit=40, offset=0):
        start, end = self._range(date_from, date_to)
        uid = int((self._scope(user_id) or [self.env.uid])[0]) if user_id else self.env.uid
        scope = [uid]
        labels = self._labels()
        per_model = agg.aggregate(self.env, start, end, ('model_name',), scope, model_name, level='model')
        day_level = agg.aggregate(self.env, start, end, (), scope, None, level='day').get((), {k: 0.0 for k in agg.MEASURES})
        per_day = agg.aggregate(self.env, start, end, ('summary_date',), scope, None, level='both')
        active_days = sum(1 for v in per_day.values() if self._is_active(v))
        tot = {k: sum(v[k] for v in per_model.values()) for k in agg.MEASURES}
        score = self._score_rows(scope, end)[:1]
        domain = [('user_id', '=', uid), ('activity_date', '>=', start), ('activity_date', '<=', end)]
        if model_name:
            domain.append(('model_name', '=', model_name))
        act_domain = domain + ([('operation', '=', operation)] if operation else [])
        Log = self.env['adoption.activity.log']
        Change = self.env['adoption.field.change']
        activity = Log.search(act_domain, limit=int(limit), offset=int(offset))
        changes = Change.search(domain, limit=int(limit))
        Session = self.env['adoption.active.session']
        Nav = self.env['adoption.navigation.log']
        top_records = Session._read_group(
            domain + [('kind', '=', 'record')], ['model_name', 'record_id', 'record_name'],
            ['active_seconds:sum', '__count'], order='active_seconds:sum desc', limit=10)
        top_pages = Nav._read_group(
            domain + [('event_type', 'in', ('page_view', 'list_view', 'report_view', 'dashboard_view'))],
            ['page_name'], ['__count'], order='__count desc', limit=8)
        return {
            'user': {'id': uid, 'name': self._user_names([uid]).get(uid, '')},
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'kpis': {
                'created': int(tot['records_created']), 'updated': int(tot['records_updated']),
                'deleted': int(tot['records_deleted']), 'viewed': int(day_level['records_viewed']),
                'field_edits': int(tot['field_edits']), 'meaningful_edits': int(tot['meaningful_field_edits']),
                'automated': int(tot['automated_changes']), 'active_days': active_days,
                'logins': int(day_level['login_count']), 'reports': int(day_level['reports_viewed']),
                'dashboards': int(day_level['dashboards_viewed']), 'pages': int(day_level['pages_viewed']),
                'active_minutes': round(day_level['active_minutes'], 1),
            },
            'score': {
                'total': score.total_score, 'band': score.adoption_band,
                'band_label': BAND_LABELS.get(score.adoption_band, ''), 'is_final': score.is_final,
                'notes': score.notes or '',
                'components': {c: getattr(score, '%s_score' % c) for c in sc.COMPONENTS},
            } if score else None,
            'weights': sc.WEIGHTS,
            'by_model': sorted(({'model': m, 'label': labels.get(m, m), 'created': int(v['records_created']),
                                 'updated': int(v['records_updated']), 'deleted': int(v['records_deleted']),
                                 'viewed': int(v['records_viewed']), 'field_edits': int(v['field_edits']),
                                 'meaningful': int(v['meaningful_field_edits']), 'automated': int(v['automated_changes'])}
                                for m, v in per_model.items()), key=lambda r: -(r['created'] + r['updated'] + r['deleted'])),
            'trend': self._trend(start, end, scope, model_name),
            'activity': [{
                'id': a.id, 'when': fields.Datetime.to_string(a.activity_datetime), 'model': a.model_label or a.model_name,
                'record': a.record_name or ('#%s' % a.record_id), 'record_id': a.record_id, 'model_name': a.model_name,
                'operation': a.operation, 'type': a.activity_type, 'source': a.source,
                'automated': a.is_automated, 'changes': a.field_change_count, 'meaningful': a.meaningful_change_count,
            } for a in activity],
            'changes': [{
                'id': c.id, 'when': fields.Datetime.to_string(c.change_datetime), 'model': labels.get(c.model_name, c.model_name),
                'record': c.record_name or ('#%s' % c.record_id), 'field': c.field_label or c.field_name,
                'old': c.old_value, 'new': c.new_value, 'meaningful': c.is_meaningful, 'masked': c.is_masked,
                'kind': c.change_kind, 'automated': c.is_automated,
            } for c in changes],
            'top_records': [{'model': labels.get(m, m), 'record': n or ('#%s' % rid), 'record_id': rid,
                             'minutes': round((s or 0) / 60.0, 1), 'visits': c}
                            for m, rid, n, s, c in top_records],
            'top_pages': [{'name': p or _('(untitled)'), 'count': c} for p, c in top_pages],
            'has_more': len(activity) == int(limit),
        }

    # ------------------------------------------------------------------ field adoption
    @api.model
    def get_field_adoption(self, model_name=None, date_from=None, date_to=None, user_id=None, meaningful_only=False):
        """Which fields people actually maintain.  ``model_name`` empty = ALL tracked models.

        Statuses (never mix them up):
          observed      tracking covered the whole range, so zero edits really means "unused"
          partial       tracking started / stopped inside the range, or history expired: unknown
          not_observed  tracking is off for that model: unknown
        """
        start, end = self._range(date_from, date_to)
        scope = self._scope(user_id)
        population = max(len(scope), 1)
        Config = self.env['adoption.tracking.config'].sudo().with_context(active_test=False)
        configs = Config.search([('model_name', '=', model_name)] if model_name else [])
        cfg_by_model = {c.model_name: c for c in configs}
        labels = {c.model_name: c.model_label or c.model_name for c in configs}
        settings = self.env['adoption.settings']._get()
        today = fields.Date.context_today(self)
        warnings = []
        history_start = start
        if start < today - timedelta(days=settings.retention_days_detail):
            history_start = today - timedelta(days=settings.retention_days_detail)
            warnings.append(_('Field-level detail is kept for %s days; earlier history is not available.',
                              settings.retention_days_detail))
        domain = [('activity_date', '>=', start), ('activity_date', '<=', end), ('is_automated', '=', False),
                  ('change_kind', '!=', 'final'), ('user_id', 'in', scope)]
        if model_name:
            domain.append(('model_name', '=', model_name))
        field_cfg = {(c.model_name, f.field_name): f for c in configs for f in c.field_config_ids}
        rows, seen = [], set()
        for model, fname, flabel, edits, users, last in self.env['adoption.field.change'].sudo()._read_group(
                domain, ['model_name', 'field_name', 'field_label'],
                ['__count', 'user_id:count_distinct', 'change_datetime:max'], limit=2000):
            fc = field_cfg.get((model, fname))
            seen.add((model, fname))
            coverage = min(100, round(100.0 * users / population))
            rows.append({
                'key': '%s.%s' % (model, fname), 'model': model, 'model_label': labels.get(model, model),
                'field': fname, 'label': flabel or fname, 'edits': edits, 'users': users, 'coverage': coverage,
                'last_changed': fields.Datetime.to_string(last) if last else False,
                'meaningful': bool(fc and fc.is_meaningful), 'weight': fc.weight if fc else 1.0,
                'category': (fc.category if fc else '') or '', 'status': 'low' if coverage < LOW_MAINTENANCE else 'ok',
            })
        # Configured fields with no edits: "observed and unused" vs "not enough history to say".
        unused, unknown = [], []
        for (model, fname), fc in field_cfg.items():
            if (model, fname) in seen or not fc.is_tracked:
                continue
            status = self._observation_status(cfg_by_model.get(model), start)
            entry = {'key': '%s.%s' % (model, fname), 'model': model, 'model_label': labels.get(model, model),
                     'field': fname, 'label': fc.field_label or fname, 'meaningful': fc.is_meaningful,
                     'category': fc.category or '', 'status': status}
            (unused if status == 'observed' and history_start <= start else unknown).append(entry)
        if meaningful_only:
            rows = [r for r in rows if r['meaningful']]
            unused = [r for r in unused if r['meaningful']]
            unknown = [r for r in unknown if r['meaningful']]
        rows.sort(key=lambda r: -r['edits'])
        late = [c for c in configs if c.observed_since and c.observed_since.date() > start]
        if len(late) == 1 and model_name:
            warnings.append(_('Tracking of this model started on %s; earlier activity was not observed.',
                              fields.Date.to_string(late[0].observed_since.date())))
        elif late:
            warnings.append(_('Tracking started inside this range for: %s. Earlier activity of those models was not observed.',
                              ', '.join('%s (%s)' % (labels[c.model_name], fields.Date.to_string(c.observed_since.date()))
                                        for c in late[:6])))
        enabled = [c for c in configs if c.is_tracking_enabled and c.active and c.track_update and c.track_field_changes]
        single = cfg_by_model.get(model_name) if model_name else None
        return {
            'model': model_name or False,
            'label': (single.model_label if single else model_name) if model_name else _('All models'),
            'all_models': not model_name,
            'range': {'from': fields.Date.to_string(start), 'to': fields.Date.to_string(end)},
            'population': population, 'rows': rows,
            'most_maintained': rows[:5], 'least_maintained': sorted(rows, key=lambda r: r['edits'])[:5],
            'underused': [r for r in rows if r['coverage'] < UNUSED_COVERAGE],
            'unused': unused, 'unknown': unknown, 'warnings': warnings,
            'tracking_enabled': bool(enabled) if not model_name else bool(single and single in enabled),
            'tracked_models': len(enabled),
        }

    @api.model
    def _observation_status(self, cfg, start):
        """observed  : tracking was on for the whole range -> zero edits really means unused.
        partial   : tracking started/stopped inside the range -> unknown.
        not_observed: tracking is off / model not configured."""
        if not cfg or not (cfg.is_tracking_enabled and cfg.active and cfg.track_update and cfg.track_field_changes):
            return 'not_observed'
        if cfg.observed_since and cfg.observed_since.date() > start:
            return 'partial'
        if cfg.last_disabled_at and cfg.last_disabled_at.date() >= start:
            return 'partial'
        return 'observed'

    # ------------------------------------------------------------------ health
    @api.model
    def get_health(self):
        self._require_manager()
        env = self.env
        S = env['adoption.settings']._get()
        now = fields.Datetime.now()
        day7, day1 = now - timedelta(days=7), now - timedelta(days=1)
        checks = []

        def add(code, title, status, detail, fix=''):
            checks.append({'code': code, 'title': title, 'status': status, 'detail': detail, 'fix': fix})

        add('settings', _('Settings'), 'ok' if S.tracking_enabled else 'fail',
            _('Tracking is enabled.') if S.tracking_enabled else _('The master tracking switch is OFF: nothing is being captured.'),
            '' if S.tracking_enabled else _('Adoption Intelligence > Configuration > Settings.'))
        configs = env['adoption.tracking.config'].sudo().search([])
        active = configs.filtered(lambda c: c.status == 'active')
        missing = configs.filtered(lambda c: c.status == 'missing')
        add('models', _('Tracked models'), 'ok' if active else 'warn',
            _('%(a)s model(s) tracked, %(m)s configured but not installed.', a=len(active), m=len(missing)),
            '' if active else _('Add models under Configuration > Tracked Models.'))
        Log = env['adoption.activity.log'].sudo()
        recent = Log.search_count([('activity_datetime', '>=', day7)])
        add('capture', _('Server-side CRUD capture'), 'ok' if recent else ('warn' if active else 'ok'),
            _('%s events in the last 7 days.', recent),
            '' if recent or not active else _('No events although models are tracked. Run the self-test.'))
        nav24 = env['adoption.navigation.log'].sudo().search_count([('navigation_datetime', '>=', day1)])
        add('client', _('Web-client tracker'), 'ok' if nav24 else 'warn',
            _('%s navigation events in the last 24 hours.', nav24),
            '' if nav24 else _('No browser telemetry. Reload the web client (assets) and check the browser console.'))
        logins7 = env['adoption.login.summary'].sudo().search_count([('login_date', '>=', fields.Date.to_date(day7)), ('login_count', '>', 0)])
        add('logins', _('Login capture'), 'ok' if logins7 or not nav24 else 'warn',
            _('%s user-days with a recorded login in the last 7 days.', logins7),
            '' if logins7 or not nav24 else _('Browser activity but no logins: verify that res.users._update_last_login is called by this Odoo 19 build (docs/LIMITATIONS.md).'))
        for xml_id, label in (('cron_login_sync', _('Job 1: login/session sync')), ('cron_rollup', _('Job 2: daily rollup')),
                              ('cron_scores', _('Job 3: scoring')), ('cron_retention', _('Job 4: retention'))):
            cron = env.ref('adoption_intelligence.%s' % xml_id, raise_if_not_found=False)
            if not cron:
                add(xml_id, label, 'fail', _('Scheduled action missing.'))
            elif not cron.active:
                add(xml_id, label, 'warn', _('Scheduled action is disabled.'))
            else:
                late = cron.lastcall and (now - cron.lastcall) > timedelta(hours=36)
                add(xml_id, label, 'warn' if late else 'ok',
                    _('Last run: %s.', fields.Datetime.to_string(cron.lastcall) if cron.lastcall else _('never (waiting for first run)')),
                    _('Has not run in 36 hours: is the Odoo cron worker running?') if late else '')
        lag = (fields.Date.context_today(self) - S.last_rollup_date).days if S.last_rollup_date else None
        failing = (S.last_rollup_status or '').startswith('FAILED')
        add('rollup', _('Daily rollup'), 'fail' if failing else ('warn' if lag is None or lag > 2 else 'ok'),
            _('Rolled up through %(d)s (%(s)s).', d=S.last_rollup_date or '-', s=S.last_rollup_status or '-'),
            _('See the error log, then Recalculate.') if failing or (lag or 0) > 2 else '')
        errors = env['adoption.error.log'].sudo().search_count([('occurred_at', '>=', day7), ('severity', '=', 'error')])
        add('errors', _('Tracking errors'), 'ok' if not errors else 'warn',
            _('%s error(s) in the last 7 days.', errors), _('Open Configuration > Error Log.') if errors else '')
        cutoff = fields.Date.context_today(self) - timedelta(days=S.retention_days_detail + 7)
        backlog = Log.search_count([('activity_date', '<', cutoff)])
        add('retention', _('Retention backlog'), 'ok' if not backlog else 'warn',
            _('%s expired detail row(s) waiting to be purged.', backlog))
        stale = env['adoption.active.session'].sudo().search_count([('state', '=', 'open'), ('last_beat_at', '<', now - timedelta(minutes=S.stale_session_minutes * 3))])
        add('sessions', _('Open sessions'), 'ok' if not stale else 'warn', _('%s session(s) overdue for closing.', stale))
        order = {'fail': 0, 'warn': 1, 'ok': 2}
        worst = min((c['status'] for c in checks), key=lambda s: order[s])
        return {'checks': checks, 'overall': worst, 'generated_at': fields.Datetime.to_string(now)}

    # ------------------------------------------------------------------ self test
    @api.model
    def run_self_test(self):
        """Proves the whole capture chain on this database using a throw-away
        res.partner inside a savepoint that is ALWAYS rolled back, so nothing
        persists (neither the partner nor its audit rows)."""
        if not self._flags()['is_admin']:
            raise AccessError(_('Only administrators can run the self-test.'))
        cfg = self.env['adoption.tracking.config']._tracking_map().get('res.partner')
        if not cfg or not (cfg['create'] and cfg['update'] and cfg['delete']):
            return {'ok': False, 'steps': [], 'message': _('Enable create/update/delete tracking for res.partner first.')}
        steps = []

        def step(name, ok, detail=''):
            steps.append({'name': name, 'ok': bool(ok), 'detail': detail})

        Log = self.env['adoption.activity.log'].sudo()
        Change = self.env['adoption.field.change'].sudo()
        try:
            with self.env.cr.savepoint():
                Partner = self.env['res.partner'].with_context(adoption_source='web')
                state = tracker.txn_state(self.env)
                partner = Partner.create({'name': 'Adoption self-test probe', 'phone': '111'})
                pid = partner.id
                state.get('seen', set()).clear()               # simulate separate requests
                partner.write({'phone': '222'})
                state.get('seen', set()).clear()
                partner.write({'phone': '222'})                # unchanged -> must not log
                state.get('seen', set()).clear()
                partner.unlink()
                logs = Log.search([('model_name', '=', 'res.partner'), ('record_id', '=', pid)], order='id')
                ops = [(r.operation, r.activity_type, r.is_automated) for r in logs]
                step('create / update / delete each produced exactly one event',
                     [o[0] for o in ops] == ['create', 'update', 'delete'], str([o[0] for o in ops]))
                step('events are attributed to you as primary, not automated',
                     bool(ops) and all(o[1] == 'primary' and not o[2] for o in ops))
                upd = logs.filtered(lambda r: r.operation == 'update')
                chg = Change.search([('activity_log_id', 'in', upd.ids)])
                step('update stored exactly one field change (phone 111 -> 222)',
                     len(chg) == 1 and (chg.field_name, chg.old_value, chg.new_value) == ('phone', '111', '222'),
                     str([(c.field_name, c.old_value, c.new_value) for c in chg]))
                step('an unchanged write created no extra event', len(upd) == 1)
                raise _Rollback()
        except _Rollback:
            pass
        except Exception as exc:  # noqa: BLE001
            step('self-test could not complete', False, str(exc)[:300])
        left = self.env['res.partner'].sudo().search_count([('name', '=', 'Adoption self-test probe')])
        step('nothing was left behind (rolled back)', left == 0)
        return {'ok': all(s['ok'] for s in steps), 'steps': steps, 'message': ''}
