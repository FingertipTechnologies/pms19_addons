from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    helpdesk_team_id = fields.Many2one(
        'ft.helpdesk.team',
        string='Support Team',
        help="Tickets raised by this customer are auto-assigned to this team.",
    )
