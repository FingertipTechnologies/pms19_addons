from odoo import models, fields

class ProjectMilestoneStage(models.Model):
    _name = 'project.milestone.stage'
    _description = 'Project Milestone Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True)
    sequence = fields.Integer(string='Sequence', default=1)
    fold = fields.Boolean(string='Folded in Kanban', default=False)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)