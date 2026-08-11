from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    change_request_ids = fields.One2many(
        "project.change.request", "project_id", string="Change Requests"
    )
