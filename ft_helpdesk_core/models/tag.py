from odoo import fields, models


class HelpdeskTag(models.Model):
    _name = 'ft.helpdesk.tag'
    _description = 'Helpdesk Tag'
    _order = 'name'

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    active = fields.Boolean(default=True)
