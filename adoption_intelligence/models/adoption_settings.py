# -*- coding: utf-8 -*-
import re

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

FIELD_LIST_RE = re.compile(r'^[a-z0-9_]+(\s*,\s*[a-z0-9_]+)*$')


class AdoptionSettings(models.Model):
    """Singleton holding every global option.

    A model (not ``ir.config_parameter``) so values are validated by the ORM,
    shown in a normal form view, and read through a single cached call on the
    hot path of every tracked ORM operation.
    """
    _name = 'adoption.settings'
    _description = 'Adoption Intelligence Settings'

    name = fields.Char(default='Adoption Intelligence Settings', required=True)

    # --- tracking -----------------------------------------------------------
    tracking_enabled = fields.Boolean(
        default=True, help='Master switch. Off = nothing is captured anywhere.')
    internal_users_only = fields.Boolean(
        default=True, help='Ignore portal / public (share) users. Adoption is a '
                           'measure of employees using Odoo.')
    import_counts_as_automated = fields.Boolean(
        default=True, string='Imports count as automated',
        help='Mirrors the original, where Data Loader / Bulk API loads were '
             'classed as automation and earned no points. Untick to credit '
             'users for records they import through the UI.')
    max_value_length = fields.Integer(default=255)
    excluded_field_names = fields.Char(
        string='Extra excluded fields',
        help='Comma separated technical field names never captured on any model.')

    # --- browser tracking ----------------------------------------------------
    client_navigation_enabled = fields.Boolean(default=True, string='Track navigation')
    client_record_view_enabled = fields.Boolean(default=True, string='Track record views and view time')
    client_search_enabled = fields.Boolean(
        default=True, string='Count searches / filters',
        help='Only a count is sent. Search terms and filter values never leave the browser.')
    client_action_attempts_enabled = fields.Boolean(
        default=True, string='Count attempted actions',
        help='Counts save/create/delete/button attempts. Whether the operation '
             'SUCCEEDED is only ever taken from the server-side CRUD events.')
    idle_threshold_seconds = fields.Integer(default=120)
    heartbeat_interval_seconds = fields.Integer(default=30)
    stale_session_minutes = fields.Integer(default=10)

    # --- points (original defaults) -------------------------------------------
    points_create = fields.Float(default=3.0)
    points_update = fields.Float(default=1.0)
    points_meaningful_edit = fields.Float(default=2.0)
    points_page_view = fields.Float(default=0.5)

    # --- retention -------------------------------------------------------------
    retention_days_detail = fields.Integer(
        default=90, help='Detailed events, field changes, navigation and sessions. '
                         'Daily summaries, login summaries and scores are kept.')
    retention_days_errors = fields.Integer(default=30)

    # --- pipeline state ---------------------------------------------------------
    last_rollup_date = fields.Date(
        readonly=True, help='Every day up to and including this date has been '
                            'rolled up. Dashboards read stored summaries up to it '
                            'and compute later days live.')
    last_rollup_at = fields.Datetime(readonly=True)
    last_rollup_status = fields.Char(readonly=True)

    # ------------------------------------------------------------------ validation
    @api.constrains('max_value_length', 'idle_threshold_seconds', 'heartbeat_interval_seconds',
                    'stale_session_minutes', 'retention_days_detail', 'retention_days_errors')
    def _check_ranges(self):
        for rec in self:
            checks = (
                (20 <= rec.max_value_length <= 5000, _('Maximum value length must be 20-5000.')),
                (15 <= rec.idle_threshold_seconds <= 1800, _('Idle threshold must be 15-1800 seconds.')),
                (10 <= rec.heartbeat_interval_seconds <= 300, _('Heartbeat interval must be 10-300 seconds.')),
                (2 <= rec.stale_session_minutes <= 240, _('Stale session timeout must be 2-240 minutes.')),
                (7 <= rec.retention_days_detail <= 3650, _('Detail retention must be 7-3650 days.')),
                (1 <= rec.retention_days_errors <= 3650, _('Error retention must be 1-3650 days.')),
            )
            for ok, message in checks:
                if not ok:
                    raise ValidationError(message)
            if rec.heartbeat_interval_seconds >= rec.idle_threshold_seconds * 2:
                raise ValidationError(_('Heartbeat interval must be well below the idle threshold.'))

    @api.constrains('points_create', 'points_update', 'points_meaningful_edit', 'points_page_view')
    def _check_points(self):
        for rec in self:
            if min(rec.points_create, rec.points_update, rec.points_meaningful_edit,
                   rec.points_page_view) < 0:
                raise ValidationError(_('Points cannot be negative.'))

    @api.constrains('excluded_field_names')
    def _check_excluded_names(self):
        for rec in self:
            if rec.excluded_field_names and not FIELD_LIST_RE.match(rec.excluded_field_names.strip()):
                raise ValidationError(_('Excluded fields: comma separated technical names (a-z, 0-9, _).'))

    # ------------------------------------------------------------------ singleton
    @api.model_create_multi
    def create(self, vals_list):
        if self.sudo().search_count([]) or len(vals_list) > 1:
            raise UserError(_('There is only one Adoption Intelligence settings record.'))
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        if not self.env.context.get('module_uninstall'):
            raise UserError(_('The Adoption Intelligence settings record cannot be deleted.'))
        return super().unlink()

    @api.model
    def _get(self):
        record = self.sudo().search([], limit=1)
        if not record:
            record = self.sudo().create({'last_rollup_date': fields.Date.today()})
        return record

    @api.model
    def action_open_settings(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Adoption Intelligence Settings'),
            'res_model': 'adoption.settings',
            'res_id': self._get().id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------ hot path
    @api.model
    @tools.ormcache()
    def _runtime(self):
        """Plain-dict snapshot read by the tracking engine on every tracked ORM
        call.  Cached per registry; cleared on any settings / config change."""
        rec = self.sudo().search([], limit=1)
        excluded_users = self.env['res.users'].sudo().with_context(active_test=False).search(
            [('adoption_excluded', '=', True)]).ids
        extra = frozenset(
            n.strip() for n in (rec.excluded_field_names or '').split(',') if n.strip())
        return {
            'exists': bool(rec),
            'tracking_enabled': rec.tracking_enabled if rec else True,
            'internal_only': rec.internal_users_only if rec else True,
            'import_automated': rec.import_counts_as_automated if rec else True,
            'max_value_length': rec.max_value_length if rec else 255,
            'excluded_field_names': extra,
            'excluded_user_ids': frozenset(excluded_users),
            'points_create': rec.points_create if rec else 3.0,
            'points_update': rec.points_update if rec else 1.0,
            'points_meaningful': rec.points_meaningful_edit if rec else 2.0,
            'points_page': rec.points_page_view if rec else 0.5,
            'retention_days': rec.retention_days_detail if rec else 90,
            'retention_days_errors': rec.retention_days_errors if rec else 30,
            'idle_seconds': rec.idle_threshold_seconds if rec else 120,
            'heartbeat_seconds': rec.heartbeat_interval_seconds if rec else 30,
            'stale_minutes': rec.stale_session_minutes if rec else 10,
            'client_navigation': rec.client_navigation_enabled if rec else True,
            'client_record_view': rec.client_record_view_enabled if rec else True,
            'client_search': rec.client_search_enabled if rec else True,
            'client_actions': rec.client_action_attempts_enabled if rec else True,
        }
