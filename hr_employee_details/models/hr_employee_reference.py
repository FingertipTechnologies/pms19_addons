from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import validators as v


class HrEmployeeReference(models.Model):
    _name = 'hr.employee.reference'
    _inherit = ['hr.employee.detail.line.mixin']
    _description = 'Employee Reference'

    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='cascade')
    name = fields.Char(string='Name', required=True)
    address = fields.Text(string='Address')
    mobile = fields.Char(string='Mobile No')
    email = fields.Char(string='Email Id')

    @api.constrains('name')
    def _check_name(self):
        for rec in self:
            if not v.is_alpha_name(rec.name):
                raise ValidationError(_(
                    "References - Name '%s' must contain letters only "
                    "(no numbers or special characters).", rec.name))

    @api.constrains('address')
    def _check_address(self):
        for rec in self:
            if not v.is_alpha_address(rec.address):
                raise ValidationError(_(
                    "References - Address for '%s' must not contain numbers. "
                    "Letters and , . - / ( ) # & are allowed.", rec.name))

    @api.constrains('mobile')
    def _check_mobile(self):
        for rec in self:
            if not v.is_phone(rec.mobile, 10, 13):
                raise ValidationError(_(
                    "References - Mobile No for '%s' is not valid. Use numbers only "
                    "(10 to 13 digits, an optional leading +); letters are not allowed.",
                    rec.name))

    @api.constrains('email')
    def _check_email(self):
        for rec in self:
            if not v.is_email(rec.email):
                raise ValidationError(_(
                    "References - Email Id for '%s' is not valid "
                    "(example: name@example.com).", rec.name))
