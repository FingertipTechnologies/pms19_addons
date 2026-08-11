"""Singleton configuration for the AI Sales Insights module.

Holds provider selection, model/tuning parameters and the editable master
prompt. The API key itself is *not* stored on this record — it lives in
``ir.config_parameter`` (system-only) and is proxied through a non-stored
computed field, so secrets never sit in a regular business table.
"""
from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ft_ai_sales_insights.services.ai_service import (
    provider_selection,
)

# ir.config_parameter key holding the (per-provider) secret.
API_KEY_PARAM = "ft_ai_sales_insights.api_key.%s"


class FtAiInsightsConfig(models.Model):
    _name = "ft.ai.insights.config"
    _description = "AI Sales Insights Configuration"

    name = fields.Char(default="AI Insights Settings", required=True)
    provider = fields.Selection(
        selection=lambda self: provider_selection(),
        default="openai",
        required=True,
        string="AI Provider",
    )
    model = fields.Char(
        string="AI Model",
        default="gpt-4o-mini",
        help="Model identifier as expected by the selected provider.",
    )
    api_key = fields.Char(
        string="API Key",
        compute="_compute_api_key",
        inverse="_inverse_api_key",
        help="Stored securely in system parameters, per provider.",
    )
    api_base_url = fields.Char(
        string="API Base URL",
        help="Optional override. Required for Azure OpenAI (full deployment "
        "URL) and Ollama (e.g. http://localhost:11434).",
    )
    temperature = fields.Float(default=0.4)
    max_tokens = fields.Integer(default=1500)
    request_timeout = fields.Integer(string="Request Timeout (s)", default=60)
    master_prompt = fields.Text(
        string="Sales Master Prompt",
        help="System prompt prepended to every Sales analysis. Editable — no "
        "code change needed.",
    )
    default_purpose_id = fields.Many2one(
        "ft.ai.insights.purpose",
        string="Default Sales Purpose",
        domain="[('applies_to', '=', 'sales')]",
    )
    project_master_prompt = fields.Text(
        string="Project Master Prompt",
        help="System prompt prepended to every Project analysis. Editable — no "
        "code change needed.",
    )
    default_project_purpose_id = fields.Many2one(
        "ft.ai.insights.purpose",
        string="Default Project Purpose",
        domain="[('applies_to', '=', 'project')]",
    )
    debug_mode = fields.Boolean(
        help="Store the full aggregated payload on each audit log entry and "
        "return it to the UI. Leave off in production."
    )
    log_level = fields.Selection(
        [("error", "Errors only"), ("info", "Info"), ("debug", "Debug")],
        default="info",
    )

    # ------------------------------------------------------------------
    # Secure API-key proxy
    # ------------------------------------------------------------------
    def _param_key(self):
        self.ensure_one()
        return API_KEY_PARAM % (self.provider or "openai")

    @api.depends("provider")
    def _compute_api_key(self):
        ICP = self.env["ir.config_parameter"].sudo()
        for rec in self:
            rec.api_key = ICP.get_param(rec._param_key(), default="")

    def _inverse_api_key(self):
        ICP = self.env["ir.config_parameter"].sudo()
        for rec in self:
            # A blank value keeps the previously stored key (avoids clobbering
            # the secret with the masked/empty field on an unrelated save).
            if rec.api_key:
                ICP.set_param(rec._param_key(), rec.api_key)

    def _resolve_api_key(self):
        """Effective secret used for outgoing requests.

        Prefers the per-provider key stored in ``ir.config_parameter`` (set via
        the UI). When that is blank, falls back to a matching option in the Odoo
        config file — e.g. ``OPENAI_API_KEY`` in odoo.conf becomes the lowercase
        option ``openai_api_key``. This keeps the compute/inverse field reading
        only the DB param, so a config-file secret is never shown in the form nor
        copied back into the database.
        """
        self.ensure_one()
        from odoo.tools import config

        stored = self.env["ir.config_parameter"].sudo().get_param(
            self._param_key(), default=""
        )
        if stored:
            return stored
        return config.get("%s_api_key" % (self.provider or "openai")) or ""

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------
    @api.model
    def _get_singleton(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({"name": "AI Insights Settings"})
        return rec

    @api.model
    def action_open_config(self):
        rec = self._get_singleton()
        return {
            "type": "ir.actions.act_window",
            "name": "AI Insights Settings",
            "res_model": "ft.ai.insights.config",
            "view_mode": "form",
            "res_id": rec.id,
            "target": "current",
        }

    def action_test_connection(self):
        """Fire a tiny prompt at the provider and report success/failure."""
        self.ensure_one()
        from odoo.addons.ft_ai_sales_insights.services.ai_service import AIService
        from odoo.addons.ft_ai_sales_insights.services.providers.base import (
            AIProviderError,
        )

        service = AIService(
            self.provider,
            api_key=self._resolve_api_key(),
            base_url=self.api_base_url,
            model=self.model,
            timeout=self.request_timeout,
        )
        try:
            result = service.generate(
                [
                    {"role": "system", "content": "You are a health check."},
                    {"role": "user", "content": 'Reply with the JSON object {"ok": true}.'},
                ],
                temperature=0,
                max_tokens=20,
            )
        except AIProviderError as exc:
            raise UserError(f"Connection failed:\n{exc}") from exc
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "AI connection OK",
                "message": f"Provider responded ({result.total_tokens} tokens).",
                "type": "success",
                "sticky": False,
            },
        }
