"""Merge the duplicate task stages back into the four the PMS runs on.

WHY THERE ARE DUPLICATES

``project.task.type`` is not a global list. Stages are linked to projects
through the ``project_task_type_rel`` many2many, so "Planned" is not one row
the whole database shares — it is one row per set of projects that happen to
have been given a stage list together. Three things create them:

1. ``ft_sprint_management/data/task_stages.xml`` creates the four canonical
   rows: Planned, Working, Testing, Completed.
2. ``project_task_default_stage`` (OCA) puts a ``case_default`` flag on the
   stage and defaults ``project.project.type_ids`` to every stage carrying it.
   Its own data file ships eight — Analysis, Specification, Design,
   Development, Testing, Merge, Done, Cancelled — seven of them case_default.
   So EVERY new project silently arrives with those stages attached, including
   a second Testing.
3. Odoo core's ``project.project.name_create`` creates a stage named "New" for
   any project made on the fly (typing a project name into a task's Project
   field, for instance). Anyone adding a column in a project's task Kanban
   creates one more.

None of those paths reuses an existing row by name, so a PMS accumulates
several distinct stages all called Planned. The Week board searched those four
names across every project and drew a column per ROW, which is why the board
showed Planned twice — the second one usually empty, because the projects it
belongs to had nothing due that week.

WHAT THIS DOES

For each of the four canonical names, keep the ``ft_sprint_management`` record
and fold every other stage of the same name into it: move the tasks, move the
project links, then delete the row now that nothing points at it.

It does NOT touch stages under any other name. "Analysis", "Planned-2" and the
rest are somebody's real stage set with real tasks in them, and deciding which
of the four each should become is a business call, not a migration's. They are
listed in the log so they can be dealt with deliberately.

Personal stages are excluded throughout. A ``project.task.type`` with
``user_id`` set is a column in one person's My Tasks kanban, not part of the
delivery workflow, and merging those would rearrange people's private boards.

Raw SQL on purpose: ``project.task.type.write`` archives every task in a stage
when ``active`` goes false and drags stage-change tracking along, and
``unlink`` opens an interactive wizard asking where the tasks should go. This
has already answered that question.
"""

import logging

_logger = logging.getLogger(__name__)

CANONICAL_XMLIDS = (
    ('Planned', 'ft_sprint_management.task_stage_planned'),
    ('Working', 'ft_sprint_management.task_stage_working'),
    ('Testing', 'ft_sprint_management.task_stage_testing'),
    ('Completed', 'ft_sprint_management.task_stage_completed'),
)


def _stage_id_for_xmlid(cr, xmlid):
    module, name = xmlid.split('.')
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND name = %s AND model = 'project.task.type'
    """, (module, name))
    row = cr.fetchone()
    return row[0] if row else None


def migrate(cr, version):
    if not version:
        return

    merged_stages = moved_tasks = 0

    for stage_name, xmlid in CANONICAL_XMLIDS:
        keep_id = _stage_id_for_xmlid(cr, xmlid)
        if not keep_id:
            _logger.warning(
                "Canonical stage %s (%s) is missing; leaving its duplicates "
                "alone.", stage_name, xmlid)
            continue

        # The name column is translated jsonb, so it is matched on its en_US
        # value the same way the board's own name lookup does.
        cr.execute("""
            SELECT id FROM project_task_type
             WHERE name->>'en_US' = %s
               AND id != %s
               AND user_id IS NULL
        """, (stage_name, keep_id))
        duplicate_ids = tuple(row[0] for row in cr.fetchall())
        if not duplicate_ids:
            continue

        cr.execute(
            "UPDATE project_task SET stage_id = %s WHERE stage_id IN %s",
            (keep_id, duplicate_ids),
        )
        moved_tasks += cr.rowcount

        # Give the canonical stage every project the duplicates served, so the
        # projects that were using a copy keep a stage of that name on their
        # own kanban. ON CONFLICT covers a project already linked to both.
        cr.execute("""
            INSERT INTO project_task_type_rel (type_id, project_id)
            SELECT DISTINCT %s, rel.project_id
              FROM project_task_type_rel rel
             WHERE rel.type_id IN %s
               AND NOT EXISTS (
                   SELECT 1 FROM project_task_type_rel kept
                    WHERE kept.type_id = %s
                      AND kept.project_id = rel.project_id
               )
        """, (keep_id, duplicate_ids, keep_id))
        cr.execute(
            "DELETE FROM project_task_type_rel WHERE type_id IN %s",
            (duplicate_ids,),
        )

        # Personal-stage rows on tasks point at stage records too.
        cr.execute("""
            DELETE FROM project_task_user_rel WHERE stage_id IN %s
        """, (duplicate_ids,))

        cr.execute(
            "DELETE FROM ir_model_data WHERE model = 'project.task.type' "
            "AND res_id IN %s", (duplicate_ids,))
        cr.execute("DELETE FROM project_task_type WHERE id IN %s", (duplicate_ids,))
        merged_stages += len(duplicate_ids)
        _logger.info(
            "Merged %s duplicate '%s' stage(s) into %s.",
            len(duplicate_ids), stage_name, keep_id)

    # Everything still outside the four, so it can be dealt with by hand.
    cr.execute("""
        SELECT s.name->>'en_US', count(t.id)
          FROM project_task_type s
          LEFT JOIN project_task t ON t.stage_id = s.id
         WHERE s.user_id IS NULL
           AND s.name->>'en_US' NOT IN %s
      GROUP BY 1
      ORDER BY 2 DESC
    """, (tuple(name for name, _ in CANONICAL_XMLIDS),))
    leftovers = cr.fetchall()

    _logger.info(
        "Week stage merge: %s duplicate stage(s) removed, %s task(s) moved.",
        merged_stages, moved_tasks)
    if leftovers:
        _logger.warning(
            "Task stages outside the PMS four are still in use and were NOT "
            "touched — decide per stage which of the four it should become, "
            "then move its tasks: %s",
            ", ".join(f"{name} ({count} task(s))" for name, count in leftovers),
        )
