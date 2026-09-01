from odoo import models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qa_bug_ids = fields.One2many('qa_testapp.ticket', 'project_id', string='Bugs')
    qa_test_case_ids = fields.One2many('qa_testapp.test_case', 'project_id', string='Test Cases')
    qa_test_plan_ids = fields.One2many('qa_testapp.test_plan', 'project_id', string='Test Plans')
    custom_milestone_ids = fields.One2many('project.custom.milestone', 'project_id', string='Milestones')

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
