"""Take the Stage Owner back off the four PMS task stages.

WHY THEY HAVE ONE

``project.task.type.user_id`` is "Stage Owner", and it carries a default::

    def _default_user_id(self):
        return not self.env.context.get('default_project_id', False) and self.env.uid

The four stages in ``data/task_stages.xml`` are global on purpose — they set no
``project_ids`` so that every project can share them — so nothing puts a
``default_project_id`` in context when they are created and the default stamps
whichever uid loaded the module. On a module install that is OdooBot, id 1.

``_compute_user_id`` is stored and depends on ``project_ids``, and it only
clears the owner for stages that HAVE projects::

    self.sudo().filtered('project_ids').user_id = False

These four never do, so nothing ever took it back off.

WHY IT BREAKS THE PMS

A stage with an owner is a PERSONAL stage — a column in one person's My Tasks
kanban — and core protects it with a rule that has no ``groups``, which makes
it global: ANDed into every user's access, Administrators and project managers
included (``project.task_type_visibility_rule``)::

    [('user_id', 'in', (False, user.id))]

Owned by OdooBot, the four were therefore unreadable by every real user, and
any task sitting in one could not be read either — the web client resolves the
stage's display name and gets

    Sorry, Administrator (id=2) doesn't have 'read' access to
    - Task Stage, Completed (project.task.type: 2191)

The 19.0.4.3.0 merge is what made it general: it moves the tasks of every
duplicate stage onto exactly these four rows, so work that had been sitting in
readable per-project copies landed in an unreadable one.

WHAT THIS DOES

Clears ``user_id`` on the four, by xmlid — never by name, which would catch a
person who genuinely has a personal stage called Planned and empty their My
Tasks column into the shared workflow.

Raw SQL because ``user_id`` is a stored computed field: an ORM write is
overwritten by ``_compute_user_id`` on the next recompute of a row that has no
``project_ids`` to satisfy its filter, and there is no recompute to trigger
here — the column just has to stop holding a uid.
"""

import logging

_logger = logging.getLogger(__name__)

CANONICAL_XMLIDS = (
    'task_stage_planned',
    'task_stage_working',
    'task_stage_testing',
    'task_stage_completed',
)


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = 'ft_sprint_management'
           AND model = 'project.task.type'
           AND name IN %s
    """, (CANONICAL_XMLIDS,))
    stage_ids = tuple(row[0] for row in cr.fetchall())
    if not stage_ids:
        _logger.warning(
            "None of the four canonical task stages were found; no stage "
            "owner to clear.")
        return

    cr.execute("""
        UPDATE project_task_type
           SET user_id = NULL
         WHERE id IN %s
           AND user_id IS NOT NULL
    """, (stage_ids,))
    cleared = cr.rowcount

    # A personal stage is also a column in somebody's My Tasks board, joined
    # to their tasks through project_task_user_rel. Those rows named a stage
    # that is about to stop being personal, so they would leave tasks pointing
    # at a column that no longer exists on anyone's board.
    cr.execute(
        "DELETE FROM project_task_user_rel WHERE stage_id IN %s", (stage_ids,))
    dropped = cr.rowcount

    _logger.info(
        "Cleared the Stage Owner on %s of the four PMS task stages (%s "
        "personal-stage row(s) dropped); they are readable by every user "
        "again.", cleared, dropped)
