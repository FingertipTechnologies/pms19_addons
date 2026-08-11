from odoo import models, fields


class InheritProjectMilestone(models.Model):
    _inherit = 'project.milestone'

    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
