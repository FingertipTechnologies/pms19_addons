from odoo import fields, models


class ProjectProjectStage(models.Model):
    _inherit = 'project.project.stage'

    # Which Project Types may use this stage. Drives the allowed-stage domain and
    # constraint on project.project (see project_project.py), so the Implementation
    # lifecycle stays separate from the General and AMC flows.
    pl_for_general = fields.Boolean(
        string='General',
        help="Stage available to General projects.",
    )
    pl_for_implementation = fields.Boolean(
        string='Implementation',
        help="Stage available to Implementation projects.",
    )
    pl_for_amc = fields.Boolean(
        string='AMC',
        help="Stage available to AMC projects.",
    )
