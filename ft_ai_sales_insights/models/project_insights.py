"""ft.ai.project.insights — the RPC orchestrator behind the Project OWL dashboard.

The Project counterpart of ``ft.ai.sales.insights``, with the same two public
entry points and the same pipeline, differing only in *what* is filtered and
collected:

* :meth:`get_filter_options` — feeds the filter dropdowns (projects, developers,
  purposes, date-filter keys).
* :meth:`analyze` — resolve config -> compute date range -> collect aggregated
  delivery data (as current user) -> build prompt -> call AI -> log -> return a
  structured result for the UI.
"""
import json
import logging
import time

from odoo import api, models
from odoo.exceptions import UserError

from odoo.addons.ft_ai_sales_insights.models.sales_insights import DATE_FILTERS
from odoo.addons.ft_ai_sales_insights.services.ai_service import AIService
from odoo.addons.ft_ai_sales_insights.services.drilldown import attach_kpi_actions
from odoo.addons.ft_ai_sales_insights.services.project_data_collector import (
    ProjectDataCollector,
)
from odoo.addons.ft_ai_sales_insights.services.prompt_builder import PromptBuilder
from odoo.addons.ft_ai_sales_insights.services.providers.base import AIProviderError

_logger = logging.getLogger(__name__)

# Fallback only. The real prompt is ``config.project_master_prompt`` (editable,
# seeded in data/ai_config_data.xml). This constant covers databases whose config
# record predates that field, since the seed record is noupdate="1".
DEFAULT_PROJECT_MASTER_PROMPT = """You are an experienced Delivery Director and PMO lead \
advising executive leadership.

You analyse project execution data (timesheets, tasks, estimates, milestones, bugs) \
and produce concise, data-backed analysis for management.

Rules:
- Base every statement strictly on the supplied DATA. Never invent numbers or names.
- Be specific and quantify (hours, counts, % over/under estimate).
- Flag over-runs (used > estimated), stalled work, and pending backlogs.
- Cover delivery quality when a "bugs" block is present: open vs closed, blocker/critical
  severity, re-opened bugs and client-raised bugs are leading indicators of risk.
- Cover effort when a "timesheets" block is present: where the hours actually went, and
  call out hours booked with no task attached.
- If the data is insufficient for a claim, say so instead of guessing.
- Keep it executive and actionable."""

# Mirrors the Sales contract in prompt_builder, in delivery terms, so the same
# OWL renderer (score gauge, KPI tiles, sections) displays it unchanged.
PROJECT_RESPONSE_CONTRACT = """
Return a SINGLE valid JSON object (no markdown fences, no prose) with this shape:
{
  "executive_summary": "2-4 sentence markdown summary",
  "overall_score": 0-100 integer (delivery health),
  "score_label": "short qualitative label, e.g. 'On Track', 'At Risk'",
  "kpis": [{"label": "", "value": "", "trend": "up|down|flat", "status": "good|warning|bad", "key": "optional"}],
  "sections": [{"title": "", "icon": "fa-... (FontAwesome)", "tone": "info|success|warning|danger", "body": "markdown", "items": ["bullet", ...]}],
  "at_risk_projects": [{"name": "", "reason": "", "detail": ""}],
  "resource_performance": [{"name": "", "highlight": "", "coaching": ""}],
  "recommended_actions": [{"priority": "high|medium|low", "action": ""}],
  "immediate_priorities": ["", ...],
  "warnings": ["", ...]
}
Only include keys that are relevant to the requested purpose; omit the rest.
Base every statement on the supplied DATA. Never invent numbers.
If the DATA contains a "scope" block, respect it: when it names a single
developer or project, analyse only that scope.

On kpi "key": the DATA contains "available_kpi_keys". When a KPI you emit is
exactly one of those metrics, set "key" to that exact string so the user can
click through to the records. If it is a derived or blended figure, omit "key".
Never invent a key that is not in available_kpi_keys.
"""


class FtAiProjectInsights(models.TransientModel):
    _name = "ft.ai.project.insights"
    _description = "AI Project Insights orchestrator"

    # ------------------------------------------------------------------
    # Filter options
    # ------------------------------------------------------------------
    @api.model
    def get_filter_options(self):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        projects = self.env["project.project"].search_read(
            [], ["id", "name"], order="name"
        )
        # Developers = employees, since timesheets are logged per employee.
        developers = self.env["hr.employee"].search_read(
            [("active", "=", True)], ["id", "name"], order="name"
        )
        purposes = self.env["ft.ai.insights.purpose"].search_read(
            [("active", "=", True), ("applies_to", "=", "project")],
            ["id", "name", "code", "icon", "description"],
            order="sequence, name",
        )
        return {
            "date_filters": [{"key": k, "label": l} for k, l in DATE_FILTERS],
            "projects": projects,
            "developers": developers,
            "purposes": purposes,
            "default_purpose_id": cfg.default_project_purpose_id.id or False,
            "provider": cfg.provider,
            "model": cfg.model,
            "configured": bool(cfg._resolve_api_key()) or cfg.provider == "ollama",
        }

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------
    @api.model
    def analyze(self, filters):
        """Run one project analysis and return a structured result dict.

        :param filters: dict from the UI (date_filter, date_from/to,
            project_id, employee_id, purpose_id, and *_label display strings).
        """
        filters = filters or {}
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        if not (cfg._resolve_api_key() or cfg.provider == "ollama"):
            raise UserError(
                "No AI provider is configured. Set it under "
                "AI Insights > Configuration > Settings (or use Ollama, which "
                "needs no key)."
            )
        purpose = self.env["ft.ai.insights.purpose"]._resolve_for(
            "project", filters.get("purpose_id"), default=cfg.default_project_purpose_id
        )

        # Date maths is identical to Sales; reuse it rather than duplicating.
        date_from, date_to = self.env["ft.ai.sales.insights"]._compute_date_range(
            filters.get("date_filter"),
            filters.get("date_from"),
            filters.get("date_to"),
        )

        # 1) Collect aggregated data AS THE CURRENT USER (record rules apply).
        collector = ProjectDataCollector(self.env, filters, date_from, date_to)
        payload = collector.collect()
        # Milestones are a billing lifecycle, not delivery timing, so only the
        # purposes that ask for them receive them — they are noise (and a source
        # of invented "delay") in delivery and per-developer reports.
        if purpose.include_milestones:
            payload["milestones"] = collector.milestones()
        # Offer the model the metrics it may tag for click-through.
        drilldowns = collector.drilldowns(include_milestones=purpose.include_milestones)
        payload["available_kpi_keys"] = sorted(drilldowns)

        # 2) Build the prompt from editable master + purpose prompts.
        messages = PromptBuilder(
            cfg.project_master_prompt or DEFAULT_PROJECT_MASTER_PROMPT,
            purpose.prompt,
            currency=self.env.company.currency_id.name or "",
            contract=PROJECT_RESPONSE_CONTRACT,
        ).build(payload, filters_label=self._filters_label(filters))

        # 3) Call the configured provider.
        service = AIService(
            cfg.provider,
            api_key=cfg._resolve_api_key(),
            base_url=cfg.api_base_url,
            model=cfg.model,
            timeout=cfg.request_timeout,
        )
        started = time.monotonic()
        log_vals = {
            "name": f"Project: {purpose.name}",
            "purpose_id": purpose.id,
            "provider": cfg.provider,
            "model": cfg.model,
            "filters_json": json.dumps(filters, default=str),
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
            self.env["ft.ai.insights.log"].sudo().create(
                {**log_vals, "status": "error", "error_message": str(exc),
                 "duration_ms": int((time.monotonic() - started) * 1000)}
            )
            raise UserError(str(exc)) from exc

        duration_ms = int((time.monotonic() - started) * 1000)
        structured, raw_text = self.env["ft.ai.sales.insights"]._parse_response(
            result.text
        )
        structured = attach_kpi_actions(structured, drilldowns)

        # 4) Audit log.
        log = self.env["ft.ai.insights.log"].sudo().create({
            **log_vals,
            "response": result.text,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
            "duration_ms": duration_ms,
            "status": "success",
        })

        return {
            "insight": structured,
            "raw_text": raw_text,
            "meta": {
                "log_id": log.id,
                "provider": cfg.provider,
                "model": result.model or cfg.model,
                "tokens": result.total_tokens,
                "duration_ms": duration_ms,
                "purpose": purpose.name,
                "date_range": {"from": str(date_from or ""), "to": str(date_to or "")},
            },
            "payload": payload if cfg.debug_mode else None,
        }

    @api.model
    def save_to_chatter(self, log_id):
        log = self.env["ft.ai.insights.log"].browse(int(log_id))
        log.action_post_to_chatter()
        return True

    # ------------------------------------------------------------------
    @staticmethod
    def _filters_label(filters):
        bits = []
        for key in ("project_label", "developer_label"):
            val = filters.get(key)
            if val and not str(val).lower().startswith("all"):
                bits.append(str(val))
        return ", ".join(bits) if bits else "no additional filters"
