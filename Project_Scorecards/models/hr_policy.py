from odoo import models, fields

class HRPolicy(models.Model):
    _name = "hr.policy"
    _description = "HR Policy"


    date = fields.Date(
        string='Date',
        default=fields.Date.context_today
    )
    version = fields.Integer(string="Version")
    policy_details = fields.Html(string="Policy Details")
    description = fields.Text(
        string="Description"
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        string="Attachments"
    )
