# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

from ..services.env_utils import in_test_mode
from . import _compat

_logger = logging.getLogger(__name__)
PURGE_BATCH = 5000
PURGE_MAX_BATCHES = 20


class AdoptionActivityLog(models.Model):
    """One row per record per *successful* ORM operation.

    Written inside the business transaction: if that transaction rolls back
    the row disappears with it, so a rolled-back save can never be reported
    as having happened.
    """
    _name = 'adoption.activity.log'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Activity Log'
    _order = 'activity_datetime desc, id desc'
    _rec_name = 'record_name'

    user_id = fields.Many2one('res.users', string='User', index=True, ondelete='set null')
    user_name = fields.Char(help='Denormalised so history survives user deletion.')
    company_id = fields.Many2one('res.company', index=True, ondelete='set null')
    model_name = fields.Char(string='Model', required=True, index=True)
    model_label = fields.Char(string='Model name')
    record_id = fields.Integer(string='Record ID', index=True)
    record_name = fields.Char(string='Record')
    operation = fields.Selection([
        ('create', 'Create'), ('update', 'Update'), ('delete', 'Delete'),
    ], required=True, index=True)
    activity_datetime = fields.Datetime(required=True, index=True, string='DateTime')
    activity_date = fields.Date(required=True, index=True, string='Date',
                                help='Date in the acting user\'s time zone.')
    source = fields.Selection([
        ('web', 'Web client'), ('api', 'External API'), ('import', 'Import'),
        ('automation', 'Automation / cron'), ('other', 'Other'),
    ], required=True, index=True)
    activity_type = fields.Selection([
        ('primary', 'Primary'), ('secondary', 'Secondary'),
    ], required=True, default='primary', index=True,
        help='Primary = the person\'s own operation. Secondary = a follow-on '
             'operation on a record already touched in the same transaction, or '
             'an _inherits delegation. Secondary earns no points.')
    is_automated = fields.Boolean(index=True, string='Automated')
    session_identifier = fields.Char(help='Hash of the login session. Never the session id itself.')
    transaction_id = fields.Char(index=True, help='Groups every event of one database transaction.')
    field_change_count = fields.Integer()
    meaningful_change_count = fields.Integer()
    adoption_points = fields.Float(digits=(16, 2))
    field_change_ids = fields.One2many('adoption.field.change', 'activity_log_id', string='Field changes')

    if _compat.HAS_INDEX:
        _user_date_idx = models.Index('(user_id, activity_date)')
        _model_date_idx = models.Index('(model_name, activity_date)')
    else:
        def init(self):
            _compat.ensure_index(self.env.cr, 'adoption_activity_log_user_date_idx',
                                 self._table, ['user_id', 'activity_date'])
            _compat.ensure_index(self.env.cr, 'adoption_activity_log_model_date_idx',
                                 self._table, ['model_name', 'activity_date'])

    # ------------------------------------------------------------------ retention
    @api.model
    def _cron_purge_expired(self):
        """Delete expired detail, in bounded batches, never beyond what has been
        rolled up (so no activity is ever lost before it is summarised)."""
        settings = self.env['adoption.settings']._get()
        rollup = settings.last_rollup_date
        if not rollup:
            _logger.info('Adoption retention skipped: nothing rolled up yet.')
            return False
        today = fields.Date.context_today(self)
        runtime = self.env['adoption.settings']._runtime()
        deleted = 0
        per_model = {name: cfg['retention_days'] for name, cfg in
                     self.env['adoption.tracking.config']._tracking_map().items() if cfg['retention_days']}

        def cutoff(days):
            return min(today - timedelta(days=days), rollup)   # never delete days that are not final

        Internal = lambda m: self.env[m].sudo().with_context(adoption_internal=True, adoption_retention=True)  # noqa: E731
        base_cut = cutoff(runtime['retention_days'])
        # per-model overrides first (their own cut-off), then everything else
        for model_name, days in per_model.items():
            deleted += self._purge('adoption.activity.log', [
                ('model_name', '=', model_name), ('activity_date', '<', cutoff(days))], Internal)
        override_models = list(per_model)
        domain = [('activity_date', '<', base_cut)]
        if override_models:
            domain.append(('model_name', 'not in', override_models))
        deleted += self._purge('adoption.activity.log', domain, Internal)   # field changes cascade (FK)
        deleted += self._purge('adoption.navigation.log', [('activity_date', '<', base_cut)], Internal)
        deleted += self._purge('adoption.active.session', [('activity_date', '<', base_cut)], Internal)
        err_cut = fields.Datetime.now() - timedelta(days=runtime['retention_days_errors'])
        deleted += self._purge('adoption.error.log', [('occurred_at', '<', err_cut)], Internal)
        _logger.info('Adoption retention removed %s detail rows (cut-off %s).', deleted, base_cut)
        return deleted

    @api.model
    def _purge(self, model_name, domain, internal):
        total = 0
        for _i in range(PURGE_MAX_BATCHES):
            batch = internal(model_name).search(domain, limit=PURGE_BATCH)
            if not batch:
                break
            batch.unlink()
            total += len(batch)
            if not in_test_mode(self.env):
                self.env.cr.commit()     # keep transactions short on big purges
        return total
