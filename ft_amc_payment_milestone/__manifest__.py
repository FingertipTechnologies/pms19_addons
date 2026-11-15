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
    # 19.0.1.3.0: labels only - the Deployed status and its fields, buttons,
    #   filters and menu read "Billable" (Mark / Undo Billable, To Bill, AMC
    #   Tasks to Bill). Technical values (1_deployed, ft_deployed*) unchanged,
    #   no migration.
    # 19.0.1.4.0: Mark Billable requires the task to be AMC-approved (rule
    #   + form button); on the All Tasks list, Mark Billable hides when every
    #   selected task is already Billable and Undo Billable hides when none is.
    # 19.0.1.5.0 (decision: "for the amc timesheets/task and milestone sending
    # automatically, both keep as one schedule action. both should be sent at a
    # time"; migration included):
    #   - ONE scheduled action, "AMC: Send Monthly Timesheets & Milestones"
    #     (ir_cron_ft_amc_send_monthly, daily, project.custom.milestone
    #     ._cron_ft_amc_send_monthly), runs ft_amc_monthly_timesheet's report
    #     send and then the milestone send in the same run, each in its own
    #     savepoint (a failure of one is logged, the other still runs).
    #   - One send day for both: the existing "Milestone E-mail Day" setting
    #     (ft_amc_payment_milestone.send_day, default 7) is relabelled
    #     "Monthly E-mail Day"; ft.amc.monthly.report._send_from_day() is
    #     overridden to read it, so the reports no longer go out on the 5th.
    #   - post-migration: the former "AMC: Send Monthly Milestone Timesheets"
    #     cron (ir_cron_ft_amc_send_monthly_milestones) is deleted and
    #     ft_amc_monthly_timesheet's "AMC: Send Monthly Timesheet Reports"
    #     (cron_amc_monthly_reports) is archived; the install hook archives it
    #     on a fresh install and the new uninstall hook restores it.
    #     Requires ft_amc_monthly_timesheet >= 19.0.2.2.0 (_send_from_day).
    # 19.0.1.6.0 (feedback: Scheduled Actions still listed two AMC crons,
    # "Create Monthly Payment Milestones" and "Send Monthly Timesheets &
    # Milestones" - "both keep as one schedule action"; migration included):
    #   - ONE scheduled action for the whole AMC monthly automation:
    #     "AMC: Monthly Milestones & Timesheets" (ir_cron_ft_amc_monthly,
    #     daily, project.custom.milestone._cron_ft_amc_monthly) runs, in
    #     order, each step in its own savepoint (a failure is logged, the next
    #     steps still run): 1. create the current month's milestones
    #     (project.project._cron_ft_amc_create_monthly_milestones - effective
    #     on the 1st, no-op later), 2. send the previous month's timesheet /
    #     task reports (ft.amc.monthly.report._cron_send_monthly_reports),
    #     3. send the milestones (_cron_ft_amc_send_monthly_milestones) -
    #     2 and 3 from the Monthly E-mail Day (default 7). The three step
    #     methods are unchanged and still callable on their own; the
    #     19.0.1.5.0 _cron_ft_amc_send_monthly is replaced by
    #     _cron_ft_amc_monthly (+ _cron_ft_amc_monthly_steps).
    #   - post-migration: "AMC: Create Monthly Payment Milestones"
    #     (ir_cron_ft_amc_create_monthly_milestones) and "AMC: Send Monthly
    #     Timesheets & Milestones" (ir_cron_ft_amc_send_monthly) are deleted
    #     with their xmlids (and, as a safety net for a database that skipped
    #     19.0.1.5.0, ir_cron_ft_amc_send_monthly_milestones); the new cron is
    #     created by the data update; ft_amc_monthly_timesheet's report cron
    #     stays archived (restored on uninstall).
    'version': '19.0.1.6.0',
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
            # Adds the ft_billable_selection summary to the list header
            # button context (hook of ft_pms_planning_workflow).
            'ft_amc_payment_milestone/static/src/js/list_header_billable.js',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
}
