from odoo import models, fields, api

class ProjectScorecard(models.Model):
    _name = "project.scorecard"
    _description = "Project Scorecard"
    _rec_name = "name"

    name = fields.Char(
        string="Scorecard Name",
        compute="_compute_name",
        store=True
    )

    date = fields.Date(
        string="Date",
        default=fields.Date.context_today
    )

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        ondelete="cascade"
    )

    meetings = fields.Integer(string="Meetings")

    time_spent = fields.Float(
        string="Time",
        help="Time in hours"
    )

    stage_id = fields.Many2one(
        "project.project.stage",
        string="Status",
        related="project_id.stage_id",
        store=True,
        readonly=True
    )
    
    start_date = fields.Date(
        string="Start Date",
        related="project_id.date_start",
        store=True,
        readonly=True
    )
    
    end_date = fields.Date(
        string="End Date",
        related="project_id.date",
        store=True,
        readonly=True
    )
    

    uat_date = fields.Date(
        string="UAT Date",
        related="project_id.uat_start_date",
        store=True,
        readonly=True
    )
    
    go_live_date = fields.Date(
        string="Go Live Date",
        related="project_id.go_live_date",
        store=True,
        readonly=True
    )

    description = fields.Text(
        string="Description"
    )

    @api.depends("project_id")
    def _compute_name(self):
        for record in self:
            record.name = (
                f"{record.project_id.name} - Project Scorecard"
                if record.project_id else
                "Project Scorecard"
            )
