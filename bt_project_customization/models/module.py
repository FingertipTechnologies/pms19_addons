from odoo import api, fields, models


class ModuleModule(models.Model):
    _name = 'cus.module'

    name = fields.Char(string="Status Name", required=True)
    description = fields.Text(string="Description")
    task_ids = fields.One2many('project.task', 'module_id', string='Tasks')
    project_ids = fields.Many2many(
        'project.project',
        string='Projects',
        compute='_compute_project_ids',
        store=True,
        help='Projects in which this module is used (via tasks).',
    )

    @api.depends('task_ids.project_id')
    def _compute_project_ids(self):
        for module in self:
            module.project_ids = module.task_ids.mapped('project_id')
