"""Flag the tasks the overdue cron has already auto-completed.

19.0.0.1.2 adds project.task.ft_auto_completed, which the daily
_cron_ft_auto_complete_overdue_tasks sets when it moves a task to Completed
and which keeps the cron from ever completing that task again. Tasks it closed
before this version have no flag, so the first run after a user reopened one
would close it again. Each such task carries the cron's chatter note
("Automatically moved to Completed: ..."), which identifies them exactly.

Raw SQL: only the new column is written — no stage, write() guards, tracking
or stored computes. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Fresh install: the cron has never run, nothing to flag.
    if not version:
        return
    cr.execute("""
        UPDATE project_task t
           SET ft_auto_completed = TRUE
         WHERE COALESCE(t.ft_auto_completed, FALSE) = FALSE
           AND EXISTS (
                SELECT 1
                  FROM mail_message m
                 WHERE m.model = 'project.task'
                   AND m.res_id = t.id
                   AND m.body::text ILIKE %s
           )
    """, ('%Automatically moved to Completed%',))
    _logger.info(
        "ft_auto_completed: flagged %s previously auto-completed task(s)",
        cr.rowcount)
