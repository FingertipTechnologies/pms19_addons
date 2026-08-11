from datetime import timedelta

from odoo import models, fields, api


class QASprint(models.Model):
    _name = 'qa_testapp.sprint'
    _description = 'QA Sprint'
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Sprint Name', required=True)
    project_id = fields.Many2one('project.project', string='Project', required=True)
    start_date = fields.Date(string='Start Date', default=fields.Date.context_today)
    end_date = fields.Date(
        string='End Date',
        compute='_compute_end_date', store=True, readonly=False,
        help='Defaults to Start Date + 7 days. Editable.',
    )
    state = fields.Selection([
        ('planned', 'Planned'),
        ('working', 'Working'),
        ('testing', 'Testing'),
        ('completed', 'Completed'),
    ], string='Status', default='planned', required=True)
    task_ids = fields.One2many('project.task', 'sprint_id', string='Tasks')
    task_count = fields.Integer(string='Task Count', compute='_compute_task_count')

    @api.depends('start_date')
    def _compute_end_date(self):
        for sprint in self:
            if sprint.start_date:
                sprint.end_date = sprint.start_date + timedelta(days=7)
            else:
                sprint.end_date = False

    @api.depends('task_ids')
    def _compute_task_count(self):
        for sprint in self:
            sprint.task_count = len(sprint.task_ids)

    def action_view_tasks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sprint Tasks',
            'res_model': 'project.task',
            'view_mode': 'kanban,list,form',
            'domain': [('sprint_id', '=', self.id)],
            'context': {
                'default_sprint_id': self.id,
                'default_project_id': self.project_id.id,
                'group_by': 'stage_id',
            },
        }
