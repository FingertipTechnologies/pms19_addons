{
    'name': 'Project Lifecycle',
    # 19.0.1.4.0 follows bt_project_customization dropping the ft_project_type
    # default: create() no longer reads the type from default_get, and only
    # homes a new project onto a stage once the type is actually known. It also
    # fixes the Start Date backfill, which had never written a single row:
    # core's project write silently drops a lone date_start when the project has
    # no End Date, so the ORM loop in hooks.backfill_start_dates was a no-op on
    # exactly the projects it existed for. It is SQL now, and runs on every
    # upgrade rather than only on install, so databases that installed the
    # broken version get their Start Dates filled in.
    # 19.0.1.5.0 drops pl_regression_date/pl_training_date in favour of
    # bt_project_customization's ft_regression_date/ft_training_date: the two
    # pairs shared a label ("Regression Date" / "Training Date") on the
    # project form, so a project could show a date under one and still get
    # blocked by Stage Validation checking the other.
    # 19.0.1.6.0 finishes the stage migration on databases that installed this
    # module while bt_project_customization was leaving Project Types NULL.
    # An untyped project matched no arm of the stage mapping, so it stayed on
    # the old pipeline, and the move then refused to archive any old
    # stage while one was still occupied — leaving both pipelines on the Kanban
    # with drained stages (General, AMC) as empty columns nobody could clear.
    # The 0.0.0 post-migrate now re-runs the move once bt's 19.0.1.11.0 has
    # filled the types, so each project keeps its place in the flow, and the old
    # stages retire themselves. The Kanban's stage columns are expanded by
    # _pl_read_group_stage_ids rather than core's "every active stage", so a
    # drained stage stops drawing a column while an occupied one always draws
    # one.
    # 19.0.2.0.0 replaces "create new stages and move every project onto them"
    # with adoption: the lifecycle xmlids are re-pointed at the stages that
    # already exist, which are then renamed to their abbreviations (Discovery ->
    # DISC, Development -> DEV, ...) and given the sequence and type flags. A
    # project's stage_id is not touched, so nothing changes phase and the stage
    # history stays intact. The previous approach moved 76 projects that had not
    # actually progressed. Only two kinds of project move now: those on a stage
    # merged into another (Sandbox Testing into SRV), and active
    # non-Implementation projects sitting on an Implementation-only stage, which
    # go to the shared Working (AMC/General) column. HOLD and AMC are Kanban
    # stages again, per the requirement; REG is created empty after DEV, and
    # Production Testing and Deployment are kept exactly as they are.
    # 19.0.2.1.0 retires the AMC stage. AMC is a Project Type, not a workflow
    # step — AMC projects run Started -> Working (AMC/General) -> Completed, the
    # same as General ones — so the stage never received a project and drew a
    # permanently empty Kanban column. Archived, flags cleared, xmlid dropped;
    # not deleted, because seven tables reference project.project.stage.
    'version': '19.0.2.1.0',
    'summary': 'Project Type, project-level lifecycle stages and milestone dates.',
    'description': """
Project Lifecycle
=================
Drives a project-level Kanban stage workflow off the project's Project Type:

* Implementation: DISC -> DEV -> REG -> SRV -> UAT -> DATA -> TRA -> SUPPORT
* AMC: Started -> Working -> Completed
* General: Started -> Working -> Completed

The Project Type itself is bt_project_customization's ft_project_type field.
CLOSED is a shared terminal stage; being parked is the On Hold checkbox on
the project form rather than a stage. Milestone dates, an auto-filled
Start Date (from the creation date) and a Closed Date (the renamed project End
Date) round out the form. A Kanban card arrow opens the project form directly.
""",
    'category': 'Project',
    'author': 'Fingertip',
    # bt_project_customization owns the Project Type field (ft_project_type)
    # this module's stage rules read, so it must load first.
    'depends': ['project', 'ft_task_hours_tracker', 'bt_project_customization'],
    'data': [
        'security/project_lifecycle_security.xml',
        'data/project_project_stage_data.xml',
        'views/project_project_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
