from odoo import models, fields, api


class ProjectTask(models.Model):
    _inherit = 'project.task'

    sprint_id = fields.Many2one(
        'qa_testapp.sprint', string='Sprint',
        domain="[('project_id', '=', project_id)]",
        help='Sprint this task belongs to (sprints of the same project).',
    )

    @api.onchange('sprint_id')
    def _onchange_sprint_id(self):
        # A sprint task must belong to the sprint's project so it uses the
        # project stages (Planned / Working / Testing / Completed) instead of
        # the personal stages shown for private (project-less) tasks.
        if self.sprint_id and not self.project_id:
            self.project_id = self.sprint_id.project_id

    @api.model_create_multi
    def create(self, vals_list):
        # Backfill the project from the sprint for tasks created inside a
        # sprint (e.g. the Tasks tab on the sprint form), so they never end up
        # as private tasks with personal stages.
        for vals in vals_list:
            if vals.get('sprint_id') and not vals.get('project_id'):
                sprint = self.env['qa_testapp.sprint'].browse(vals['sprint_id'])
                if sprint.project_id:
                    vals['project_id'] = sprint.project_id.id
        return super().create(vals_list)
