from odoo import models, fields

class Technology(models.Model):
    _name = 'cus.technology'
    _description = 'Technology'

    name = fields.Char(string="Name", required=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(string="Active", default=True)