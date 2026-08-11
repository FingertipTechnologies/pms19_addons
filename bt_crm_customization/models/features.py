from odoo import models, fields

class Features(models.Model):
    _name = 'cus.features'
    _description = 'Features'

    name = fields.Char(string="Name", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)