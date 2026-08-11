from odoo import models, fields


class ProjectProject(models.Model):
    _inherit = 'project.project'

    qa_bug_ids = fields.One2many('qa_testapp.ticket', 'project_id', string='Bugs')
    qa_test_case_ids = fields.One2many('qa_testapp.test_case', 'project_id', string='Test Cases')
    qa_test_plan_ids = fields.One2many('qa_testapp.test_plan', 'project_id', string='Test Plans')
    custom_milestone_ids = fields.One2many('project.custom.milestone', 'project_id', string='Milestones')
