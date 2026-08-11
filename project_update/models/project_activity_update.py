from odoo import models, fields, api

class ProjectActivityUpdate(models.Model):
    _name = 'project.activity.update'
    _description = 'Project Activity Update'
    _order = 'update_date desc, id desc'

    name = fields.Char(string='Today Update', required=True)
    update_date = fields.Date(
        string='Date',
        default=fields.Date.context_today,
        required=True
    )
    project_id = fields.Many2one(
        'project.project',
        string='Project',
        required=True,
        ondelete='cascade',
        domain=[('stage_id.fold', '=', False)],
        context={'active_test': True}
       
    )
    project_manager_id = fields.Many2one(
        'res.users',
        string='Project Manager',
        related='project_id.user_id',
        store=True,
        readonly=True
    )
    stage_id = fields.Many2one(
        'project.project.stage',
        string='Project STATUS',
        related='project_id.stage_id',
        store=True,
        readonly=True
    )
  

    @api.depends('name', 'update_date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.update_date}"