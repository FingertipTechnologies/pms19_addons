from odoo import api, fields, models
from odoo.exceptions import ValidationError


class FtTargetPeriod(models.Model):
    _name = "ft.target.period"
    _description = "Target Period"
    _order = "start_date desc"

    name = fields.Char(required=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)
    active = fields.Boolean(default=True)

    @api.constrains("start_date", "end_date")
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError("End Date cannot be before Start Date.")
