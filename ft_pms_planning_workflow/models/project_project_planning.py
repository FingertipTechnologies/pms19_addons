from odoo import api, fields, models

from .planner import AVG_STATES, compute_avg_daily_effort


class ProjectProject(models.Model):
    _inherit = 'project.project'

    # Not stored: it depends on today's date, so a stored value would be stale
    # by the next morning.
    pwf_avg_daily_effort = fields.Float(
        string='Avg. Daily Effort',
        digits=(16, 2),
        compute='_compute_pwf_avg_daily_effort',
        help='Remaining estimated hours (Estimated Time - Actual Hours) divided '
             'by the working days (Mon-Fri) from today to the End Date. For an '
             'overdue project it is the whole remaining budget.',
    )
    pwf_avg_effort_state = fields.Selection(
        AVG_STATES,
        string='Avg. Effort Status',
        compute='_compute_pwf_avg_daily_effort',
    )

    def _pwf_avg_daily_effort_values(self, today=None):
        """{project_id: (value, state)} — shared with the Project Planner."""
        today = today or fields.Date.context_today(self)
        return {
            project.id: compute_avg_daily_effort(
                project.estimated, project.effective_hours, project.date, today)
            for project in self
        }

    @api.depends('estimated', 'effective_hours', 'date')
    def _compute_pwf_avg_daily_effort(self):
        values = self._pwf_avg_daily_effort_values()
        for project in self:
            value, state = values[project.id]
            project.pwf_avg_daily_effort = value
            project.pwf_avg_effort_state = state
