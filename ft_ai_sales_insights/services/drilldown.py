"""Turn the model's KPI ``key`` tags into clickable record lists.

The AI writes the KPI tiles, so it cannot know a domain. Instead each collector
publishes ``drilldowns()`` — real domains built from the same filters that
produced the numbers — and the model tags a KPI with one of those keys. This
maps tag -> action, ignoring anything it doesn't recognise, so a hallucinated or
missing key degrades to a plain (non-clickable) tile rather than a wrong list.
"""
from __future__ import annotations


def attach_kpi_actions(structured, drilldowns: dict):
    """Add an ``action`` dict to every KPI whose ``key`` is a known drill-down."""
    if not isinstance(structured, dict) or not drilldowns:
        return structured
    kpis = structured.get("kpis")
    if not isinstance(kpis, list):
        return structured
    for kpi in kpis:
        if not isinstance(kpi, dict):
            continue
        spec = drilldowns.get(kpi.get("key"))
        if not spec:
            # Drop unrecognised keys so the UI never renders a dead click.
            kpi.pop("key", None)
            continue
        kpi["action"] = {
            "res_model": spec["res_model"],
            "name": spec.get("name") or kpi.get("label") or "Records",
            "domain": spec["domain"],
            "context": spec.get("context") or {},
        }
    return structured
