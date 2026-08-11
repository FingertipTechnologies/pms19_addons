"""AI analyses for the Project Dashboard — lives entirely in this module.

Extends ``ft.project.dashboard`` (from ft_project_dashboard) with the AI RPCs
used by the "AI Summary" panel that this module injects into that dashboard's
UI. Keeping it here means all AI code stays inside ft_ai_sales_insights;
ft_project_dashboard carries no AI logic.

Structurally this mirrors the Sales side: the analysis to run is an editable
``ft.ai.insights.purpose`` record (``applies_to='project'``), the payload comes
from ``ProjectDataCollector``, and the prompt is composed by ``PromptBuilder``
from the admin-editable project master prompt. Adding a new project analysis is
therefore a data change, not a code change.
"""
import json
import logging
import time
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ft_ai_sales_insights.models.project_insights import (
    DEFAULT_PROJECT_MASTER_PROMPT,
)
from odoo.addons.ft_ai_sales_insights.services.ai_service import AIService
from odoo.addons.ft_ai_sales_insights.services.project_data_collector import (
    ProjectDataCollector,
)
from odoo.addons.ft_ai_sales_insights.services.prompt_builder import PromptBuilder
from odoo.addons.ft_ai_sales_insights.services.providers.base import AIProviderError

_logger = logging.getLogger(__name__)

AI_PERIODS = [
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("last_2_weeks", "Last 2 Weeks"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("last_2_months", "Last 2 Months"),
    ("last_3_months", "Last 3 Months"),
]

# This embedded panel renders a simpler shape than the full Project Insights
# dashboard (no score gauge / KPI tiles), so it keeps its own contract.
PROJECT_RESPONSE_CONTRACT = """
Return a SINGLE valid JSON object (no markdown fences) with this shape:
{
  "headline": "2-3 sentence overall status",
  "sections": [
    {"title": "", "icon": "fa-... (FontAwesome)", "tone": "info|success|warning|danger",
     "body": "markdown analysis", "items": ["short bullet", ...]}
  ],
  "recommended_actions": ["", ...],
  "warnings": ["", ...]
}
Only include sections supported by the DATA.
Base every statement on the supplied DATA. Never invent numbers.
"""


class FtProjectDashboardAi(models.TransientModel):
    _inherit = "ft.project.dashboard"

    # ------------------------------------------------------------------
    # RPC entry points (called by the injected AI Summary panel)
    # ------------------------------------------------------------------
    @api.model
    def get_ai_options(self):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        purposes = self.env["ft.ai.insights.purpose"].search_read(
            [("active", "=", True), ("applies_to", "=", "project")],
            ["id", "name", "code", "icon", "description"],
            order="sequence, name",
        )
        return {
            "periods": [{"key": k, "label": l} for k, l in AI_PERIODS],
            "purposes": purposes,
            "default_purpose_id": cfg.default_project_purpose_id.id or False,
            "configured": bool(cfg._resolve_api_key()) or cfg.provider == "ollama",
            "provider": cfg.provider,
            "model": cfg.model,
        }

    @api.model
    def get_ai_summary(self, period="this_month", purpose_id=None):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        if not (cfg._resolve_api_key() or cfg.provider == "ollama"):
            raise UserError(
                "No AI provider is configured. Set it under "
                "AI Insights > Configuration > Settings (or use Ollama, which "
                "needs no key)."
            )

        purpose = self.env["ft.ai.insights.purpose"]._resolve_for(
            "project", purpose_id, default=cfg.default_project_purpose_id
        )
        date_from, date_to = self._ai_date_range(period)
        collector = ProjectDataCollector(self.env, {"period": period}, date_from, date_to)
        payload = collector.collect()
        # Same rule as the full dashboard: milestone billing only where asked for.
        if purpose.include_milestones:
            payload["milestones"] = collector.milestones()

        period_label = dict(AI_PERIODS).get(period, period)
        messages = PromptBuilder(
            cfg.project_master_prompt or DEFAULT_PROJECT_MASTER_PROMPT,
            purpose.prompt,
            currency=self.env.company.currency_id.name or "",
            contract=PROJECT_RESPONSE_CONTRACT,
        ).build(
            payload,
            filters_label=(
                f"Period: {period_label} ({date_from} to {date_to}). "
                f"All hours are timesheet hours."
            ),
        )

        service = AIService(
            cfg.provider,
            api_key=cfg._resolve_api_key(),
            base_url=cfg.api_base_url,
            model=cfg.model,
            timeout=cfg.request_timeout,
        )
        started = time.monotonic()
        log_vals = {
            "name": f"Project: {purpose.name} — {period_label}",
            "purpose_id": purpose.id,
            "provider": cfg.provider,
            "model": cfg.model,
            "filters_json": json.dumps({
                "period": period,
                "from": str(date_from),
                "to": str(date_to),
                "purpose": purpose.code,
            }),
            "payload_json": json.dumps(payload, default=str) if cfg.debug_mode else False,
        }
        try:
            result = service.generate(
                messages,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                json_mode=True,
            )
        except AIProviderError as exc:
            self.env["ft.ai.insights.log"].sudo().create({
                **log_vals, "status": "error", "error_message": str(exc),
                "duration_ms": int((time.monotonic() - started) * 1000),
            })
            raise UserError(str(exc)) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        structured, raw_text = self._parse_json(result.text)
        log = self.env["ft.ai.insights.log"].sudo().create({
            **log_vals,
            "response": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "duration_ms": duration_ms,
            "status": "success",
        })
        return {
            "summary": structured,
            "raw_text": raw_text,
            "meta": {
                "log_id": log.id,
                "provider": cfg.provider,
                "model": result.model or cfg.model,
                "tokens": result.total_tokens,
                "duration_ms": duration_ms,
                "period": period_label,
                "purpose": purpose.name,
                "date_range": {"from": str(date_from), "to": str(date_to)},
            },
            "data": payload if cfg.debug_mode else None,
        }

    # ------------------------------------------------------------------
    # Date range
    # ------------------------------------------------------------------
    @api.model
    def _ai_date_range(self, period):
        today = fields.Date.context_today(self)
        if period == "this_week":
            start = today - timedelta(days=today.weekday())
            return start, today
        if period == "last_week":
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=6)
        if period == "last_2_weeks":
            return today - timedelta(days=14), today
        if period == "this_month":
            return today.replace(day=1), today
        if period == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return last_prev.replace(day=1), last_prev
        if period == "last_2_months":
            return (today - relativedelta(months=2)).replace(day=1), today
        if period == "last_3_months":
            return (today - relativedelta(months=3)).replace(day=1), today
        return today.replace(day=1), today

    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json(text):
        if not text:
            return None, None
        try:
            return json.loads(text), None
        except (ValueError, TypeError):
            cleaned = text.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            s, e = cleaned.find("{"), cleaned.rfind("}")
            if s != -1 and e > s:
                try:
                    return json.loads(cleaned[s : e + 1]), None
                except (ValueError, TypeError):
                    pass
            return None, text
