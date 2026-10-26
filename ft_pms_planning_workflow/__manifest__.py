{
    'name': 'PMS Planning & Stage Workflow',
    # 19.0.1.21.0: task-level approval (Approve / Reject / Reset) is AMC-only;
    #   Implementation / General tasks are refused and the form hides it.
    # 19.0.1.22.0: AMC "To Approve" task filter lists only completed tasks.
    # 19.0.1.23.0: a timesheet reviewer may approve / reject their own lines
    #   (a PM logs time on their own project); the self-review block is gone.
    'version': '19.0.1.23.0',
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
* Stage gates (Implementation projects): evidence per stage, QA-only REG
  sign-off, admin approval for UAT, closing feedback and retrospective.
* Stage-change e-mails, project lock, Testing task type.
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
        ],
    },
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
