"""Audit log for every AI analysis request.

By default only non-sensitive metadata is stored (who, when, purpose, filters,
token usage, status). The aggregated payload and full response are stored only
when Debug Mode is enabled. Inherits ``mail.thread`` so an insight can be
"saved to chatter" (posted as a message on its own log record).
"""
from odoo import api, fields, models


class FtAiInsightsLog(models.Model):
    _name = "ft.ai.insights.log"
    _description = "AI Sales Insights Request Log"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(default="AI Insight", tracking=True)
    user_id = fields.Many2one(
        "res.users", string="Requested by", default=lambda s: s.env.user, index=True
    )
    purpose_id = fields.Many2one("ft.ai.insights.purpose", string="Purpose")
    provider = fields.Char()
    model = fields.Char()
    filters_json = fields.Text(string="Filters")
    payload_json = fields.Text(
        string="Payload (debug)", help="Only stored when Debug Mode is on."
    )
    response = fields.Text()
    prompt_tokens = fields.Integer()
    completion_tokens = fields.Integer()
    total_tokens = fields.Integer(compute="_compute_total", store=True)
    duration_ms = fields.Integer(string="Duration (ms)")
    status = fields.Selection(
        [("success", "Success"), ("error", "Error")], default="success", index=True
    )
    error_message = fields.Text()

    @api.depends("prompt_tokens", "completion_tokens")
    def _compute_total(self):
        for rec in self:
            rec.total_tokens = (rec.prompt_tokens or 0) + (rec.completion_tokens or 0)

    def action_post_to_chatter(self):
        """Post the stored response into this record's chatter."""
        for rec in self.filtered("response"):
            rec.message_post(body=rec.response, subject=rec.name)
        return True
