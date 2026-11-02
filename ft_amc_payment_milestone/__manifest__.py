# -*- coding: utf-8 -*-
{
    'name': 'AMC Payment Milestones',
    # 19.0.1.0.0 first release (requirements 36-50 of the PMS spec):
    #   - One payment milestone per calendar month for every AMC project,
    #     created automatically on the 1st (daily cron, idempotent) whether or
    #     not any AMC work was done that month, on the existing
    #     project.custom.milestone model (Milestones tab + central menu).
    #   - Extra statuses (Internally Approved before Completed, Customer
    #     Approved after it); the sequence is enforced for AMC monthly
    #     milestones only.
    #   - "Deployed" task status (bulk action, PM/TL/admin only). A task that
    #     is AMC-approved, in a final stage and Deployed is attached to the
    #     milestone of the month it was deployed in; ALL of its approved hours
    #     count there.
    #   - Completed = the monthly timesheet e-mail has been sent (per-milestone
    #     send switch); sent automatically on the 7th (configurable) for the
    #     previous month. The day-5 report cron no longer mails months that
    #     have a milestone.
    # 19.0.1.1.0 (clarified requirement; migration included):
    #   - Naming: "Support Services for <Month YYYY>" / "SS-YYYY-MM" (existing
    #     milestones renamed by the post-migration).
    #   - Statuses: Not Started, Completed, Client Approved, Invoice Raised,
    #     Part Paid, Paid. The internal approval step is gone (pre-migration
    #     resets internal_approved rows to not_started and drops the old
    #     "awaiting internal approval" To-Dos); customer_approved is relabelled
    #     "Client Approved", partially_paid "Part Paid" (keys unchanged).
    #   - Day-7 cron completes (= sends) the Not Started milestones of the
    #     months that are over whose send switch is on; no reminders.
    #   - Approved Hours = APPROVED timesheet lines only (weekly timesheet
    #     approval), per task helper _ft_amc_approved_hours().
    #   - Task Excel (task, stage, deployed on, approved by, approved hours,
    #     billable hours, total) generated on Completed and by a button,
    #     attached to the milestone and added to the customer e-mail.
    #   - Milestones tab shows Name, Hours, Status only for AMC projects.
    # 19.0.1.2.0 (decision: "after completed, deploy status should be added;
    # deploy is different from completed"; migration included):
    #   - Deployed is a value of the task's standard Status (`state`), right
    #     after Done: '1_deployed', registered as a CLOSED state (is_closed,
    #     Open / Closed filters, subtask counters, dependencies, rotting all
    #     treat it like Done). ft_deployed stays the source of truth: Mark
    #     Deployed -> 1_deployed, Undo -> 1_done, reopen -> 01_in_progress.
    #     The Status widget cannot set Deployed (buttons only, rights check);
    #     moving a deployed task to another status undoes the deployment
    #     through the same rules. Status widget shows a cloud icon for it.
    #   - post-migration: tasks with ft_deployed get state = '1_deployed'.
    # 19.0.1.2.1: creating / saving a task from the form no longer fails with
    #   "The deployment status ... cannot be edited directly": the form sends
    #   the deployment fields back with their default (False); only a set or
    #   changed value is refused.
    'version': '19.0.1.2.1',
    'summary': 'Monthly "Support Services" payment milestones for AMC projects: client '
               'approval / invoice / payment statuses, Deployed task status, approved-hours '
               'task Excel and milestone-driven customer e-mail.',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project_custom_milestone',
        'qa_testapp',
        'project_date_extension',
        'ft_amc_monthly_timesheet',
        'ft_pms_planning_workflow',
        'bt_project_customization',
        'ft_task_hours_tracker',
        'ft_project_lifecycle',
        'mail',
    ],
    'data': [
        'data/ir_cron_data.xml',
        'views/project_milestone_views.xml',
        'views/project_project_views.xml',
        'views/project_task_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # Patches project's ProjectTaskStateSelection (icon / colours of
            # the Deployed status); loads after project's own assets through
            # the module dependency.
            'ft_amc_payment_milestone/static/src/js/task_state_deployed.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
