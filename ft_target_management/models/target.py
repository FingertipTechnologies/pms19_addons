from odoo import api, fields, models


class FtTarget(models.Model):
    _name = "ft.target"
    _description = "Target"
    _order = "id desc"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True)
    target_type_id = fields.Many2one("ft.target.type", string="Target Type", required=True)
    period_id = fields.Many2one("ft.target.period", string="Period", required=True)
    target_value = fields.Float(string="Target Value")
    actual_value = fields.Float(string="Actual Value")
    assigned_to = fields.Many2one("res.users", string="Assigned To")
    achievement = fields.Float(
        string="Achievement %", compute="_compute_achievement", store=True
    )
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    @api.depends("target_type_id", "assigned_to", "period_id")
    def _compute_name(self):
        for rec in self:
            parts = [rec.target_type_id.name or "Target"]
            if rec.assigned_to:
                parts.append(rec.assigned_to.name)
            if rec.period_id:
                parts.append(rec.period_id.name)
            rec.name = " - ".join(parts)

    @api.depends("target_value", "actual_value")
    def _compute_achievement(self):
        # Stored as a 0-1 fraction; the views render it with the percentage
        # widget, which multiplies by 100 for display (e.g. 0.45 -> "45%").
        for rec in self:
            rec.achievement = (
                (rec.actual_value / rec.target_value)
                if rec.target_value
                else 0.0
            )
