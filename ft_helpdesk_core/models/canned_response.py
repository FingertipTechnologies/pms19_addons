from odoo import fields, models


class HelpdeskCannedResponse(models.Model):
    _name = 'ft.helpdesk.canned.response'
    _description = 'Helpdesk Canned Response'
    _order = 'sequence, name'

    name = fields.Char(string='Title', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    shortcut = fields.Char(
        string='Shortcut',
        help='Type this shortcut (e.g., /greet) to quickly insert this response.',
    )
    body = fields.Html(
        string='Response Body', required=True, translate=True,
        help='Supports placeholders: {{ticket.ticket_no}}, {{ticket.customer_id.name}}, '
             '{{ticket.assigned_user_id.name}}, {{ticket.team_id.name}}',
    )
    team_ids = fields.Many2many(
        'ft.helpdesk.team', string='Available for Teams',
        help='Leave empty to make available for all teams.',
    )
    category = fields.Selection([
        ('greeting', 'Greeting'),
        ('closing', 'Closing'),
        ('info_request', 'Information Request'),
        ('troubleshooting', 'Troubleshooting'),
        ('escalation', 'Escalation'),
        ('general', 'General'),
    ], string='Category', default='general')
