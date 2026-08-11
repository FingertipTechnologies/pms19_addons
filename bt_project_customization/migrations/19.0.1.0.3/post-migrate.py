"""Backfill delivery dates for stages that are final by NAME, not by fold flag.

``_compute_ft_completion_date`` used to set a date only when the task's stage had
"Folded in Kanban" ticked. It now also accepts stages named in
COMPLETED_STAGE_NAMES, because on the production database nobody had ticked that
flag: 6,768 active tasks sat across 489 non-folded stages and not one task was in
a folded stage, so every delivery metric read zero even though 1,826 tasks were
sitting in a stage called "Completed".

Odoo does NOT recompute a stored computed field just because its compute body
changed, so those tasks would keep their empty ft_completion_date until each one
was next written. This backfills them in one statement.

``date_end`` is backfilled alongside it for the same reason the 18.0.1.0.2
migration did so: the PMS metrics read ft_completion_date, but Odoo's own Tasks
Analysis and burndown reports read date_end directly, and would otherwise keep
disagreeing with the dashboard.

Raw SQL on purpose, mirroring 18.0.1.0.2: this must not fire ft_reopen_count,
retrigger stored computes across every task, or write a mail.tracking row per
row. Cancelled tasks are left alone — a cancellation is not a delivery. The
stage list comes from the model helper rather than being restated in SQL, so
there is still only one definition of "final stage".
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    final_stage_ids = env['project.task']._ft_final_stage_ids()
    if not final_stage_ids:
        _logger.warning(
            "bt_project_customization: no final task stages found — nothing to "
            "backfill. Delivery metrics will read zero until a stage is either "
            "named in COMPLETED_STAGE_NAMES or marked Folded in Kanban."
        )
        return

    # date_end first: ft_completion_date prefers it, so filling it here means the
    # completion date below lands on the more precise value where one exists.
    cr.execute("""
        UPDATE project_task t
           SET date_end = t.date_last_stage_update
         WHERE t.stage_id IN %s
           AND t.date_end IS NULL
           AND t.date_last_stage_update IS NOT NULL
           AND (t.state IS NULL OR t.state != '1_canceled')
    """, (tuple(final_stage_ids),))
    _logger.info(
        "bt_project_customization: backfilled date_end on %s task(s)",
        cr.rowcount,
    )

    cr.execute("""
        UPDATE project_task t
           SET ft_completion_date = COALESCE(t.date_end, t.date_last_stage_update)
         WHERE t.stage_id IN %s
           AND t.ft_completion_date IS NULL
           AND COALESCE(t.date_end, t.date_last_stage_update) IS NOT NULL
           AND (t.state IS NULL OR t.state != '1_canceled')
    """, (tuple(final_stage_ids),))
    _logger.info(
        "bt_project_customization: backfilled ft_completion_date on %s task(s)",
        cr.rowcount,
    )

    # A task sitting in a NON-final stage must not keep a completion date from
    # before this change, or it would be counted as both delivered and open.
    cr.execute("""
        UPDATE project_task t
           SET ft_completion_date = NULL
         WHERE t.ft_completion_date IS NOT NULL
           AND (t.stage_id IS NULL OR t.stage_id NOT IN %s)
    """, (tuple(final_stage_ids),))
    _logger.info(
        "bt_project_customization: cleared ft_completion_date on %s task(s) no "
        "longer in a final stage", cr.rowcount,
    )
