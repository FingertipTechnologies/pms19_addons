"""Install-time backfill for the AMC Task Overdue Dashboard.

Two one-off repairs so that tasks which existed before this module (or before
ft_pms_planning_workflow's deadline tracking) report the same figures as tasks
created after it:

1. ``pwf_original_deadline`` where it is still NULL: recovered from the
   chatter's deadline tracking (the ``old_value_datetime`` of the EARLIEST
   ``mail.tracking.value`` row on ``date_deadline`` is the deadline the task
   had before its first change), else the current deadline. Only NULL rows
   are filled: an original deadline, once set, is never overwritten.
2. ``ft_historical_overdue_days`` for every task already completed
   (``state = '1_done'``), from the original deadline to the completion day
   (``date_end``, else ``date_last_stage_update``, else ``write_date``).
   Recomputed for every done task on each run, so a re-run after (1) fixed
   more originals also fixes the figures that depended on them.

Both are safe to run again (``odoo-bin -u`` does not re-run a post_init_hook;
call them from a shell when needed).
"""
import logging

_logger = logging.getLogger(__name__)


def backfill_original_deadlines(env):
    """Fill NULL ``pwf_original_deadline`` on project_task. Returns the count.

    SQL rather than ORM: the field is read-only, the pwf write hook would log
    nothing useful for it, and the earliest tracking row per task is a plain
    DISTINCT ON. ``mail_tracking_value`` points at its ``mail_message``
    (model / res_id) and at the ``ir_model_fields`` row of the tracked field;
    rows of removed fields keep ``field_id`` NULL and are skipped by the join.
    """
    Task = env['project.task']
    Task.flush_model(['pwf_original_deadline', 'date_deadline'])
    env.cr.execute("""
        WITH first_tracking AS (
            SELECT DISTINCT ON (m.res_id)
                   m.res_id AS task_id, v.old_value_datetime
              FROM mail_tracking_value v
              JOIN mail_message m ON m.id = v.mail_message_id
              JOIN ir_model_fields f ON f.id = v.field_id
             WHERE m.model = 'project.task'
               AND f.model = 'project.task'
               AND f.name = 'date_deadline'
               AND v.old_value_datetime IS NOT NULL
             ORDER BY m.res_id, m.create_date, m.id, v.id
        )
        UPDATE project_task t
           SET pwf_original_deadline = ft.old_value_datetime
          FROM first_tracking ft
         WHERE ft.task_id = t.id
           AND t.pwf_original_deadline IS NULL
    """)
    from_tracking = env.cr.rowcount
    env.cr.execute("""
        UPDATE project_task
           SET pwf_original_deadline = date_deadline
         WHERE pwf_original_deadline IS NULL
           AND date_deadline IS NOT NULL
    """)
    from_deadline = env.cr.rowcount
    Task.invalidate_model(['pwf_original_deadline'])
    _logger.info(
        "ft_amc_overdue_dashboard: original deadline backfilled on %d task(s) "
        "from the deadline tracking and on %d from the current deadline",
        from_tracking, from_deadline)
    return from_tracking + from_deadline


def backfill_historical_overdue(env):
    """Stamp ``ft_historical_overdue_days`` on every completed task.

    Day arithmetic runs in the same calendar as the cron of
    ft_task_hours_tracker (``_ft_cron_tz_env``: context tz, else the user's,
    else the company's, else the administrator's), because the hook runs as
    the superuser, which has no timezone of its own. Values are read through
    the ORM and written in SQL, grouped by value, so a large backlog costs a
    handful of UPDATEs and no write() chain. Returns the number of tasks
    whose stored figure changed.
    """
    Task = env['project.task'].sudo().with_context(active_test=False)
    Task = Task._ft_cron_tz_env()
    Task.flush_model(['ft_historical_overdue_days', 'state', 'date_end',
                      'date_last_stage_update', 'pwf_original_deadline',
                      'date_deadline'])
    done = Task.search_fetch(
        # 1_deployed: Deployed, ft_amc_payment_milestone, counts as done
        [('state', 'in', ['1_done', '1_deployed'])],
        ['ft_historical_overdue_days', 'date_end', 'date_last_stage_update',
         'write_date', 'pwf_original_deadline', 'date_deadline'])
    by_value = {}
    for task in done:
        end = task.date_end or task.date_last_stage_update or task.write_date
        days = task._ft_amc_overdue_days_between(
            task.ft_overdue_reference_deadline(), end)
        if days != (task.ft_historical_overdue_days or 0):
            by_value.setdefault(days, []).append(task.id)
    changed = 0
    for days, ids in by_value.items():
        env.cr.execute(
            "UPDATE project_task SET ft_historical_overdue_days = %s "
            "WHERE id IN %s", (days, tuple(ids)))
        changed += env.cr.rowcount
    Task.invalidate_model(['ft_historical_overdue_days'])
    _logger.info(
        "ft_amc_overdue_dashboard: overdue-at-completion stamped on %d of %d "
        "completed task(s)", changed, len(done))
    return changed


def post_init_hook(env):
    backfill_original_deadlines(env)
    backfill_historical_overdue(env)
