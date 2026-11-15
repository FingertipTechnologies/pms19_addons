from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    ft_weekly_review_ids = fields.One2many(
        "ft.project.weekly.review",
        "project_id",
        string="Weekly Reviews",
    )
