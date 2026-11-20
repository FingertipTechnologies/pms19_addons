# -*- coding: utf-8 -*-
from odoo import fields, models

from . import _compat


class AdoptionFieldChange(models.Model):
    """One row per field that actually changed (unchanged fields never get a row)."""
    _name = 'adoption.field.change'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Field Change'
    _order = 'change_datetime desc, id desc'

    activity_log_id = fields.Many2one('adoption.activity.log', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', string='User', index=True, ondelete='set null')
    company_id = fields.Many2one('res.company', index=True, ondelete='set null')
    model_name = fields.Char(string='Model', required=True, index=True)
    record_id = fields.Integer(string='Record ID', index=True)
    record_name = fields.Char(string='Record')
    field_name = fields.Char(string='Field', required=True, index=True)
    field_label = fields.Char()
    field_type = fields.Char()
    change_kind = fields.Selection([
        ('update', 'Update'),
        ('initial', 'Value at creation'),
        ('final', 'Value at deletion'),
    ], required=True, default='update', index=True,
        help='"Value at deletion" rows document what a deleted record contained; '
             'they never count as field edits.')
    old_value = fields.Text()
    new_value = fields.Text()
    is_masked = fields.Boolean()
    is_meaningful = fields.Boolean(index=True)
    weight = fields.Float(default=1.0)
    category = fields.Char()
    change_datetime = fields.Datetime(required=True, index=True, string='DateTime')
    activity_date = fields.Date(required=True, index=True)
    is_automated = fields.Boolean(index=True)

    if _compat.HAS_INDEX:
        _model_field_date_idx = models.Index('(model_name, field_name, activity_date)')
    else:
        def init(self):
            _compat.ensure_index(self.env.cr, 'adoption_field_change_mfd_idx', self._table,
                                 ['model_name', 'field_name', 'activity_date'])
