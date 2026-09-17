"""Renumber every week continuously: W40, then W53 rather than W1 2026.

The count now runs on from a fixed Monday (week_utils.WEEK_EPOCH) instead of
restarting each January, so a week is identified by its number alone and no
year is carried beside it.

``name`` is stored, and Odoo does not rewrite an existing column just because
the compute behind it changed, so every row is recomputed here. Without this
the database would keep the old "W40 2025" names and only weeks created from
now on would carry the new ones — two formats in one list.
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
    _logger.info("Renumbered %s weeks continuously (%s ... %s).",
                 len(weeks), weeks[0].name, weeks[-1].name)
