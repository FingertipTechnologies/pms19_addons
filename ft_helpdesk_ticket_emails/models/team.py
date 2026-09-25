from odoo import fields, models


class HelpdeskTeam(models.Model):
    _inherit = 'ft.helpdesk.team'

    pm_user_id = fields.Many2one(
        'res.users', string='Project Manager (PM)',
        domain="[('share', '=', False)]",
        help='Project manager accountable for this team. Receives the ticket '
             'event emails when "Project Manager (PM)" is enabled in '
             'Settings > FT Helpdesk > Ticket Emails.',
    )
