from odoo import fields, models


class HelpdeskTicketType(models.Model):
    _name = 'ft.helpdesk.ticket.type'
    _description = 'Helpdesk Ticket Type'
    _order = 'sequence, name'

    name = fields.Char(string='Type Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description', translate=True)
    icon = fields.Char(
        string='Icon Class', default='fa-ticket',
        help='FontAwesome icon class for portal display.',
    )
    portal_visible = fields.Boolean(string='Visible on Portal', default=True)
    fieldset_id = fields.Many2one(
        'ft.helpdesk.fieldset', string='Dynamic Fieldset',
        help='Additional dynamic fields shown when this type is selected.',
    )
    default_team_id = fields.Many2one(
        'ft.helpdesk.team', string='Default Team',
        help='Auto-assign this team when ticket of this type is created.',
    )
    color = fields.Integer(string='Color Index')
