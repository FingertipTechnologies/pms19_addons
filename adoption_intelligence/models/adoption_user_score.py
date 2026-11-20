# -*- coding: utf-8 -*-
import calendar
import logging
from datetime import date, timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

from ..services import activity_aggregator as agg
from ..services import score_calculator as sc
from . import _compat

_logger = logging.getLogger(__name__)

BANDS = [
    ('power_user', 'Power User'), ('healthy', 'Healthy'),
    ('needs_improvement', 'Needs Improvement'), ('at_risk', 'At Risk'),
    ('inactive', 'Inactive'),
]


class AdoptionUserScore(models.Model):
    """Score of one user for one period.

    Each ``*_score`` is the *weighted* contribution (``0..weight``), so the six
    columns add up to ``total_score``.  Method: services/score_calculator.py.
    """
    _name = 'adoption.user.score'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption User Score'
    _order = 'period_start desc, total_score desc'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    period_type = fields.Selection([('month', 'Month'), ('week', 'Week'), ('custom', 'Custom')],
                                   required=True, default='month', index=True)
    period_start = fields.Date(required=True, index=True)
    period_end = fields.Date(required=True)
    period_key = fields.Char(required=True, index=True)
    is_final = fields.Boolean(help='False while the period is still in progress or not yet fully rolled up.')

    presence_score = fields.Float(digits=(16, 2))
    data_activity_score = fields.Float(digits=(16, 2))
    process_compliance_score = fields.Float(digits=(16, 2))
    feature_adoption_score = fields.Float(digits=(16, 2))
    engagement_score = fields.Float(digits=(16, 2))
    data_quality_score = fields.Float(digits=(16, 2))
    total_score = fields.Float(digits=(16, 2), index=True)
    adoption_band = fields.Selection(BANDS, required=True, index=True)

    active_days = fields.Integer()
    records_created = fields.Integer()
    records_updated = fields.Integer()
    records_deleted = fields.Integer()
    field_edits = fields.Integer()
    meaningful_edits = fields.Integer()
    objects_used = fields.Integer()
    reports_viewed = fields.Integer()
    dashboards_viewed = fields.Integer()
    active_minutes = fields.Float(digits=(16, 1))
    logins = fields.Integer()
    notes = fields.Text(help='Why a component is 0 / how a benchmark was chosen.')
    calculation_datetime = fields.Datetime(default=fields.Datetime.now)

    if _compat.HAS_CONSTRAINT:
        _key_uniq = models.Constraint('UNIQUE(period_key)', 'Score already exists for this user and period.')
    else:
        _sql_constraints = [('key_uniq', 'unique(period_key)', 'Score already exists for this user and period.')]

    # ------------------------------------------------------------------ periods
    @api.model
    def _period_bounds(self, period_type, anchor):
        anchor = fields.Date.to_date(anchor)
        if period_type == 'week':
            start = anchor - timedelta(days=anchor.weekday())
            return start, start + timedelta(days=6)
        start = anchor.replace(day=1)
        return start, anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])

    # ------------------------------------------------------------------ totals
    @api.model
    def _load_totals(self, start, end, user_ids):
        """Totals per user, built from the daily summaries (never raw events)."""
        totals = {uid: sc.Totals(user_id=uid) for uid in user_ids}
        by_model = agg.aggregate(self.env, start, end, ('user_id', 'model_name'), user_ids, level='model')
        for (uid, _model), v in by_model.items():
            t = totals.get(uid)
            if not t:
                continue
            touched = v['records_created'] + v['records_updated']
            t.records_touched += touched
            t.meaningful_edits += v['meaningful_field_edits']
            t.field_edits += v['field_edits']
            t.distinct_fields += v['distinct_fields_used']
            if touched > 0:
                t.objects_used += 1
        by_day_level = agg.aggregate(self.env, start, end, ('user_id',), user_ids, level='day')
        for (uid,), v in by_day_level.items():
            t = totals.get(uid)
            if t:
                t.reports_and_dashboards += v['reports_viewed'] + v['dashboards_viewed']
                t.active_minutes += v['active_minutes']
                t.logins += v['login_count']
        per_day = agg.aggregate(self.env, start, end, ('user_id', 'summary_date'), user_ids, level='both')
        for (uid, _day), v in per_day.items():
            t = totals.get(uid)
            if t and (v['records_created'] + v['records_updated'] > 0
                      or v['active_minutes'] > 0 or v['login_count'] > 0):
                t.active_days += 1
        return totals

    @api.model
    def _population(self):
        """Who is scored: active internal users that are not excluded."""
        return self.env['res.users'].sudo().search([
            ('share', '=', False), ('active', '=', True), ('adoption_excluded', '=', False)]).ids

    # ------------------------------------------------------------------ calculate
    @api.model
    def calculate_period(self, start, end, period_type='month'):
        """Idempotent: re-running a period updates the same rows."""
        if not agg.acquire_lock(self.env):
            _logger.info('Adoption scoring already running elsewhere; skipping.')
            return 0
        start, end = fields.Date.to_date(start), fields.Date.to_date(end)
        user_ids = self._population()
        totals = self._load_totals(start, end, user_ids)
        benchmarks = sc.compute_benchmarks(list(totals.values()))
        settings = self.env['adoption.settings']._get()
        natural_end = self._period_bounds(period_type, start)[1] if period_type != 'custom' else end
        is_final = bool(settings.last_rollup_date and natural_end <= settings.last_rollup_date - timedelta(days=agg.SAFE_LAG_DAYS))
        Score = self.sudo().with_context(adoption_internal=True)
        existing = {r.period_key: r for r in Score.search([('user_id', 'in', user_ids), ('period_start', '=', start),
                                                           ('period_type', '=', period_type)])}
        now = fields.Datetime.now()
        creates = []
        for uid, t in totals.items():
            key = '%s|%s|%s|%s' % (uid, period_type, start, end if period_type == 'custom' else '')
            res = sc.score_user(t, benchmarks)
            vals = {
                'user_id': uid, 'period_type': period_type, 'period_start': start, 'period_end': end,
                'period_key': key, 'is_final': is_final, 'calculation_datetime': now,
                'active_days': t.active_days, 'field_edits': int(t.field_edits),
                'meaningful_edits': int(t.meaningful_edits), 'objects_used': int(t.objects_used),
                'active_minutes': round(t.active_minutes, 1), 'logins': int(t.logins),
                'total_score': res['total_score'], 'adoption_band': res['adoption_band'],
                'notes': res['notes'],
            }
            for comp in sc.COMPONENTS:
                vals['%s_score' % comp] = res['%s_score' % comp]
            rec = existing.get(key)
            if rec:
                rec.write(vals)
            else:
                creates.append(vals)
        if creates:
            Score.create(creates)
        self._fill_detail_metrics(start, end, user_ids, period_type)
        return len(totals)

    @api.model
    def _fill_detail_metrics(self, start, end, user_ids, period_type):
        """created/updated/deleted and report/dashboard counts for the table."""
        by_user = agg.aggregate(self.env, start, end, ('user_id',), user_ids, level='both')
        Score = self.sudo().with_context(adoption_internal=True)
        for score in Score.search([('user_id', 'in', user_ids), ('period_start', '=', start),
                                   ('period_type', '=', period_type)]):
            v = by_user.get((score.user_id.id,))
            if v:
                score.write({'records_created': int(v['records_created']),
                             'records_updated': int(v['records_updated']),
                             'records_deleted': int(v['records_deleted']),
                             'reports_viewed': int(v['reports_viewed']),
                             'dashboards_viewed': int(v['dashboards_viewed'])})

    # ------------------------------------------------------------------ jobs / actions
    @api.model
    def _cron_calculate_scores(self):
        """Job 3: score the current month (and the previous one for a few days
        after month-end so it is finalised).  Rolls up first if the rollup job
        has not run, so the order of the cron schedule can never matter."""
        agg.rollup_pending(self.env)
        today = fields.Date.context_today(self)
        periods = {self._period_bounds('month', today)}
        if today.day <= 3:
            periods.add(self._period_bounds('month', today.replace(day=1) - timedelta(days=1)))
        for start, end in sorted(periods):
            self.calculate_period(start, end, 'month')
        return len(periods)

    @api.model
    def recalculate(self, period_start, period_type='month'):
        """Administrator action: recompute (and re-roll-up) one period."""
        if not self.env.user.has_group('adoption_intelligence.group_adoption_admin'):
            raise AccessError(_('Only Adoption Intelligence administrators can recalculate scores.'))
        start, end = self._period_bounds(period_type, period_start)
        yesterday = fields.Date.subtract(fields.Date.context_today(self), days=1)
        if start <= yesterday:
            self.env['adoption.daily.summary'].recalculate_range(start, min(end, yesterday))
        return self.calculate_period(start, end, period_type)
