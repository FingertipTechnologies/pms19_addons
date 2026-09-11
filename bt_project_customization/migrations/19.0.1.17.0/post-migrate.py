"""Bring `state` into line with the stage on the tasks that already exist.

19.0.1.17.0 makes a task's core `state` follow its stage: entering a final
stage sets 1_done, leaving one returns it to 01_in_progress. That fixes every
task from here on, and nothing at all about the ones already in the database —
which is most of them.

Why it matters more than a wrong-looking badge:

`state` is what Odoo means by closed. `is_closed` is computed from it and
searched through `_search_is_closed`, so the Open and Closed filters, the
subtask counters, the rotting rules and anything else built on `is_closed` all
read it. Nothing in this PMS had ever set it, and `_compute_state` actively
resets an open task to 01_in_progress whenever its stage changes — so moving a
task INTO Completed re-stamped it as in progress. The result was an Open filter
that returned the completed work too, which is what prompted this.

Final is this PMS's own definition, matching _ft_final_stage_ids: a folded
stage, or one named in COMPLETED_STAGE_NAMES whether or not anybody remembered
to tick Folded — which on this stage set nobody did.

Cancelled tasks are left alone. A cancelled task is closed already, and
1_canceled carries a meaning 1_done would destroy.

Written in SQL rather than through the ORM on purpose: this touches thousands
of rows, `state` is a stored computed field whose ORM write would drag every
dependent recomputation along with it, and project.task.write is layered with
validation and audit stamping that has no business firing for a backfill.
"""
import logging

_logger = logging.getLogger(__name__)

# Kept in step with COMPLETED_STAGE_NAMES in models/project_task.py.
COMPLETED_STAGE_NAMES = ('Completed',)


def migrate(cr, version):
    if not version:
        return

    # The stage name is a translated jsonb column, so it is matched on the
    # en_US value the way _ft_final_stage_ids does by loading the records.
    cr.execute("""
        SELECT id FROM project_task_type
         WHERE fold = TRUE
            OR name->>'en_US' IN %s
    """, (COMPLETED_STAGE_NAMES,))
    final_ids = tuple(row[0] for row in cr.fetchall())
    if not final_ids:
        _logger.warning(
            "No final task stages found; leaving task states untouched.")
        return

    cr.execute("""
        UPDATE project_task
           SET state = '1_done'
         WHERE stage_id IN %s
           AND state NOT IN ('1_done', '1_canceled')
    """, (final_ids,))
    closed = cr.rowcount

    # The mirror image: anything previously stamped 1_done that is no longer
    # sitting in a final stage. There should be none on a database that has
    # never set state by hand, but a task moved back out under the old
    # behaviour would otherwise stay closed for ever.
    cr.execute("""
        UPDATE project_task
           SET state = '01_in_progress'
         WHERE state = '1_done'
           AND (stage_id IS NULL OR stage_id NOT IN %s)
    """, (final_ids,))
    reopened = cr.rowcount

    _logger.info(
        "Task state backfill: %s marked done, %s reopened.", closed, reopened)
