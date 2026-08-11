from odoo import models, fields

class QATestPlan(models.Model):
    _name = 'qa_testapp.test_plan'
    _description = 'QA Test Plan'
    _order = 'id desc'

    name = fields.Char(string='Test Plan Name', required=True)
    url_ids = fields.One2many(
        'qa_testapp.resource_url', 'test_plan_id', string='URLs')
    project_id = fields.Many2one('project.project', string='Project', required=True)
    project_org_id = fields.Many2one('res.partner', string='Project ORG ID', required=True)
    introduction = fields.Html(string='Introduction (Purpose)')
    test_objectives = fields.Html(string='Test Objectives (Quality Goals)')
    scope_in = fields.Html(string='Scope - In Scope')
    scope_out = fields.Html(string='Scope - Out of Scope')
    test_approach = fields.Html(string='Test Approach')
    test_environment = fields.Html(string='Test Environment')
    activity_start_date = fields.Date(string='Activity Start Date')
    activity_end_date = fields.Date(string='Activity End Date')
    entry_criteria = fields.Html(string='Entry Criteria')
    exit_criteria = fields.Html(string='Exit Criteria')
    test_manager = fields.Char(string='Test Manager')
    test_engineer = fields.Char(string='Test Engineer')
    developer = fields.Char(string='Developer')
    defect_management = fields.Html(string='Defect Management')
    assumptions = fields.Html(string='Assumptions')
    constraints = fields.Html(string='Constraints')
    approval_authority = fields.Char(string='Approval Authority')
    sign_off_details = fields.Html(string='Sign off Details')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ], string='Status', default='draft')