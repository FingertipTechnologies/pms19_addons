{
    'name': 'Project Customization',
    # 18.0.1.0.3 backfilled ft_completion_date for stages that are final by NAME
    # rather than by the Kanban fold flag.
    # 18.0.1.0.4 adds the rework-hours tracking: account.analytic.line.
    # ft_is_rework and project.task.ft_rework_hours are both STORED, so without
    # this bump their columns are never created and every read of them fails.
    'version': '19.0.1.0.5',
    'description': 'Project Customization.',
    'category': 'Project',
    'author': 'Broadtech',
    'depends': ['project','hr_timesheet','sale_timesheet'],
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
