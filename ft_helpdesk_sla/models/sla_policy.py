from odoo import api, fields, models


class SLAPolicy(models.Model):
    _name = 'ft.helpdesk.sla.policy'
    _description = 'Helpdesk SLA Policy'
    _order = 'sequence, name'

    name = fields.Char(string='Policy Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    # Matching criteria
    team_id = fields.Many2one(
        'ft.helpdesk.team', string='Team',
        help='Apply this SLA to tickets of this team. Leave empty for all teams.',
    )
    priority = fields.Selection([
        ('0', 'P4 – Low'),
        ('1', 'P3 – Medium'),
        ('2', 'P2 – High'),
        ('3', 'P1 – Critical'),
    ], string='Minimum Priority',
        help='Apply to tickets with this priority or higher.',
    )
    category_id = fields.Many2one(
        'ft.helpdesk.category', string='Category',
        help='Apply to tickets of this category. Leave empty for all categories.',
    )
    type_id = fields.Many2one(
        'ft.helpdesk.ticket.type', string='Ticket Type',
        help='Apply to tickets of this type. Leave empty for all types.',
    )

    # SLA targets (in hours)
    first_response_hours = fields.Float(
        string='First Response Time (hours)', required=True, default=4.0,
        help='Target time for first agent response.',
    )
    resolution_hours = fields.Float(
        string='Resolution Time (hours)', required=True, default=24.0,
        help='Target time for ticket resolution.',
    )

    # Business hours
    business_hours_id = fields.Many2one(
        'ft.helpdesk.business.hours', string='Business Hours',
        help='Use business hours for SLA computation. Leave empty for 24/7.',
    )

    # Escalation
    escalate_on_breach = fields.Boolean(
        string='Escalate on Breach', default=True,
        help='Automatically escalate ticket when SLA is breached.',
    )
    notify_user_ids = fields.Many2many(
        'res.users', 'ft_sla_policy_notify_user_rel',
        'policy_id', 'user_id',
        string='Notify on Breach',
        help='Users to notify when SLA is breached.',
    )

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
    )

    def _match_ticket(self, ticket):
        """Check if this SLA policy matches a ticket."""
        self.ensure_one()
        if self.team_id and self.team_id != ticket.team_id:
            return False
        if self.priority and ticket.priority < self.priority:
            return False
        if self.category_id and self.category_id != ticket.category_id:
            return False
        if self.type_id and self.type_id != ticket.type_id:
            return False
        return True
