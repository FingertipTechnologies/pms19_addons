from odoo import api, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    pwf_next_stage_id = fields.Many2one(
        'project.project.stage',
        string='Next Stage',
        compute='_compute_pwf_stage_panel',
    )
    pwf_next_stage_key = fields.Char(
        string='Next Stage Key',
        compute='_compute_pwf_stage_panel',
    )
    pwf_show_stage_panel = fields.Boolean(
        string='Show Stage Panel',
        compute='_compute_pwf_stage_panel',
    )

    @api.depends('stage_id', 'ft_project_type', 'pl_allowed_stage_ids')
    def _compute_pwf_stage_panel(self):
        Stage = self.env['project.project.stage']
        sort_key = Stage._ft_stage_sort_key
        for project in self:
            stages = project.pl_allowed_stage_ids.filtered(
                lambda s: s._ft_stage_key() != 'hold'
            ).sorted(key=sort_key)
            current = project.stage_id
            if current:
                here = sort_key(current)
                nxt = next((s for s in stages if sort_key(s) > here), Stage)
            else:
                nxt = stages[:1]
            project.pwf_next_stage_id = nxt
            project.pwf_next_stage_key = (nxt._ft_stage_key() or False) if nxt else False
            project.pwf_show_stage_panel = bool(
                project.ft_project_type == 'implementation' and nxt
            )
