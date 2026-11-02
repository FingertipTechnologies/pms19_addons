from odoo import api, fields, models

from odoo.addons.ft_project_stage_dates.models.project_project import (
    PL_ACTUAL_DATE_FIELDS,
)
from odoo.addons.project_date_extension.models.project_date_extension_request import (
    STAGE_PLANNED_DATE_FIELD,
)

from .ft_project_stage_line import REBUILD_CONTEXT_KEY


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ft_stage_line_ids = fields.One2many(
        'ft.project.stage.line', 'project_id', string='Stage Report Lines',
        readonly=True)
    ft_stage_line_count = fields.Integer(
        compute='_compute_ft_stage_line_count', string='Stage Report Lines Count')
    # Sum of the Delay Days of the project's APPROVED Date Extension
    # Requests. Each request carries only the gap it asked for on the stage
    # it targeted (the later dates it shifts are not separate requests), so
    # the plain sum never counts a day twice: DISC +3 then DEV +5 is 8.
    pl_total_extension_days = fields.Integer(
        string='Total Extension Days',
        compute='_compute_pl_total_extension_days', store=True,
        help="Sum of the Delay Days of the approved Date Extension Requests "
             "of this project (a preponement counts 0). Equal to the sum of "
             "the Extension Days of its stage report lines.")

    @api.depends('ft_stage_line_ids')
    def _compute_ft_stage_line_count(self):
        for project in self:
            project.ft_stage_line_count = len(project.ft_stage_line_ids)

    @api.depends('date_extension_request_ids.state',
                 'date_extension_request_ids.delay_days')
    def _compute_pl_total_extension_days(self):
        for project in self:
            requests = project.sudo().date_extension_request_ids
            project.pl_total_extension_days = sum(
                requests.filtered(lambda r: r.state == 'approved')
                .mapped('delay_days'))

    # ------------------------------------------------------------------
    # Report rebuild triggers
    # ------------------------------------------------------------------
    @api.model
    def _ft_stage_report_trigger_fields(self):
        """Fields whose write changes a stage line: the stage, the type, the
        actual entry dates and the planned reach-by dates. The latter come
        from STAGE_PLANNED_DATE_FIELD itself, so date_start (KICKOFF),
        support_start_date (SUPPORT) and the core ``date`` (CLOSED) are in
        without being named here."""
        names = {'stage_id', 'ft_project_type'}
        names.update(PL_ACTUAL_DATE_FIELDS.values())
        names.update(STAGE_PLANNED_DATE_FIELD.values())
        return {name for name in names if name in self._fields}

    def _ft_stage_report_rebuild(self):
        """Rebuild the stage lines of these projects (non-Implementation
        projects in the set lose theirs). Sudo; never recursive."""
        if not self:
            return
        self.env['ft.project.stage.line'].with_context(
            **{REBUILD_CONTEXT_KEY: True})._rebuild_for_projects(self)

    @api.model_create_multi
    def create(self, vals_list):
        projects = super().create(vals_list)
        if not self.env.context.get(REBUILD_CONTEXT_KEY):
            projects.filtered(
                lambda p: p.ft_project_type == 'implementation'
            )._ft_stage_report_rebuild()
        return projects

    def write(self, vals):
        res = super().write(vals)
        if (self.env.context.get(REBUILD_CONTEXT_KEY)
                or not (self._ft_stage_report_trigger_fields() & set(vals))):
            return res
        # A type change must reach the rebuild even for the project that is
        # no longer Implementation: that is how its lines are removed.
        if 'ft_project_type' in vals:
            targets = self
        else:
            targets = self.filtered(
                lambda p: p.ft_project_type == 'implementation')
        targets._ft_stage_report_rebuild()
        return res

    # ------------------------------------------------------------------
    # Smart button
    # ------------------------------------------------------------------
    def action_view_stage_report(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ft_project_stage_report.action_ft_project_stage_report_days')
        action.update({
            'domain': [('project_id', '=', self.id)],
            'context': {
                'pivot_measures': ['days_worked', 'overdue_days', 'extension_days'],
                'pivot_row_groupby': ['stage_id'],
                'pivot_column_groupby': [],
                'graph_measure': 'days_worked',
                'graph_groupbys': ['stage_id'],
            },
            'display_name': '%s - %s' % (self.display_name, action['name']),
        })
        return action
