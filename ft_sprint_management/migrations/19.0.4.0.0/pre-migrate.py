"""Collapse the per-project weeks into one shared week per Monday.

A week used to be cut into one record per project, so W41 existed four times
over — once for each project with work in it — plus an "All Projects" copy that
counted them all. The Weeks list read as four identical rows with the work
split between them, and the same seven days answered to four different records.

There is now exactly one week per Monday. The project is a property of the
tasks inside the week, not of the week.

Done in SQL and in the pre-migration because the ORM can no longer help: by the
time the registry is built, ``project_id`` is not a field of the model any
more, so nothing could read it to decide which weeks to merge or which tasks to
move. The column is still in the table at this point, and is dropped at the end
of this script.

Order matters, and each step is written so that re-running it is harmless:

  0. Drop the NOT NULL on ``project_id`` first. On a database still carrying
     the schema of 19.0.1.0.0 the field was ``required=True``, and a
     pre-migration runs BEFORE Odoo reconciles the table with the new field
     definitions — so step 1 would be writing NULL into a column Postgres has
     not yet been told may hold one, and the whole upgrade would roll back on
     "Missing required value for the field 'project_id'".
  1. Promote a per-project week to the shared one where its Monday has no
     shared week yet. Promotion rather than insertion: it reuses a row that
     already carries the right dates and name, so nothing has to be recreated
     and no column of this table has to be known about here.
  2. Move every task off the week it was linked to and on to the shared week
     for the same Monday. This has to happen before the delete or the FK's
     ON DELETE SET NULL would blank the link on every task at once.
  3. Delete what is left — the redundant per-project copies.
  4. Drop the column.

``sprint_start_date`` and ``sprint_end_date`` on the task are stored related
columns and are deliberately left alone: every week sharing a Monday has the
same start and end dates, so the values they hold are still correct after the
tasks move.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # 0. The column is about to hold NULLs. On a database upgrading from
    #    19.0.1.0.0 it is still NOT NULL, and nothing has relaxed it yet — the
    #    field definitions are not applied until after every pre-migration has
    #    run. A no-op where the constraint is already gone.
    cr.execute(
        "ALTER TABLE qa_testapp_sprint ALTER COLUMN project_id DROP NOT NULL")

    # 1. Every Monday needs a shared (project-less) week. Where one is missing,
    #    the lowest-numbered per-project week for that Monday becomes it.
    cr.execute("""
        UPDATE qa_testapp_sprint
           SET project_id = NULL
         WHERE id IN (
            SELECT DISTINCT ON (p.start_date) p.id
              FROM qa_testapp_sprint p
             WHERE p.project_id IS NOT NULL
               AND NOT EXISTS (
                    SELECT 1 FROM qa_testapp_sprint g
                     WHERE g.project_id IS NULL
                       AND g.start_date = p.start_date)
             ORDER BY p.start_date, p.id
         )
    """)
    promoted = cr.rowcount

    # 2. Re-point the tasks before anything is deleted.
    cr.execute("""
        UPDATE project_task t
           SET sprint_id = g.id
          FROM qa_testapp_sprint s
          JOIN qa_testapp_sprint g
            ON g.project_id IS NULL AND g.start_date = s.start_date
         WHERE t.sprint_id = s.id
           AND s.project_id IS NOT NULL
    """)
    relinked = cr.rowcount

    # 3. The per-project copies have nothing left pointing at them.
    cr.execute("DELETE FROM qa_testapp_sprint WHERE project_id IS NOT NULL")
    removed = cr.rowcount

    # 4. A week has no project any more.
    cr.execute("ALTER TABLE qa_testapp_sprint DROP COLUMN IF EXISTS project_id")

    _logger.info(
        "Weeks are now shared: promoted %s, moved %s tasks, removed %s "
        "duplicate per-project weeks.", promoted, relinked, removed)
