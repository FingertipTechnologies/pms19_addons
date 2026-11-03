{
    'name': 'PMS Planning & Stage Workflow',
    # 19.0.1.21.0: task-level approval (Approve / Reject / Reset) is AMC-only;
    #   Implementation / General tasks are refused and the form hides it.
    # 19.0.1.22.0: AMC "To Approve" task filter lists only completed tasks.
    # 19.0.1.23.0: a timesheet reviewer may approve / reject their own lines
    #   (a PM logs time on their own project); the self-review block is gone.
    # 19.0.1.24.0: DISC deliverables (Schema Design, Components and Their
    #   Relationships, Process Flow Chart) + at least one module gate DISC ->
    #   DEV; the Code Review Document gates leaving SRV; at least one
    #   milestone is required to create an Implementation project and before
    #   every forward stage move; the form lists what the next move still needs.
    # 19.0.1.25.0: gate documents have a required file format: Schema Design,
    #   Components and Their Relationships and Code Review Document are Excel
    #   (.xlsx/.xls), the Process Flow Chart is PDF; wrong formats are refused.
    # 19.0.1.26.0: an overdue Implementation project cannot change stage at
    #   all (any direction, any user, admin included; sudo exempt) until a
    #   Date Extension is approved - on top of the task / timesheet lock; the
    #   form's "Missing for Next Stage" hint names the overdue reason first.
    # 19.0.1.27.0: timesheets can be reviewed from inside the task: the task
    #   form's Timesheets tab gets a per-line Approve / Reject / Reset button
    #   and "Approve All Pending" / "Reject All Pending" for the task (same
    #   rights and actions as the Timesheet Approvals list).
    # 19.0.1.28.0: SRV - Regression Sign-Off block of the project form shows
    #   its labels again (Current Status, Open Issues, Signed Off By, Signed
    #   Off On - lost when the Code Review group was nested inside it) and
    #   "Not signed off yet" while unsigned; the hint names who counts as QA
    #   (QA Group members or a tester job position).
    # 19.0.1.29.0: QA Group members get WRITE access on projects (access rule,
    #   no create / delete): the project form opens editable for them, so the
    #   SRV block's Current Status / Open Issues can be typed inline; the
    #   stage, lifecycle dates, finance clearances, lock and locked milestones
    #   stay guarded server-side.
    # 19.0.1.30.0: the Code Review Document gates ENTERING SRV (with the QA
    #   sign-off), no longer leaving it; the task list's Approve / Reject /
    #   Reset Approval buttons follow the selection; the Approved / Rejected
    #   task filters are AMC-only and stale approvals on non-AMC tasks are
    #   cleared.
    # 19.0.1.32.0: the paste button is on every screenshot evidence field
    #   (Sandbox Review, Customer UAT Sign-off, Internal / External / Google
    #   review), not only the Signed BRD one.
    # 19.0.1.31.0: the Signed BRD E-mail Screenshot field gets a small paste
    #   button (and Ctrl+V) next to the paperclip; a failed kanban quick create
    #   opens the full form with every value typed in the card, not just the name.
    'version': '19.0.1.32.0',
    'summary': 'Project Planner, weekly Task Planner, Avg. Daily Effort and '
               'gated project stage workflow with approvals and notifications.',
    'description': """
PMS Planning & Stage Workflow
=============================
* Project Planner: projects x days timeline coloured by effort
  (grey < 4h, yellow 4-<6h, green 6-8h, red > 8h), cumulative or employee-wise.
* Task Planner: weekly board (Weeks from ft_sprint_management), overdue /
  not started / working / completed ordering, estimated / open / completed
  totals, week moves with a mandatory reason that never change the deadline.
* Projects list: Estimated Time, Actual Hours, Avg. Daily Effort.
* Stage gates (Implementation projects): evidence per stage (DISC design
  documents, modules and a milestone before DEV; Code Review Document and
  QA REG sign-off before SRV), admin approval for UAT, closing
  feedback and retrospective. Gate documents have a required file format
  (Excel for the design documents and the code review, PDF for the process
  flow chart).

* Stage-change e-mails, project lock (overdue projects: tasks and timesheets
  locked and no stage change by anyone until a Date Extension is approved),
  Testing task type.
""",
    'category': 'Project',
    'author': 'Fingertip',
    'depends': [
        'project',
        'mail',
        'hr_timesheet',
        'sale_timesheet',
        'bt_project_customization',
        'ft_project_lifecycle',
        'ft_sprint_management',
        'ft_task_hours_tracker',
        'ft_customer_feedback',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/workflow_security.xml',
        'wizard/stage_approval_reject_views.xml',
        'views/task_week_move_views.xml',
        'views/project_project_list_views.xml',
        'views/project_stage_approval_views.xml',
        'views/project_project_workflow_views.xml',
        'views/res_config_settings_views.xml',
        'views/planner_menus.xml',
        'views/project_task_amc_approval_views.xml',
        'views/timesheet_approval_views.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_pms_planning_workflow/static/src/project_planner/multi_select.js',
            'ft_pms_planning_workflow/static/src/project_planner/multi_select.xml',
            'ft_pms_planning_workflow/static/src/project_planner/project_planner.js',
            'ft_pms_planning_workflow/static/src/project_planner/project_planner.xml',
            'ft_pms_planning_workflow/static/src/project_planner/project_planner.scss',
            'ft_pms_planning_workflow/static/src/task_planner/task_planner.js',
            'ft_pms_planning_workflow/static/src/task_planner/task_planner.xml',
            'ft_pms_planning_workflow/static/src/task_planner/task_planner.scss',
            'ft_pms_planning_workflow/static/src/control_panel_buttons/control_panel_buttons.js',
            'ft_pms_planning_workflow/static/src/control_panel_buttons/control_panel_buttons.xml',
            'ft_pms_planning_workflow/static/src/list_header_buttons/list_header_buttons.js',
            'ft_pms_planning_workflow/static/src/paste_attachment/paste_attachment_field.js',
            'ft_pms_planning_workflow/static/src/paste_attachment/paste_attachment_field.xml',
            'ft_pms_planning_workflow/static/src/kanban_quick_create/kanban_quick_create_patch.js',
        ],
    },
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
