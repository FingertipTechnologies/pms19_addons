from odoo import fields, models, tools


class QABugAnalysis(models.Model):
    _name = 'qa_testapp.bug.analysis'
    _description = 'QA Bug Analysis (Project-wise)'
    _auto = False
    _rec_name = 'bug_id'
    _order = 'reported_date desc'

    # ----- Dimensions -----
    ticket_id = fields.Many2one(
        'qa_testapp.ticket', string='Bug', readonly=True,
    )
    bug_id = fields.Char(string='Bug ID', readonly=True)
    title = fields.Char(string='Title', readonly=True)
    reported_date = fields.Datetime(string='Reported On', readonly=True)
    project_id = fields.Many2one(
        'project.project', string='Project', readonly=True,
    )
    module_id = fields.Many2one(
        'cus.module', string='Module', readonly=True,
    )
    reporter_id = fields.Many2one(
        'res.users', string='Reporter', readonly=True,
    )
    assignee_id = fields.Many2one(
        'res.users', string='Assignee', readonly=True,
    )
    test_case_id = fields.Many2one(
        'qa_testapp.test_case', string='Related Test Case', readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company', readonly=True,
    )
    severity = fields.Selection([
        ('blocker', 'Blocker'),
        ('critical', 'Critical'),
        ('major', 'Major'),
        ('minor', 'Minor'),
        ('trivial', 'Trivial'),
    ], string='Severity', readonly=True)
    priority = fields.Selection([
        ('p1', 'P1 - Urgent'),
        ('p2', 'P2 - High'),
        ('p3', 'P3 - Medium'),
        ('p4', 'P4 - Low'),
        ('p5', 'P5 - Backlog'),
    ], string='Priority', readonly=True)
    status = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('fixed', 'Fixed'),
        ('closed', 'Closed'),
        ('reopened', 'Re-Opened'),
    ], string='Status', readonly=True)
    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('qa', 'QA'),
        ('production', 'Production'),
    ], string='Environment', readonly=True)
    reproducibility = fields.Selection([
        ('always', 'Always'),
        ('sometimes', 'Sometimes'),
        ('rare', 'Rare'),
        ('unable', 'Unable to Reproduce'),
    ], string='Reproducibility', readonly=True)
    is_client = fields.Boolean(string='Client Reported', readonly=True)
    is_internal = fields.Boolean(string='Internal Reported', readonly=True)

    # ----- Measures -----
    bug_count = fields.Integer(
        string='Bug Count', readonly=True,
        aggregator='sum',
    )
    fixed_count = fields.Integer(
        string='Bugs Fixed', readonly=True,
        aggregator='sum',
    )
    reopen_count = fields.Integer(
        string='Reopen Count', readonly=True,
        aggregator='sum',
    )
    is_reopened = fields.Boolean(
        string='Re-Opened', readonly=True,
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    t.id                AS id,
                    t.id                AS ticket_id,
                    t.bug_id            AS bug_id,
                    t.title             AS title,
                    t.reported_date     AS reported_date,
                    t.project_id        AS project_id,
                    t.module_id         AS module_id,
                    t.reporter_id       AS reporter_id,
                    t.assignee_id       AS assignee_id,
                    t.test_case_id      AS test_case_id,
                    p.company_id        AS company_id,
                    t.severity          AS severity,
                    t.priority          AS priority,
                    t.status            AS status,
                    t.environment       AS environment,
                    t.reproducibility   AS reproducibility,
                    t.is_client         AS is_client,
                    t.is_internal       AS is_internal,
                    1                   AS bug_count,
                    CASE
                        WHEN t.status IN ('fixed', 'closed') THEN 1
                        ELSE 0
                    END                 AS fixed_count,
                    COALESCE(t.reopen_count, 0) AS reopen_count,
                    CASE
                        WHEN t.status = 'reopened' OR COALESCE(t.reopen_count, 0) > 0
                        THEN TRUE ELSE FALSE
                    END                 AS is_reopened
                FROM qa_testapp_ticket t
                LEFT JOIN project_project p ON p.id = t.project_id
            )
        """ % self._table)
