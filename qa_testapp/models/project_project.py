from odoo import _, api, models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qa_bug_ids = fields.One2many('qa_testapp.ticket', 'project_id', string='Bugs')
    qa_test_case_ids = fields.One2many('qa_testapp.test_case', 'project_id', string='Test Cases')
    qa_test_plan_ids = fields.One2many('qa_testapp.test_plan', 'project_id', string='Test Plans')
    custom_milestone_ids = fields.One2many('project.custom.milestone', 'project_id', string='Milestones')

    # Customer-portal support tickets raised against this project. Surfaced in
    # the PMS project form (Tickets tab + stat button) so the PM works them
    # from PMS instead of having to open the Helpdesk app.
    helpdesk_ticket_ids = fields.One2many(
        'ft.helpdesk.ticket', 'project_id', string='Tickets',
    )
    open_helpdesk_ticket_count = fields.Integer(
        string='Open Tickets', compute='_compute_open_helpdesk_ticket_count',
    )

    # Inverse of res.users.qa_bug_project_ids. Exists so the bug-only record
    # rule on project.project can be a plain domain leaf: reading the m2m from
    # the user side inside a project.project rule would re-enter
    # ir.rule._compute_domain('project.project', 'read') and recurse forever.
    qa_bug_only_user_ids = fields.Many2many(
        'res.users',
        'qa_bug_only_user_project_rel', 'project_id', 'user_id',
        string='Bug-Only Testers',
        help="Bug-only external testers allowed to see this project's bugs.",
    )

    @api.depends('helpdesk_ticket_ids.state')
    def _compute_open_helpdesk_ticket_count(self):
        counts = {}
        if self.ids:
            # sudo: a plain project user has no access to tickets, and a bare
            # count must never turn a project form into an AccessError. The
            # Tickets tab and stat button are group-restricted in the view.
            groups = self.env['ft.helpdesk.ticket'].sudo()._read_group(
                [('project_id', 'in', self.ids),
                 ('state', 'not in', ('closed', 'cancelled'))],
                groupby=['project_id'],
                aggregates=['__count'],
            )
            counts = {project.id: count for project, count in groups}
        for project in self:
            project.open_helpdesk_ticket_count = counts.get(project.id, 0)

    def action_view_helpdesk_tickets(self):
        """Stat-button action: the project's support tickets, open ones first."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tickets'),
            'res_model': 'ft.helpdesk.ticket',
            'view_mode': 'list,kanban,form',
            'domain': [('project_id', '=', self.id)],
            'context': {
                'default_project_id': self.id,
                'search_default_active_tickets': 1,
            },
        }
