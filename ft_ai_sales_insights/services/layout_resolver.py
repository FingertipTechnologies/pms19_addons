"""Layout resolver — turns the AI's chosen layout into safe, data-backed blocks.

The AI does not send numbers. It sends a *layout*: an ordered list of blocks,
each naming a block ``type`` and a ``data_ref`` (a key into the aggregated
payload the server already computed). This module:

  * enumerates which refs are available for a given payload, so the prompt can
    tell the model exactly what it may reference, and
  * resolves each block against the payload, injecting the REAL server data and
    dropping any block that references something missing or malformed.

This is what makes "the AI decides the layout" safe: the model chooses the
shape and emphasis; the figures always come from the collected data, never from
the model's own text.
"""
from __future__ import annotations

# Block types the front-end knows how to render. Anything else is dropped.
CHART_TYPES = ("bar_chart", "line_chart", "pie_chart")
TEXT_TYPES = ("section", "callout")
KNOWN_TYPES = CHART_TYPES + TEXT_TYPES + ("kpi_tiles", "table")


def enumerate_data_refs(payload: dict) -> dict:
    """Map every referenceable path in ``payload`` to its usable fields.

    Only two shapes are exposed:
      * a list of dicts (``records``) — usable by tables and charts, and
      * a flat dict of scalars (``scalars``) — usable for KPI tile values.
    Walked one level into nested dicts (e.g. ``pipeline.by_stage``), which
    covers how the collector nests its sections.
    """
    refs = {}

    def _record_fields(rows):
        return sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else []

    def _scalar_fields(d):
        return sorted(k for k, v in d.items() if not isinstance(v, (list, dict)))

    for key, value in payload.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            refs[key] = {"kind": "records", "fields": _record_fields(value)}
        elif isinstance(value, dict):
            scalars = _scalar_fields(value)
            if scalars:
                refs[key] = {"kind": "scalars", "fields": scalars}
            for sub_key, sub_val in value.items():
                if isinstance(sub_val, list) and sub_val and isinstance(sub_val[0], dict):
                    refs[f"{key}.{sub_key}"] = {
                        "kind": "records", "fields": _record_fields(sub_val),
                    }
    return refs


def resolve_ref(payload: dict, ref):
    """Walk a dotted ``ref`` (e.g. 'pipeline.by_stage') into ``payload``."""
    if not ref or not isinstance(ref, str):
        return None
    current = payload
    for part in ref.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _resolve_chart(block, payload):
    rows = resolve_ref(payload, block.get("data_ref"))
    x, y = block.get("x"), block.get("y")
    if not (isinstance(rows, list) and x and y):
        return None
    labels, data = [], []
    for row in rows:
        if not isinstance(row, dict) or x not in row or y not in row:
            continue
        labels.append(row.get(x))
        data.append(row.get(y))
    if not labels:
        return None
    block["_chart"] = {"labels": labels, "data": data}
    return block


def _resolve_table(block, payload):
    rows = resolve_ref(payload, block.get("data_ref"))
    columns = block.get("columns")
    if not (isinstance(rows, list) and isinstance(columns, list) and columns):
        return None
    # Keep only well-formed columns; a table with none is useless, so drop it.
    clean_cols = [c for c in columns if isinstance(c, dict) and c.get("key")]
    if not clean_cols:
        return None
    block["columns"] = clean_cols
    block["_rows"] = [r for r in rows if isinstance(r, dict)]
    return block


def _resolve_kpis(block, payload):
    items = block.get("items")
    if not isinstance(items, list) or not items:
        return None
    clean = []
    for item in items:
        if not isinstance(item, dict) or not item.get("label"):
            continue
        # Prefer a value pulled from real data; fall back to the model's own
        # value only when it named no ref (e.g. a blended figure).
        ref = item.get("value_ref")
        if ref:
            value = resolve_ref(payload, ref)
            if value is not None and not isinstance(value, (list, dict)):
                item["value"] = value
        clean.append(item)
    if not clean:
        return None
    block["_items"] = clean
    return block


def resolve_layout(structured: dict, payload: dict) -> dict:
    """Resolve ``structured['layout']`` in place; drop any block that can't be.

    A no-op when the model returned no ``layout`` (an older purpose), so the
    dashboard falls back to its fixed layout untouched.
    """
    if not isinstance(structured, dict):
        return structured
    blocks = structured.get("layout")
    if not isinstance(blocks, list):
        return structured

    resolved = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type in CHART_TYPES:
            out = _resolve_chart(block, payload)
        elif block_type == "table":
            out = _resolve_table(block, payload)
        elif block_type == "kpi_tiles":
            out = _resolve_kpis(block, payload)
        elif block_type in TEXT_TYPES:
            out = block  # prose only, authored by the model — nothing to resolve
        else:
            out = None  # unknown type
        if out is not None:
            resolved.append(out)

    structured["layout"] = resolved
    return structured
