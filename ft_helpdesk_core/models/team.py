from odoo import api, fields, models


class HelpdeskTeam(models.Model):
    _name = 'ft.helpdesk.team'
    _description = 'Helpdesk Team'
    _order = 'sequence, name'

    name = fields.Char(string='Team Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, required=True,
    )
    leader_user_id = fields.Many2one(
        'res.users', string='Team Leader',
        domain="[('share', '=', False)]",
        required=True,
    )
    member_user_ids = fields.Many2many(
        'res.users', 'ft_helpdesk_team_member_rel',
        'team_id', 'user_id', string='Members',
        domain="[('share', '=', False)]",
    )
    default_assignee_id = fields.Many2one(
        'res.users', string='Default Assignee',
        domain="[('share', '=', False)]",
        help='Auto-assign new tickets to this user when no other rule applies.',
    )
    default_type_id = fields.Many2one(
        'ft.helpdesk.ticket.type', string='Default Ticket Type',
    )
    portal_enabled = fields.Boolean(
        string='Visible on Portal', default=True,
        help='Allow portal users to submit tickets to this team.',
    )
    auto_assign_mode = fields.Selection([
        ('manual', 'Manual'),
        ('round_robin', 'Round Robin'),
    ], string='Auto-Assign Mode', default='manual')
    color = fields.Integer(string='Color Index')
    description = fields.Text(string='Description', translate=True)

    # Counters
    ticket_count = fields.Integer(
        string='Ticket Count', compute='_compute_ticket_count',
    )
    open_ticket_count = fields.Integer(
        string='Open Tickets', compute='_compute_ticket_count',
    )

    # Round-robin tracking
    last_assigned_index = fields.Integer(
        string='Last Assigned Index', default=0,
    )

    def _compute_ticket_count(self):
        ticket_data = self.env['ft.helpdesk.ticket'].read_group(
            [('team_id', 'in', self.ids)],
            ['team_id', 'state'],
            ['team_id', 'state'],
            lazy=False,
        )
        total_map = {}
        open_map = {}
        for data in ticket_data:
            team_id = data['team_id'][0]
            count = data['__count']
            total_map[team_id] = total_map.get(team_id, 0) + count
            if data['state'] in ('new', 'open', 'pending_customer', 'pending_internal'):
                open_map[team_id] = open_map.get(team_id, 0) + count
        for team in self:
            team.ticket_count = total_map.get(team.id, 0)
            team.open_ticket_count = open_map.get(team.id, 0)

    def _get_next_assignee(self):
        """Round-robin assignment logic."""
        self.ensure_one()
        members = self.member_user_ids
        if not members:
            return self.default_assignee_id or self.leader_user_id
        idx = (self.last_assigned_index or 0) % len(members)
        assignee = members[idx]
        self.last_assigned_index = idx + 1
        return assignee
