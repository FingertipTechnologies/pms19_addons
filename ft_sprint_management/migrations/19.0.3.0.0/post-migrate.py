"""Rename the existing weeks, and provision the ones that were never created.

Two things changed in 19.0.3.0.0:

  * A week's name is now derived from its Monday, in Odoo's own week format
    ("'W'w YYYY" in odoo/orm/models.py) — W40 2025. The names in the database
    were typed by hand, or written by the 19.0.2.0.0 migration as "Week 1".
    ``name`` is a stored computed field now, and Odoo does not recompute an
    existing column just because the field gained a compute, so the rows are
    rewritten here.

  * Weeks are created from task deadlines rather than by hand. From here on
    that happens as tasks are written; this fills in the history, so the boards
    have their columns on the first page load instead of after somebody has
    edited every task once.

Only the weeks that actually have work in them, because that is what the
boards draw. Provisioning whole years would put fifty-two mostly empty columns
on every board.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    weeks = env['qa_testapp.sprint'].search([])
    if weeks:
        weeks._compute_name()
        weeks.flush_recordset(['name'])
        _logger.info("Renamed %s weeks to their ISO week names.", len(weeks))

    tasks = env['project.task'].search([
        ('project_id', '!=', False),
        ('date_deadline', '!=', False),
    ])
    days = {task._ft_local_date(task.date_deadline) for task in tasks}

    # One shared week per Monday. This script originally provisioned a week per
    # project as well; 19.0.4.0.0 collapsed those into the shared ones, so
    # creating them here would only give that migration more to clean up.
    Week = env['qa_testapp.sprint']
    before = Week.search_count([])
    Week._ensure_weeks(days)

    _logger.info(
        "Provisioned %s weeks from %s task deadlines.",
        Week.search_count([]) - before, len(tasks))
