from odoo import models, fields, api

class HRTeamActivity(models.Model):
    _name = "hr.team.activity"
    _description = "HR Team Activity"
    _rec_name = "name"

    name = fields.Char(
        string="Activity Title",
        compute="_compute_name",
        store=True
    )
    date = fields.Date(
        string='Date',
        default=fields.Date.context_today
    )

    educational = fields.Text(string="Educational")
    fun_activity = fields.Text(string="Fun Activity")
    special_announcement = fields.Text(string="Special Announcement")
    training = fields.Text(string="Training")
    award_reward = fields.Text(string="Award / Reward")
    description = fields.Text(
        string="Description"
    )

    @api.depends('date')
    def _compute_name(self):
        for record in self:
            if record.date:
                record.name = f"HR Team Activity - {record.date}"
            else:
                record.name = "HR Team Activity"


