# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from ..services import value_utils
from . import _compat


class AdoptionFieldConfig(models.Model):
    """Per-field policy: excluded, meaningful (counts for Process Compliance),
    weighted, or masked (change recorded, value never stored)."""
    _name = 'adoption.field.config'
    _description = 'Adoption Field Configuration'
    _order = 'model_name, category, field_name'

    tracking_config_id = fields.Many2one(
        'adoption.tracking.config', string='Tracked model', required=True,
        ondelete='cascade', index=True)
    model_id = fields.Many2one(related='tracking_config_id.model_id', store=True, index=True)
    model_name = fields.Char(related='tracking_config_id.model_name', store=True, index=True)
    field_id = fields.Many2one(
        'ir.model.fields', string='Field', required=True, ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', 'not in', ['binary', 'image', 'properties', 'properties_definition', 'serialized'])]")
    field_name = fields.Char(related='field_id.name', store=True, index=True)
    field_label = fields.Char(related='field_id.field_description', string='Label')
    field_type = fields.Selection(related='field_id.ttype', string='Type')
    is_tracked = fields.Boolean(
        default=True, string='Tracked',
        help='Untick to EXCLUDE this field from tracking.')
    is_meaningful = fields.Boolean(
        default=False, string='Meaningful',
        help='Editing this field counts towards Process Compliance (25% of the score).')
    mask_value = fields.Boolean(
        default=False, string='Mask values',
        help='Record that the field changed but store "***masked***" instead of the values.')
    weight = fields.Float(default=1.0, help='Multiplier on the points of a meaningful edit.')
    category = fields.Char()
    active = fields.Boolean(default=True)

    if _compat.HAS_CONSTRAINT:
        _field_uniq = models.Constraint('UNIQUE(tracking_config_id, field_id)', 'This field is already configured.')
    else:
        _sql_constraints = [('field_uniq', 'unique(tracking_config_id, field_id)', 'This field is already configured.')]

    @api.constrains('field_id', 'tracking_config_id')
    def _check_field(self):
        for rec in self:
            if rec.field_id.model_id != rec.tracking_config_id.model_id:
                raise ValidationError(_('Field "%(f)s" does not belong to model "%(m)s".',
                                        f=rec.field_id.name, m=rec.tracking_config_id.model_name))
            if not rec.field_id.store:
                model_field = self.env.get(rec.model_name) is not None and \
                    self.env[rec.model_name]._fields.get(rec.field_id.name)
                if not (model_field and model_field.inherited):
                    raise ValidationError(_('Field "%s" is not stored, so it cannot change independently.', rec.field_id.name))
            if value_utils.is_sensitive_name(rec.field_id.name):
                raise ValidationError(_('Field "%s" looks like a credential or secret and can never be tracked.', rec.field_id.name))
            if rec.weight < 0:
                raise ValidationError(_('Weight cannot be negative.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self.env.registry.clear_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self.env.registry.clear_cache()
        return result

    def unlink(self):
        result = super().unlink()
        self.env.registry.clear_cache()
        return result
