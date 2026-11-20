# -*- coding: utf-8 -*-
from odoo import api, fields, models

from ..services import activity_aggregator as agg
from . import _compat


class AdoptionDailySummary(models.Model):
    """Aggregated metrics: one row per user x day x model, plus one cross-model
    row per user x day whose ``model_name`` is ``__ALL__``.  Dashboards read
    these (plus a live computation for days not yet rolled up), never the
    detail tables."""
    _name = 'adoption.daily.summary'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Daily Summary'
    _order = 'summary_date desc, user_id, model_name'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    summary_date = fields.Date(required=True, index=True)
    model_name = fields.Char(string='Model', required=True, index=True,
                             help='"__ALL__" = cross-model engagement row.')
    is_day_level = fields.Boolean(compute='_compute_day_level', store=True, index=True)
    records_created = fields.Float(digits=(16, 0))
    records_updated = fields.Float(digits=(16, 0))
    records_deleted = fields.Float(digits=(16, 0))
    records_viewed = fields.Float(digits=(16, 0))
    field_edits = fields.Float(digits=(16, 0))
    meaningful_field_edits = fields.Float(digits=(16, 0))
    distinct_fields_used = fields.Float(digits=(16, 0))
    automated_changes = fields.Float(digits=(16, 0))
    adoption_points = fields.Float(digits=(16, 2))
    pages_viewed = fields.Float(digits=(16, 0))
    reports_viewed = fields.Float(digits=(16, 0))
    dashboards_viewed = fields.Float(digits=(16, 0))
    searches = fields.Float(digits=(16, 0))
    active_minutes = fields.Float(digits=(16, 2))
    login_count = fields.Float(digits=(16, 0))
    session_count = fields.Float(digits=(16, 0))

    if _compat.HAS_CONSTRAINT:
        _key_uniq = models.Constraint('UNIQUE(user_id, summary_date, model_name)',
                                      'Only one summary per user, day and model.')
    else:
        _sql_constraints = [('key_uniq', 'unique(user_id, summary_date, model_name)',
                             'Only one summary per user, day and model.')]

    @api.depends('model_name')
    def _compute_day_level(self):
        for rec in self:
            rec.is_day_level = rec.model_name == agg.ALL

    @api.model
    def _cron_rollup(self):
        """Job 2: roll up every completed day since the last successful run."""
        return agg.rollup_pending(self.env)

    @api.model
    def recalculate_range(self, date_from, date_to):
        """Manual, idempotent recalculation (administrators)."""
        done = []
        day = fields.Date.to_date(date_from)
        end = fields.Date.to_date(date_to)
        if not agg.acquire_lock(self.env):
            return {'days': 0, 'busy': True}
        settings = self.env['adoption.settings']._get()
        while day <= end:
            result = agg.rollup_day(self.env, day, force=True)
            if result is not None:
                done.append(day)
            day = fields.Date.add(day, days=1)
        last = settings.last_rollup_date
        yesterday = fields.Date.subtract(fields.Date.context_today(self), days=1)
        # Advance the resume point only when the recalculated range is contiguous
        # with what the nightly job already completed (never create a gap).
        if done and (not last or done[0] <= fields.Date.add(last, days=1)):
            new_last = min(max(done), yesterday)
            if not last or new_last > last:
                settings.sudo().with_context(adoption_internal=True).write({
                    'last_rollup_date': new_last, 'last_rollup_at': fields.Datetime.now(),
                    'last_rollup_status': 'manual: %s' % new_last})
        return {'days': len(done), 'busy': False}
