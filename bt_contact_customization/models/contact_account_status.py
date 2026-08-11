from odoo import models, fields

class ResPartnerAccountStatus(models.Model):
    _name = 'res.partner.account.status'
    _description = 'Account Status'

    name = fields.Char(string="Status Name", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)