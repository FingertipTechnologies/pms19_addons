{
    'name': 'Project Customization',
    # 18.0.1.0.3 backfilled ft_completion_date for stages that are final by NAME
    # rather than by the Kanban fold flag.
    # 18.0.1.0.4 adds the rework-hours tracking: account.analytic.line.
    # ft_is_rework and project.task.ft_rework_hours are both STORED, so without
    # this bump their columns are never created and every read of them fails.
    # 19.0.1.1.0 turns cus.module.project_ids into the per-project module
    # configuration (was computed from tasks), filters the task's Module field
    # against it, adds project.task.task_source defaulted from the project
    # stage, scopes the Estimated requirement to tasks that have a project, and
    # limits a User Story to one assignee.
    # 19.0.1.2.0 combines that work with task workflow controls, source
    # evidence, deadline auditing and work/completion tracking.
    # 19.0.1.3.0 adds project.project.ft_project_type (Implementation / AMC /
    # General) and backfills it. The field is required, so the bump is what
    # creates the column and stamps the default on every existing row; the
    # migration then corrects the AMC and General ones.
    # 19.0.1.4.0 makes the Task Source bands survive ft_project_lifecycle:
    # the Discovery/UAT boundaries now ignore archived stages and accept the
    # new DISC name, and AMC/General projects state their source outright
    # instead of deriving it from a lifecycle they do not use. The "Planned
    # only in Discovery" rule matches the same stage-name list, so it accepts
    # DISC too.
    # 19.0.1.5.0 adds Enhancement as a fourth Task Source. Manual-only: no
    # project stage maps to it, and it carries no supporting-evidence rule.
    # 19.0.1.6.0 tightens four rules and defines none of them with a new
    # column, so this bump is only for tracking:
    #   - Enhancement now requires the same customer portal Ticket as a Change
    #     Request (TICKET_REQUIRED_SOURCES).
    #   - AMC projects no longer default their tasks to Change Request. That
    #     value was an artefact of the old pipeline's stage order and made
    #     every maintenance task demand a portal ticket. The AMC rule is not
    #     yet defined, so the default is now empty and a person chooses.
    #   - Work Start Date is the FIRST entry to Working, not the most recent;
    #     Work End Date is the LAST completion and is no longer blanked when a
    #     task is reopened. Together they span the whole life of the work.
    #   - The 24-hour minimum Deadline applies to User Story tasks rather than
    #     to Planned/Unplanned ones, and "Number of Deadline Changes" is
    #     relabelled "#Deadline Changes".
    # 19.0.1.7.0 relabels those two dates to say what 19.0.1.6.0 made them do:
    # Work Start Date -> "First Time", Work End Date -> "Last Time". Labels
    # only — the ft_work_start_date / ft_work_end_date columns, their values
    # and their stamping rules are all untouched, so the bump is for the label
    # to reach an existing database and for tracking.
    # 19.0.1.8.0 adds the project-level Stage Validation Framework. Movement of
    # project.project through its Kanban stages (stage_id) is gated on required
    # milestone dates: Kick-off before DISC, BRD Approval before DEV, Regression
    # before SRV, Sandbox Review before UAT, UAT Start before DATA, Training
    # before TRA, Support Start before SUPPORT, and Go Live before AMC/CLOSED
    # (HOLD is unrestricted). A move with the date missing is blocked with a
    # clear message, on the Kanban drag as well as the form. Two new optional
    # Date columns back it — ft_regression_date and ft_training_date — created
    # on this update; no migration is needed as nothing reads them until set.
    # It also adds the Overdue signal (ft_is_overdue / ft_overdue_reason,
    # computed, unstored): a project whose milestone date has passed while it
    # still sits short of the stage that date gates is flagged Overdue on the
    # Kanban card, the list and the form, with an Overdue search filter.
    # 19.0.1.9.0 drops the 'implementation' default from ft_project_type and
    # puts the field on the two project-creation dialogs (the kanban's "Create
    # a Project" popup and the in-column quick create). The field stays
    # required, so the type is now chosen at creation instead of being
    # inherited silently. No migration: every existing row already holds a
    # value, and a default only ever affected new records.
    # 19.0.1.10.0 moves project modules and stage-wise time into the optional
    # ft_project_module_tracking addon, with metadata preserved on upgrade.
    'version': '19.0.1.10.0',
    'description': 'Project Customization.',
    'category': 'Project',
    'author': 'Broadtech',
    'depends': ['project', 'hr_timesheet', 'sale_timesheet', 'ft_helpdesk_core'],
    'data': [
        'security/ir.model.access.csv',
        'security/project_timesheet_group.xml',
        'views/project_project_views.xml',
        'views/project_milestone_views.xml',
        'views/project_task_views.xml',
        'views/module_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'bt_project_customization/static/src/js/task_stage_confirm.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
