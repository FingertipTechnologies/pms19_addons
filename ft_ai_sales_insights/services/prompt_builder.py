"""PromptBuilder — assembles the message list sent to the AI.

No prompt text is hardcoded here. The master prompt and the per-purpose prompt
are passed in (they come from editable DB records). This class only *composes*
them with the aggregated data payload and a strict response contract.
"""
from __future__ import annotations

import json

# The structured shape we ask the model to return. The OWL dashboard renders
# these keys; anything missing simply doesn't render. ``raw_text`` is a
# fallback the UI shows verbatim when JSON parsing fails.
RESPONSE_CONTRACT = """
Return a SINGLE valid JSON object (no markdown fences, no prose) with this shape:
{
  "executive_summary": "2-4 sentence markdown summary",
  "overall_score": 0-100 integer,
  "score_label": "short qualitative label, e.g. 'Healthy', 'At Risk'",
  "kpis": [{"label": "", "value": "", "trend": "up|down|flat", "status": "good|warning|bad", "key": "optional"}],
  "sections": [{"title": "", "icon": "fa-... (FontAwesome)", "tone": "info|success|warning|danger", "body": "markdown", "items": ["bullet", ...]}],
  "top_opportunities": [{"name": "", "amount": "", "probability": "", "note": ""}],
  "at_risk_deals": [{"name": "", "amount": "", "reason": ""}],
  "salesperson_performance": [{"name": "", "highlight": "", "coaching": ""}],
  "recommended_actions": [{"priority": "high|medium|low", "action": ""}],
  "immediate_priorities": ["", ...],
  "forecast": {"amount": "", "confidence": "high|medium|low", "note": ""},
  "warnings": ["", ...]
}
Only include keys that are relevant to the requested purpose; omit the rest.
Base every statement on the supplied DATA. Never invent numbers.

On kpi "key": the DATA contains "available_kpi_keys". When a KPI you emit is
exactly one of those metrics, set "key" to that exact string so the user can
click through to the records. If it is a derived or blended figure, omit "key".
Never invent a key that is not in available_kpi_keys.

OPTIONAL "layout": you MAY additionally return a "layout" array that decides how
this analysis is presented. You choose the blocks and their order; the SERVER
fills in every number from the DATA, so you never type figures into a chart or
table yourself. Reference data only through "data_ref"/"value_ref" taken from
"available_data_refs" in the DATA — each entry lists its usable "fields".
"layout": [
  {"type": "kpi_tiles", "title": "", "items": [
      {"label": "", "value_ref": "one of available_data_refs 'scalars' fields path, e.g. 'summary.won'", "key": "optional available_kpi_key"}]},
  {"type": "table", "title": "", "data_ref": "a 'records' ref, e.g. 'salespersons'",
      "columns": [{"key": "a field of that ref", "label": ""}]},
  {"type": "bar_chart"|"line_chart"|"pie_chart", "title": "",
      "data_ref": "a 'records' ref, e.g. 'pipeline.by_stage'",
      "x": "a field name for labels", "y": "a numeric field name for values"},
  {"type": "section"|"callout", "title": "", "tone": "info|success|warning|danger",
      "body": "markdown", "items": ["bullet", ...]}
]
Rules for layout: use ONLY data_ref/value_ref values present in
available_data_refs, and ONLY x/y/column keys listed under that ref's "fields".
Pick chart types that suit the data (a distribution across stages -> bar or pie;
a trend over time -> line). Omit "layout" entirely if a plain summary fits
better — the dashboard renders its standard view when no layout is given.
"""


class PromptBuilder:
    def __init__(
        self,
        master_prompt: str,
        purpose_prompt: str,
        currency: str = "",
        contract: str = RESPONSE_CONTRACT,
    ):
        self.master_prompt = (master_prompt or "").strip()
        self.purpose_prompt = (purpose_prompt or "").strip()
        self.currency = currency
        # Domains return different shapes (Sales scores deals, Project scores
        # delivery), so the contract is injectable. Defaults to the Sales one.
        self.contract = (contract or "").strip()

    def build(self, payload: dict, filters_label: str = "") -> list[dict]:
        """Return the OpenAI-style ``messages`` list."""
        system = "\n\n".join(
            part for part in (self.master_prompt, self.contract) if part
        )
        cur = f"\nAll monetary values are in {self.currency}." if self.currency else ""
        user = (
            f"{self.purpose_prompt}\n"
            f"{('Applied filters: ' + filters_label) if filters_label else ''}"
            f"{cur}\n\n"
            f"DATA (aggregated):\n```json\n"
            f"{json.dumps(payload, default=str, ensure_ascii=False, indent=2)}\n```"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
