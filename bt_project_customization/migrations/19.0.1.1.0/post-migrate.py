"""Seed the per-project module configuration from the pairings already in use.

``cus.module.project_ids`` was a stored COMPUTED field (the projects of the
module's tasks) and is now the editable configuration that the Module field on
a task is filtered against. The relation table is unchanged, so every row the
compute had written survives the switch — this only closes the gap the compute
had left open.

That gap is real but small: the compute fires on ``task_ids.project_id``, and a
task whose project was changed by a path that did not invalidate the module's
cache leaves the pairing unrecorded. On this database exactly one task was in
that state. Without this backfill its module would vanish from its own project's
dropdown the moment anyone opened the task.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        INSERT INTO cus_module_project_project_rel (cus_module_id, project_project_id)
        SELECT DISTINCT t.module_id, t.project_id
        FROM project_task t
        WHERE t.module_id IS NOT NULL
          AND t.project_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)
