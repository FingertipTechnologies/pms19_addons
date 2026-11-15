from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    technical_lead_id = fields.Many2one(
        'res.users', string='Technical Lead', index=True, tracking=True,
        domain="[('share', '=', False)]",
        help="Receives the daily Implementation / AMC status e-mail of this "
             "project together with the Project Manager.")
