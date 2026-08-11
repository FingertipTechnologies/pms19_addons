from odoo import models, fields, api

class HRTrainingScorecard(models.Model):
    _name = "hr.training.scorecard"
    _description = "HR Training Scorecard"
    _rec_name = "name"

    name = fields.Char(
        string="Scorecard Name",
        compute="_compute_name",
        store=True
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today
    )

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        required=False,
        ondelete='restrict', 
        index=True,
        tracking=True, 
    )
    subject = fields.Char(string="Subject")
    description = fields.Text(string="Description")

    @api.depends('department_id', 'subject')
    def _compute_name(self):
        for record in self:
            dept = record.department_id.name if record.department_id else 'No Department'
            subject = record.subject or 'No Subject'
            record.name = f"HR Training - {dept} - {subject}"