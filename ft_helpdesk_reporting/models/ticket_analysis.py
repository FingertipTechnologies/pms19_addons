from odoo import fields, models, tools


class HelpdeskTicketAnalysis(models.Model):
    _name = 'ft.helpdesk.ticket.analysis'
    _description = 'Helpdesk Ticket Analysis'
    _auto = False
    _rec_name = 'ticket_id'
    _order = 'create_date desc'

    # ----- Dimensions -----
    ticket_id = fields.Many2one(
        'ft.helpdesk.ticket', string='Ticket', readonly=True,
    )
    name = fields.Char(string='Subject', readonly=True)
    ticket_no = fields.Char(string='Ticket Number', readonly=True)
    create_date = fields.Datetime(string='Created On', readonly=True)
    close_date = fields.Datetime(string='Closed On', readonly=True)
    team_id = fields.Many2one(
        'ft.helpdesk.team', string='Team', readonly=True,
    )
    assigned_user_id = fields.Many2one(
        'res.users', string='Assignee', readonly=True,
    )
    project_id = fields.Many2one(
        'project.project', string='Project', readonly=True,
    )
    category_id = fields.Many2one(
        'ft.helpdesk.category', string='Category', readonly=True,
    )
    type_id = fields.Many2one(
        'ft.helpdesk.ticket.type', string='Type', readonly=True,
    )
    priority = fields.Selection([
        ('0', 'P4 – Low'),
        ('1', 'P3 – Medium'),
        ('2', 'P2 – High'),
        ('3', 'P1 – Critical'),
    ], string='Priority', readonly=True)
    state = fields.Selection([
        ('new', 'New'),
        ('open', 'In Progress'),
        ('pending_customer', 'Pending Customer'),
        ('pending_internal', 'Pending Internal'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', readonly=True)
    channel = fields.Selection([
        ('portal', 'Portal'),
        ('email', 'Email'),
        ('internal', 'Internal'),
        ('api', 'API'),
    ], string='Channel', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer', readonly=True,
    )

    # ----- Measures -----
    first_response_hours = fields.Float(
        string='First Response Time (Hours)', readonly=True,
        group_operator='avg',
    )
    resolution_hours = fields.Float(
        string='Resolution Time (Hours)', readonly=True,
        group_operator='avg',
    )
    fixed_count = fields.Integer(
        string='Issues Fixed', readonly=True,
        group_operator='sum',
    )

    # ----- SLA / Escalation flags -----
    is_sla_breached = fields.Boolean(
        string='SLA Breached', readonly=True,
    )
    is_escalated = fields.Boolean(
        string='Escalated', readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    t.id                        AS id,
                    t.id                        AS ticket_id,
                    t.name                      AS name,
                    t.ticket_no                 AS ticket_no,
                    t.create_date               AS create_date,
                    t.closed_at                 AS close_date,
                    t.team_id                   AS team_id,
                    t.project_id                AS project_id,
                    t.assigned_user_id          AS assigned_user_id,
                    t.category_id               AS category_id,
                    t.type_id                   AS type_id,
                    t.priority                  AS priority,
                    t.state                     AS state,
                    t.channel                   AS channel,
                    t.company_id                AS company_id,
                    t.customer_id               AS customer_id,
                    t.is_escalated              AS is_escalated,
                    -- First response time in hours
                    CASE
                        WHEN t.first_response_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (t.first_response_at - t.create_date)) / 3600.0
                        ELSE NULL
                    END                         AS first_response_hours,
                    -- Resolution time in hours
                    CASE
                        WHEN t.resolved_at IS NOT NULL
                        THEN EXTRACT(EPOCH FROM (t.resolved_at - t.create_date)) / 3600.0
                        ELSE NULL
                    END                         AS resolution_hours,
                    -- SLA breach: true if any linked SLA status is breached
                    CASE
                        WHEN sla.id IS NOT NULL
                             AND (sla.first_response_breached OR sla.resolution_breached)
                        THEN TRUE
                        ELSE FALSE
                    END                         AS is_sla_breached,
                    -- Issues fixed: resolved or closed tickets count as 1
                    CASE
                        WHEN t.state IN ('resolved', 'closed')
                        THEN 1
                        ELSE 0
                    END                         AS fixed_count
                FROM ft_helpdesk_ticket t
                LEFT JOIN ft_helpdesk_sla_status sla
                    ON sla.id = (
                        SELECT s.id
                        FROM ft_helpdesk_sla_status s
                        WHERE s.ticket_id = t.id
                        ORDER BY s.create_date DESC
                        LIMIT 1
                    )
            )
        """ % self._table)
