"""ft.ai.sales.insights — the RPC orchestrator behind the OWL dashboard.

Two public entry points:
* :meth:`get_filter_options` — feeds the filter dropdowns (teams, salespersons,
  stages, purposes, date-filter keys).
* :meth:`analyze` — runs the full pipeline: resolve config -> compute date
  range -> collect aggregated data (as current user) -> build prompt -> call
  AI -> log -> return a structured result for the UI.
"""
import json
import logging
import time
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ft_ai_sales_insights.services.ai_service import AIService
from odoo.addons.ft_ai_sales_insights.services.data_collector import (
    SalesDataCollector,
)
from odoo.addons.ft_ai_sales_insights.services.drilldown import attach_kpi_actions
from odoo.addons.ft_ai_sales_insights.services.layout_resolver import (
    enumerate_data_refs,
    resolve_layout,
)
from odoo.addons.ft_ai_sales_insights.services.prompt_builder import PromptBuilder
from odoo.addons.ft_ai_sales_insights.services.providers.base import AIProviderError

_logger = logging.getLogger(__name__)

# Predefined date-filter keys shown in the UI (label handled client-side too).
DATE_FILTERS = [
    ("all", "All Time"),
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("this_week", "This Week"),
    ("last_week", "Last Week"),
    ("last_2_weeks", "Last 2 Weeks"),
    ("last_30_days", "Last 30 Days"),
    ("this_month", "This Month"),
    ("last_month", "Last Month"),
    ("last_3_months", "Last 3 Months"),
    ("this_quarter", "This Quarter"),
    ("last_quarter", "Last Quarter"),
    ("this_year", "This Year"),
    ("custom", "Custom Date Range"),
]


class FtAiSalesInsights(models.TransientModel):
    _name = "ft.ai.sales.insights"
    _description = "AI Sales Insights orchestrator"

    # ------------------------------------------------------------------
    # Filter options
    # ------------------------------------------------------------------
    @api.model
    def get_filter_options(self):
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        teams = self.env["crm.team"].search_read(
            [], ["id", "name"], order="name"
        )
        salespersons = self.env["res.users"].search_read(
            [("share", "=", False), ("active", "=", True)],
            ["id", "name"],
            order="name",
        )
        stages = self.env["crm.stage"].search_read([], ["id", "name"], order="sequence")
        purposes = self.env["ft.ai.insights.purpose"].search_read(
            [("active", "=", True), ("applies_to", "=", "sales")],
            ["id", "name", "code", "icon", "description"],
            order="sequence, name",
        )
        return {
            "date_filters": [{"key": k, "label": l} for k, l in DATE_FILTERS],
            "teams": teams,
            "salespersons": salespersons,
            "stages": stages,
            "purposes": purposes,
            "default_purpose_id": cfg.default_purpose_id.id or False,
            "provider": cfg.provider,
            "model": cfg.model,
            "configured": bool(cfg._resolve_api_key()) or cfg.provider == "ollama",
        }

    @api.model
    def search_customers(self, query, limit=20):
        """name_search proxy for the customer autocomplete (respects rules)."""
        Partner = self.env["res.partner"]
        pairs = Partner.name_search(name=query or "", args=[], limit=limit)
        return [{"id": pid, "name": name} for pid, name in pairs]

    # ------------------------------------------------------------------
    # Date range
    # ------------------------------------------------------------------
    @api.model
    def _compute_date_range(self, key, custom_from=None, custom_to=None):
        today = fields.Date.context_today(self)
        if key in (None, "", "all"):
            return None, None
        if key == "custom":
            return custom_from or None, custom_to or None
        if key == "today":
            return today, today
        if key == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if key == "this_week":
            start = today - timedelta(days=today.weekday())
            return start, today
        if key == "last_week":
            start = today - timedelta(days=today.weekday() + 7)
            return start, start + timedelta(days=6)
        if key == "last_2_weeks":
            return today - timedelta(days=14), today
        if key == "last_30_days":
            return today - timedelta(days=30), today
        if key == "this_month":
            return today.replace(day=1), today
        if key == "last_month":
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            return last_prev.replace(day=1), last_prev
        if key == "last_3_months":
            return today - relativedelta(months=3), today
        if key == "this_quarter":
            q_start_month = 3 * ((today.month - 1) // 3) + 1
            return today.replace(month=q_start_month, day=1), today
        if key == "last_quarter":
            q_start_month = 3 * ((today.month - 1) // 3) + 1
            this_q_start = today.replace(month=q_start_month, day=1)
            last_q_end = this_q_start - timedelta(days=1)
            return last_q_end.replace(day=1) - relativedelta(months=2), last_q_end
        if key == "this_year":
            return today.replace(month=1, day=1), today
        return None, None

    # ------------------------------------------------------------------
    # Main analysis
    # ------------------------------------------------------------------
    @api.model
    def analyze(self, filters):
        """Run one analysis and return a structured result dict.

        :param filters: dict from the UI (date_filter, date_from/to, team_id,
            user_id, partner_id, stage_id, purpose_id, and *_label display
            strings).
        """
        filters = filters or {}
        cfg = self.env["ft.ai.insights.config"].sudo()._get_singleton()
        purpose = self._resolve_purpose(filters, cfg)

        date_from, date_to = self._compute_date_range(
            filters.get("date_filter"),
            filters.get("date_from"),
            filters.get("date_to"),
        )

        # 1) Collect aggregated data AS THE CURRENT USER (record rules apply).
        collector = SalesDataCollector(self.env, filters, date_from, date_to)
        payload = collector.collect()
        # Offer the model the metrics it may tag for click-through.
        drilldowns = collector.drilldowns()
        payload["available_kpi_keys"] = sorted(drilldowns)
        # Tell the model exactly which data it may reference in a layout, and
        # with which fields, so charts/tables it lays out are always data-backed.
        payload["available_data_refs"] = enumerate_data_refs(payload)

        # 2) Build the prompt from editable master + purpose prompts.
        currency = self.env.company.currency_id.name or ""
        messages = PromptBuilder(
            cfg.master_prompt, purpose.prompt, currency=currency
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
            "name": f"{purpose.name}",
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
        structured, raw_text = self._parse_response(result.text)
        structured = attach_kpi_actions(structured, drilldowns)
        # Fill any AI-chosen layout blocks with the real collected data (and drop
        # blocks referencing anything missing). No-op for purposes that returned
        # no layout, so the standard view is unaffected.
        structured = resolve_layout(structured, payload)

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
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_purpose(self, filters, cfg):
        # Shared with the Project dashboard so both resolve identically; only
        # the domain differs.
        return self.env["ft.ai.insights.purpose"]._resolve_for(
            "sales", filters.get("purpose_id"), default=cfg.default_purpose_id
        )

    @staticmethod
    def _filters_label(filters):
        bits = []
        for key in ("team_label", "user_label", "partner_label", "stage_label"):
            val = filters.get(key)
            if val and not str(val).lower().startswith("all"):
                bits.append(str(val))
        return ", ".join(bits) if bits else "no additional filters"

    @staticmethod
    def _parse_response(text):
        """Return (structured_dict_or_None, raw_text_or_None)."""
        if not text:
            return None, None
        try:
            return json.loads(text), None
        except (ValueError, TypeError):
            # Tolerate ```json fenced blocks or leading/trailing prose.
            cleaned = text.strip()
            if "```" in cleaned:
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(cleaned[start : end + 1]), None
                except (ValueError, TypeError):
                    pass
            return None, text
