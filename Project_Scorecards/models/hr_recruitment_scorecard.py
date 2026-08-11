from odoo import models, fields, api

class HRRecruitmentScorecard(models.Model):
    _name = "hr.recruitment.scorecard"
    _description = "HR Recruitment Scorecard"
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

    positions = fields.Integer(string="Positions")
    description = fields.Text(string="Description")

    @api.depends('department_id')
    def _compute_name(self):
        for record in self:
            dept_name = record.department_id.name if record.department_id else 'No Department'
            record.name = f"HR Recruitment - {dept_name}"