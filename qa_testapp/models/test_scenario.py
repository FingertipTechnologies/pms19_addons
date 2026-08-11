from odoo import models, fields, api


class QATestScenario(models.Model):
    _name = 'qa_testapp.test_scenario'
    _description = 'QA Test Scenario'
    _order = 'id desc'
    _rec_name = 'test_scenario_id'

    test_scenario_id = fields.Char(
        string='Test Scenario ID', readonly=True, copy=False, default='New',
    )
    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    project_id = fields.Many2one('project.project', string='Project', required=True)
    module_id = fields.Many2one(
        'cus.module', string='Module', required=True,
        domain="[('id', 'in', available_module_ids)]",
    )
    available_module_ids = fields.Many2many(
        'cus.module', compute='_compute_available_modules',
    )
    description = fields.Text(string='Description')
    status = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('invalid', 'Invalid')
    ], string='Status', default='pass')
    comments = fields.Text(string='Comments', help='Comments by PM')
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user)
    reviewed_by = fields.Many2one('res.users', string='Reviewed By')
    project_org_id = fields.Many2one('res.partner', string='Project ORG ID')

    @api.depends('project_id')
    def _compute_available_modules(self):
        for rec in self:
            if rec.project_id:
                tasks = self.env['project.task'].sudo().search([
                    ('project_id', '=', rec.project_id.id),
                    ('module_id', '!=', False),
                ])
                rec.available_module_ids = tasks.mapped('module_id')
            else:
                rec.available_module_ids = self.env['cus.module'].sudo().search([])

    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.module_id = False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('test_scenario_id', 'New') == 'New':
                vals['test_scenario_id'] = self.env['ir.sequence'].next_by_code(
                    'qa_testapp.test_scenario') or 'New'
        return super().create(vals_list)
