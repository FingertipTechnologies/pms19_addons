from odoo import api, models

from .ft_project_stage_line import REBUILD_CONTEXT_KEY

# Request fields whose change alters the Extension Days of a stage line
# (and project.project.pl_total_extension_days): the state, the project,
# the stage / date targeted and everything delay_days is computed from.
REPORT_FIELDS = frozenset((
    'state', 'project_id', 'stage_to_extend_id', 'date_to_extend_id',
    'requested_date', 'current_date', 'extension_days', 'delay_days',
))


class ProjectDateExtensionRequest(models.Model):
    _inherit = 'project.date.extension.request'

    def _ft_approved_projects(self):
        return self.filtered(lambda r: r.state == 'approved').project_id

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        if not self.env.context.get(REBUILD_CONTEXT_KEY):
            requests._ft_approved_projects()._ft_stage_report_rebuild()
        return requests

    def write(self, vals):
        if (self.env.context.get(REBUILD_CONTEXT_KEY)
                or not (REPORT_FIELDS & set(vals))):
            return super().write(vals)
        # Projects whose approved days change: those approved BEFORE (a
        # request leaving 'approved' or moving to another project) and those
        # approved AFTER (a request becoming approved, or an approved one
        # whose days moved).
        projects = self._ft_approved_projects()
        res = super().write(vals)
        projects |= self._ft_approved_projects()
        projects._ft_stage_report_rebuild()
        return res

    def unlink(self):
        projects = self._ft_approved_projects()
        res = super().unlink()
        if not self.env.context.get(REBUILD_CONTEXT_KEY):
            projects._ft_stage_report_rebuild()
        return res
