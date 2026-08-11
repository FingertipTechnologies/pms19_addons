from odoo import api, fields, models


class ProjectChangeRequest(models.Model):
    _name = "project.change.request"
    _description = "Project Change Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(
        string="Request Number",
        required=True,
        copy=False,
        readonly=True,
        default="New",
        help="Auto-generated on creation.",
    )
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    # The project's Kanban stage — what the PMS shows as "Project Status"
    # (the custom project.status selection is unused). Computed with sudo and
    # stored so the Change Request list can sort/group/filter by it without
    # tripping the group restriction on project.stage_id.
    project_status_id = fields.Many2one(
        "project.project.stage",
        string="Project Status",
        compute="_compute_project_status_id",
        store=True,
        readonly=True,
        compute_sudo=True,
    )
    date = fields.Date(default=fields.Date.context_today)
    status = fields.Selection(
        [
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("implemented", "Implemented"),
        ],
        default="submitted",
        required=True,
    )
    estimated_hours = fields.Float(string="Estimated Hours")
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "change_request_line_attachment_rel",
        "change_request_id",
        "attachment_id",
        string="Attachments",
    )

    @api.depends("project_id.stage_id")
    def _compute_project_status_id(self):
        for rec in self:
            rec.project_status_id = rec.project_id.stage_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") in (False, "New"):
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("project.change.request")
                    or "New"
                )
        return super().create(vals_list)
