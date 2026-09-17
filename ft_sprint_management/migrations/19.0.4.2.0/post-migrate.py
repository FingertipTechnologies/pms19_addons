"""Renumber the weeks from the first week of 2026.

W1 is now the week of 29 December 2025 — ISO week 1 of 2026 — and the count
runs on from there without restarting, so the last week of 2026 is W53 and the
first of 2027 is W54. Weeks earlier than that fall outside the count and keep
their ISO name, year included ("W40 2025"), rather than being given the zero
and negative numbers the arithmetic would otherwise hand them.

``name`` is stored, and Odoo does not rewrite an existing column just because
the compute behind it changed, so every row is recomputed here. Without this
the database would keep the numbers from the old epoch and only weeks created
from now on would carry the new ones — the same week under two numbers.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    weeks = env['qa_testapp.sprint'].search([])
    if not weeks:
        return
    weeks._compute_name()
    weeks.flush_recordset(['name'])
    _logger.info("Renumbered %s weeks from the first week of 2026 (%s ... %s).",
                 len(weeks), weeks[0].name, weeks[-1].name)
