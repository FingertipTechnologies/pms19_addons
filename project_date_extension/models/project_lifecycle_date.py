# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, fields, models


class ProjectLifecycleDate(models.Model):
    """The ordered list of project 'stage dates' that can be extended.

    Each record maps a human label to a Date field on project.project and
    a position in the lifecycle. The Date Extension Request offers these in
    a dropdown, filtered to the current stage and everything after it, and
    the approval shifts this date and all later ones forward by the gap.
    """

    _name = "project.lifecycle.date"
    _description = "Project Lifecycle Date"
    _order = "sequence, id"

    name = fields.Char(string="Date", required=True, translate=True)
    field_name = fields.Char(
        string="Project Field",
        required=True,
        help="Technical name of the Date field on project.project.",
    )
    sequence = fields.Integer(default=10, help="Lifecycle order.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "field_name_uniq",
            "unique(field_name)",
            "Each project date field can be listed only once.",
        )
    ]

    @api.depends_context("ld_project_id")
    def _compute_display_name(self):
        """Show each date's current value (its history) in the dropdown, e.g.
        "Kick-off Date (Sep 5)". The project is passed via the field context
        (ld_project_id) so the right value is shown per project."""
        project_id = self.env.context.get("ld_project_id")
        project = (
            self.env["project.project"].browse(project_id)
            if project_id
            else None
        )
        for rec in self:
            label = rec.name or ""
            if project and rec.field_name in project._fields:
                value = project[rec.field_name]
                if value:
                    label = "%s (%s %d)" % (
                        rec.name,
                        value.strftime("%b"),
                        value.day,
                    )
            rec.display_name = label
