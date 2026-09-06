"""Create ``project.task.task_source`` empty instead of letting Odoo backfill it.

``task_source`` is a STORED computed field. When Odoo has to create the column
itself during the upgrade it also schedules ``_compute_task_source`` on every
existing task and then runs ``_check_task_source_rules`` on the result. The
compute derives the source from the project's CURRENT stage, so on a live
database that stamps thousands of legacy tasks as Planned / Unplanned /
Change Request and the very first one that is not in a Discovery project, has
no customer ticket, or has no unplanned reason raises a ValidationError — and
the whole upgrade rolls back. That is exactly what left the database at
19.0.1.0.5 while the code was already at 19.0.1.2.3 (``column
project_project.regression_date does not exist``).

The field's own docstring says the source records where the project stood WHEN
THE WORK ARRIVED; guessing it from where the project stands today is wrong for
legacy tasks anyway. So the column is created here, before the ORM looks at the
table, and left NULL: Odoo only backfills a stored compute when it created the
column itself. New tasks still get their default from the compute on create.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'project_task'
           AND column_name = 'task_source'
    """)
    if cr.fetchone():
        return
    cr.execute("ALTER TABLE project_task ADD COLUMN task_source VARCHAR")
    _logger.info(
        "bt_project_customization: created project_task.task_source empty so "
        "legacy tasks are not back-stamped from their project's current stage"
    )
