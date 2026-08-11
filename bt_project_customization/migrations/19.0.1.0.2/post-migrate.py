"""Backfill `date_end` on tasks that were completed but never stamped.

Odoo writes `date_end` in `project.task.update_date_end()` only when `stage_id`
is written, and writes False whenever the target stage is not folded. Any task
that entered a stage BEFORE that stage was marked "Folded in Kanban" therefore
sits in a folded stage forever with an empty date_end. The PMS delivery metrics
now read `ft_completion_date`, which falls back to `date_last_stage_update`, so
they no longer care — but Odoo's own Tasks Analysis and burndown reports still
read date_end directly and would keep disagreeing with the dashboard.

`date_last_stage_update` is written by the same core code path on every stage
change, so for these tasks it holds the moment they were completed.

Raw SQL on purpose: this must not fire `ft_reopen_count`, retrigger stored
computes across every task in the database, or write a mail.tracking row for
each one. Cancelled tasks are left alone — a cancellation is not a delivery.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        UPDATE project_task t
           SET date_end = t.date_last_stage_update
          FROM project_task_type s
         WHERE t.stage_id = s.id
           AND s.fold = TRUE
           AND t.date_end IS NULL
           AND t.date_last_stage_update IS NOT NULL
           AND (t.state IS NULL OR t.state != '1_canceled')
    """)
    _logger.info(
        "bt_project_customization: backfilled date_end on %s completed task(s)",
        cr.rowcount,
    )
