# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class ProjectTask(models.Model):
    """Point 6: tie a task (and therefore its timesheets) to the custom
    milestone/stage whose date is controlled by the extension workflow.

    The custom milestone (project.custom.milestone) is otherwise only
    linked to a project, so there is no way to know which stage a given
    task/timesheet belongs to. This optional link provides it: tasks that
    carry a milestone are governed by that milestone's (possibly extended)
    Due Date; tasks left blank are unaffected, so the feature is
    non-breaking for existing data.
    """

    _inherit = "project.task"

    custom_milestone_id = fields.Many2one(
        "project.custom.milestone",
        string="Stage / Milestone",
        index=True,
        domain="[('project_id', '=', project_id)]",
        help="Custom milestone (stage) that governs this task's date "
        "rules. Timesheet entries on this task are blocked after the "
        "milestone's approved Due Date; extend the date through a Date "
        "Extension Request to allow later entries.",
    )
