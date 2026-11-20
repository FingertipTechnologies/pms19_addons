# -*- coding: utf-8 -*-
from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError

from . import _compat

# Models that must never be tracked.  ``adoption.*`` is what prevents the
# tracker from recording its own log writes (infinite recursion); the rest is
# high-volume plumbing that says nothing about people using Odoo.
BLOCKED_PREFIXES = ('adoption.', 'ir.', 'bus.', 'base.', 'res.config', 'auth_totp')
BLOCKED_MODELS = frozenset({
    'mail.message', 'mail.notification', 'mail.followers', 'mail.mail',
    'mail.tracking.value', 'res.users.log', 'res.users.apikeys',
    'res.users.settings', 'res.device', 'res.device.log',
})

# (model, object weight, track read/view?, [(field, weight, category), ...])
# Weights/categories mirror the original Salesforce seed.  Only fields that
# exist in the installed version are created.
DEFAULT_MODELS = [
    ('res.users', 1.0, False, [('name', 1, 'User Data Quality'), ('email', 1, 'User Data Quality')]),
    ('res.partner', 1.0, True, [
        ('phone', 1, 'Account Data Quality'), ('email', 2, 'Contact Data Quality'),
        ('industry_id', 1, 'Account Data Quality'), ('vat', 1, 'Account Data Quality')]),
    ('crm.lead', 2.0, True, [
        ('stage_id', 3, 'Pipeline'), ('expected_revenue', 3, 'Pipeline'),
        ('date_deadline', 2, 'Pipeline'), ('probability', 2, 'Pipeline'),
        ('priority', 1, 'Pipeline'), ('source_id', 1, 'Lead Management'),
        ('user_id', 1, 'Process Hygiene')]),
    ('sale.order', 1.0, True, [
        ('state', 3, 'Sales'), ('partner_id', 2, 'Sales'),
        ('validity_date', 1, 'Sales'), ('payment_term_id', 1, 'Sales')]),
    ('sale.order.line', 1.0, False, [
        ('product_id', 2, 'Sales'), ('product_uom_qty', 2, 'Sales'),
        ('price_unit', 2, 'Sales'), ('discount', 1, 'Sales')]),
    ('product.product', 1.0, True, [
        ('list_price', 2, 'Catalogue'), ('standard_price', 2, 'Catalogue'),
        ('categ_id', 1, 'Catalogue')]),
    ('account.move', 1.0, True, [
        ('partner_id', 2, 'Accounting'), ('invoice_date', 2, 'Accounting'),
        ('invoice_date_due', 2, 'Accounting'), ('state', 3, 'Accounting')]),
    ('project.task', 1.0, True, [
        ('stage_id', 3, 'Activity Management'), ('user_ids', 2, 'Activity Management'),
        ('date_deadline', 1, 'Activity Management'), ('priority', 1, 'Activity Management')]),
    ('project.project', 1.0, True, [
        ('stage_id', 2, 'Activity Management'), ('user_id', 1, 'Activity Management'),
        ('date', 1, 'Activity Management')]),
]


class AdoptionTrackingConfig(models.Model):
    _name = 'adoption.tracking.config'
    _description = 'Adoption Tracking Configuration'
    _rec_name = 'model_label'
    _order = 'model_name'

    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade', index=True,
        domain="[('transient', '=', False)]")
    model_name = fields.Char(related='model_id.model', store=True, index=True, string='Technical name')
    model_label = fields.Char(related='model_id.name', store=True, string='Model name')
    active = fields.Boolean(default=True)
    is_tracking_enabled = fields.Boolean(default=True, string='Tracking enabled')
    track_create = fields.Boolean(default=True)
    track_update = fields.Boolean(default=True)
    track_delete = fields.Boolean(default=True)
    track_read = fields.Boolean(
        default=False, string='Track record views',
        help='READ tracking. Instrumented in the web client (a record opened in '
             'a form view), never by intercepting server-side read() calls.')
    track_view_time = fields.Boolean(
        default=False, string='Track view time',
        help='Estimate active time spent on each record of this model.')
    track_field_changes = fields.Boolean(
        default=True, help='Store old/new value of every changed field. Off = only '
                           'record-level events (no per-field detail).')
    track_all_fields = fields.Boolean(
        default=True, help='Capture every eligible stored field. Off = only fields '
                           'listed below with "Tracked" ticked.')
    track_x2many = fields.Boolean(
        default=False, string='Track x2many fields',
        help='One2many / Many2many changes (e.g. order lines). Off by default: the '
             'lines are normally tracked as their own model.')
    weight = fields.Float(default=1.0, string='Object weight',
                          help='Multiplies adoption points earned on this model.')
    retention_days = fields.Integer(
        string='Retention override (days)', default=0,
        help='0 = use the global detail retention.')
    field_config_ids = fields.One2many('adoption.field.config', 'tracking_config_id', string='Fields')

    observed_since = fields.Datetime(readonly=True, copy=False,
                                     help='When tracking last became active. History before this is unknown.')
    last_disabled_at = fields.Datetime(readonly=True, copy=False)
    model_available = fields.Boolean(compute='_compute_status', string='Model installed')
    status = fields.Selection([
        ('active', 'Tracking'), ('disabled', 'Disabled'), ('missing', 'Model not installed'),
    ], compute='_compute_status')

    if _compat.HAS_CONSTRAINT:
        _model_uniq = models.Constraint('UNIQUE(model_id)', 'This model is already configured.')
    else:
        _sql_constraints = [('model_uniq', 'unique(model_id)', 'This model is already configured.')]

    # ------------------------------------------------------------------ helpers
    @api.model
    def _model_check(self, model_name):
        """(ok, reason). Used by constraints, the seeder and the dashboard."""
        if not model_name:
            return False, _('No model selected.')
        if model_name.startswith(BLOCKED_PREFIXES) or model_name in BLOCKED_MODELS:
            return False, _('"%s" is an internal or high-volume technical model and cannot be tracked.', model_name)
        model = self.env.registry.get(model_name)
        if model is None:
            return False, _('Model "%s" is not installed.', model_name)
        if model._abstract or model._transient or not model._auto:
            return False, _('"%s" is abstract, transient or a database view.', model_name)
        return True, ''

    @api.depends('model_name', 'is_tracking_enabled', 'active')
    def _compute_status(self):
        for rec in self:
            ok, _reason = self._model_check(rec.model_name)
            rec.model_available = ok
            rec.status = 'missing' if not ok else ('active' if rec.is_tracking_enabled and rec.active else 'disabled')

    @api.constrains('model_id')
    def _check_model(self):
        for rec in self:
            ok, reason = self._model_check(rec.model_name)
            if not ok:
                raise ValidationError(reason)

    @api.constrains('retention_days')
    def _check_retention(self):
        for rec in self:
            if rec.retention_days and rec.retention_days < 7:
                raise ValidationError(_('Retention override must be 0 (global) or at least 7 days.'))

    # ------------------------------------------------------------------ cache
    @api.model
    @tools.ormcache()
    def _tracking_map(self):
        """{model_name: settings dict} for every *enabled* and installed model.

        Read-only for callers.  This is the only thing the per-ORM-call hook
        consults, so an untracked model costs one dict lookup.
        """
        result = {}
        for cfg in self.sudo().search([('is_tracking_enabled', '=', True)]):
            name = cfg.model_name
            if not self._model_check(name)[0]:
                continue
            fields_cfg = {
                fc.field_name: {
                    'tracked': fc.is_tracked, 'meaningful': fc.is_meaningful,
                    'weight': fc.weight or 1.0, 'mask': fc.mask_value,
                    'category': fc.category or '',
                }
                for fc in cfg.field_config_ids if fc.active and fc.field_name
            }
            result[name] = {
                'config_id': cfg.id, 'create': cfg.track_create, 'update': cfg.track_update,
                'delete': cfg.track_delete, 'read': cfg.track_read,
                'view_time': cfg.track_view_time, 'field_changes': cfg.track_field_changes,
                'all_fields': cfg.track_all_fields, 'x2many': cfg.track_x2many,
                'weight': cfg.weight or 1.0, 'retention_days': cfg.retention_days,
                'fields': fields_cfg, 'label': cfg.model_label or name,
            }
        return result

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if vals.get('is_tracking_enabled', True):
                vals.setdefault('observed_since', now)
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        now = fields.Datetime.now()
        watched = ('is_tracking_enabled', 'track_update', 'track_field_changes', 'active')
        flips = {}
        if any(k in vals for k in watched):
            for rec in self:
                was = rec.active and rec.is_tracking_enabled and rec.track_update and rec.track_field_changes
                flips[rec.id] = was
        result = super().write(vals)
        for rec in self:
            if rec.id not in flips:
                continue
            now_on = rec.active and rec.is_tracking_enabled and rec.track_update and rec.track_field_changes
            if now_on and not flips[rec.id]:
                rec.sudo().with_context(adoption_internal=True).observed_since = now
            elif flips[rec.id] and not now_on:
                rec.sudo().with_context(adoption_internal=True).last_disabled_at = now
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result

    # ------------------------------------------------------------------ seeding
    @api.model
    def _seed_defaults(self):
        """Idempotent: add the recommended models/fields that are *installed*.
        Existing configuration is never overwritten."""
        created = []
        IrModel = self.env['ir.model'].sudo()
        for model_name, weight, read_views, field_specs in DEFAULT_MODELS:
            if not self._model_check(model_name)[0]:
                continue
            ir_model = IrModel.search([('model', '=', model_name)], limit=1)
            if not ir_model:
                continue
            cfg = self.sudo().with_context(active_test=False).search([('model_id', '=', ir_model.id)], limit=1)
            if not cfg:
                cfg = self.sudo().create({
                    'model_id': ir_model.id, 'weight': weight,
                    'track_read': read_views, 'track_view_time': read_views,
                })
                created.append(model_name)
            existing = set(cfg.field_config_ids.mapped('field_name'))
            model_fields = self.env[model_name]._fields
            for fname, fweight, category in field_specs:
                field = model_fields.get(fname)
                if fname in existing or field is None or not (field.store or field.inherited):
                    continue
                ir_field = self.env['ir.model.fields'].sudo().search(
                    [('model_id', '=', ir_model.id), ('name', '=', fname)], limit=1)
                if ir_field:
                    self.env['adoption.field.config'].sudo().create({
                        'tracking_config_id': cfg.id, 'field_id': ir_field.id,
                        'is_meaningful': True, 'weight': fweight, 'category': category,
                    })
        self.env.registry.clear_cache()
        return created

    def action_seed_defaults(self):
        created = self._seed_defaults()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _('Recommended models'), 'type': 'success', 'sticky': False,
                'message': _('Added: %s', ', '.join(created)) if created else _('Nothing to add — all installed defaults are already configured.'),
            },
        }
