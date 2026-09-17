"""Leave the PMS with exactly four task stages: Planned, Working, Testing and
Completed.

19.0.4.3.0 merged the stages that shared one of those four names and listed
everything else in the log to be decided by hand. This is that decision:

* a stage with "Sandbox Review" or "Testing" anywhere in its name (Sandbox
  Review, UAT Testing, Sandbox Testing, ...) becomes Testing;
* a stage that IS one of the four under another case or with stray spaces
  ("completed ", "PLANNED") becomes that stage;
* every other stage — Analysis, Development, Merge, Done, Cancelled,
  Dependency, New, Post sales and the rest — becomes Working.

The tasks in each are moved to their stage, every project is linked to the four
and to nothing else, and the old stages are removed: deleted outright, or
archived when a module ships them as data (project_task_default_stage's eight),
because a noupdate record whose row is gone is created again on that module's
next upgrade. Archiving also takes them out of that module's "default for new
projects" search.

Personal stages are left alone. A project.task.type with user_id set is a
column in one person's My Tasks board, not part of the delivery workflow. The
one exception is a project task whose stage_id points at such a row: the task
is moved like any other, the column stays.

Raw SQL for the moves, for the same reasons as 19.0.4.3.0: project.task.write
runs the User Story workflow guards, the rework counters and stage tracking,
and project.task.type.unlink asks through a wizard where the tasks should go.
Only date_end is set the way core would set it — cleared when the task lands in
a stage that is not folded. date_last_stage_update is kept, so the whole
backlog does not read as having changed stage on the day of the upgrade.

An END script rather than a post script because the stored fields computed off
the stage (task state, the completion date, anything another module adds) have
to be recomputed after the SQL, and only at the end stage has every installed
module's model been loaded.
"""

import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

PLANNED = 'task_stage_planned'
WORKING = 'task_stage_working'
TESTING = 'task_stage_testing'
COMPLETED = 'task_stage_completed'
CANONICAL_XMLIDS = (PLANNED, WORKING, TESTING, COMPLETED)

SAME_NAME = {
    'planned': PLANNED,
    'working': WORKING,
    'testing': TESTING,
    'completed': COMPLETED,
}
TESTING_NAME_RE = re.compile(r'sandbox\W*review|testing')


def _target_xmlid(names):
    """The PMS stage for a stage carrying ``names`` (one per translation)."""
    normalised = [' '.join((name or '').split()).lower() for name in names]
    for name in normalised:
        if name in SAME_NAME:
            return SAME_NAME[name]
    if any(TESTING_NAME_RE.search(name) for name in normalised):
        return TESTING
    return WORKING


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        SELECT name, res_id FROM ir_model_data
         WHERE module = 'ft_sprint_management'
           AND model = 'project.task.type'
           AND name IN %s
    """, (CANONICAL_XMLIDS,))
    pms_ids = dict(cr.fetchall())
    missing = set(CANONICAL_XMLIDS) - set(pms_ids)
    if missing:
        _logger.warning(
            "PMS task stage(s) %s are missing; leaving every other stage and "
            "its tasks untouched.", ", ".join(sorted(missing)))
        return
    keep_ids = tuple(pms_ids.values())

    cr.execute(
        "SELECT id, fold FROM project_task_type WHERE id IN %s", (keep_ids,))
    folded = dict(cr.fetchall())

    # Stages to retire: every shared stage outside the four.
    cr.execute("""
        SELECT id FROM project_task_type
         WHERE id NOT IN %s AND user_id IS NULL
    """, (keep_ids,))
    retire_ids = tuple(row[0] for row in cr.fetchall())

    # Stages to empty: those, plus any personal stage a project task sits in.
    cr.execute("""
        SELECT s.id, s.name
          FROM project_task_type s
         WHERE s.id NOT IN %s
           AND (s.user_id IS NULL
                OR EXISTS (SELECT 1 FROM project_task t
                            WHERE t.stage_id = s.id
                              AND t.project_id IS NOT NULL))
    """, (keep_ids,))
    by_target = {}
    for stage_id, name in cr.fetchall():
        # name is translated jsonb, so every language's value is looked at.
        names = list((name or {}).values())
        by_target.setdefault(_target_xmlid(names), []).append(
            (stage_id, (name or {}).get('en_US') or next(iter(names), '')))

    moved_task_ids = []
    for xmlid, stages in by_target.items():
        target_id = pms_ids[xmlid]
        cr.execute("""
            UPDATE project_task t
               SET stage_id = %s,
                   date_end = CASE WHEN %s THEN t.date_end END
              FROM project_task_type s
             WHERE t.stage_id = s.id
               AND s.id IN %s
               AND (s.user_id IS NULL OR t.project_id IS NOT NULL)
         RETURNING t.id
        """, (target_id, folded[target_id], tuple(sid for sid, _ in stages)))
        ids = [row[0] for row in cr.fetchall()]
        moved_task_ids += ids
        _logger.info(
            "Moved %s task(s) into %s from: %s", len(ids), xmlid,
            ", ".join(sorted({name for _, name in stages})))

    # Every project runs on the four and on nothing else.
    if retire_ids:
        cr.execute(
            "DELETE FROM project_task_type_rel WHERE type_id IN %s", (retire_ids,))
        cr.execute(
            "DELETE FROM project_task_user_rel WHERE stage_id IN %s", (retire_ids,))
    cr.execute("""
        INSERT INTO project_task_type_rel (type_id, project_id)
        SELECT k.id, p.id
          FROM project_project p
         CROSS JOIN unnest(%s::int[]) AS k(id)
         WHERE NOT EXISTS (
               SELECT 1 FROM project_task_type_rel rel
                WHERE rel.type_id = k.id AND rel.project_id = p.id)
    """, (list(keep_ids),))
    linked = cr.rowcount

    archived = deleted = 0
    if retire_ids:
        cr.execute("""
            SELECT DISTINCT res_id FROM ir_model_data
             WHERE model = 'project.task.type'
               AND res_id IN %s
               AND left(module, 2) != '__'
        """, (retire_ids,))
        shipped_ids = tuple(row[0] for row in cr.fetchall())
        if shipped_ids:
            cr.execute(
                "UPDATE project_task_type SET active = FALSE WHERE id IN %s",
                (shipped_ids,))
            cr.execute("""
                SELECT 1 FROM information_schema.columns
                 WHERE table_name = 'project_task_type'
                   AND column_name = 'case_default'
            """)
            if cr.fetchone():
                cr.execute(
                    "UPDATE project_task_type SET case_default = FALSE "
                    "WHERE id IN %s", (shipped_ids,))
            archived = len(shipped_ids)

        delete_ids = tuple(set(retire_ids) - set(shipped_ids))
        if delete_ids:
            cr.execute(
                "DELETE FROM ir_model_data WHERE model = 'project.task.type' "
                "AND res_id IN %s", (delete_ids,))
            cr.execute(
                "DELETE FROM project_task_type WHERE id IN %s", (delete_ids,))
            deleted = len(delete_ids)

    if moved_task_ids:
        env = api.Environment(cr, SUPERUSER_ID, {})
        env.invalidate_all()
        Task = env['project.task'].with_context(active_test=False)
        tasks = Task.browse(moved_task_ids)
        field_depends = env.registry.field_depends
        for field in Task._fields.values():
            if not (field.store and field.compute) or field.name == 'stage_id':
                continue
            if any(dep in ('stage_id', 'date_end') or dep.startswith('stage_id.')
                   for dep in field_depends[field]):
                env.add_to_compute(field, tasks)
        env.flush_all()

    _logger.info(
        "PMS task stages reduced to the four: %s task(s) moved, %s stage(s) "
        "deleted, %s archived, %s project link(s) added.",
        len(moved_task_ids), deleted, archived, linked)
