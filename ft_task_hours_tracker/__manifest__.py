{
    'name': 'FT Task Hours Tracker',
    # Bumped off 18.0.0.0.0, where it had sat since the module was first added,
    # through every commit that introduced a new stored field. Odoo compares the
    # installed version against this one, so an unchanged version means a
    # database that already has the module never gains the new columns:
    # ft_project_stage_id (added in d7a9431 and referenced by the task list view)
    # has no column on any database that was not manually updated, and selecting
    # it raises UndefinedColumn. Bump this whenever a stored field is added here.
    # 18.0.0.0.2 adds the stored ft_is_trainee flag on account.analytic.line,
    # which powers the "Trainees" option in the Timesheets Group By menu.
    # 18.0.0.0.3 re-runs that flag's backfill: 18.0.0.0.2 shipped before any
    # employee had been mapped to a Trainee job position, so it had nothing to
    # flag and the grouping read zero.
    # 18.0.0.0.4 replaces that boolean with ft_trainee_id, so grouping lists
    # each trainee by name instead of Yes/No.
    # 18.0.0.0.5 claims an employee's past time for the Trainee group the
    # moment HR gives them a Trainee job position, instead of it needing a
    # manual backfill each time.
    # 18.0.0.0.6 drops the "None" bucket when grouping by Trainee — it held
    # everybody who is not a trainee, so it dominated both the group list and
    # the total hours.
    # 18.0.0.0.7 makes the 18.0.0.0.5 hook actually fire. Its backfill reads
    # hr_employee.job_id in raw SQL, which the ORM had not yet flushed when
    # hr.employee.write called it, so every catch-up stamped zero lines and a
    # trainee's history only appeared if an upgrade happened to sweep it. The
    # sweep is re-run here for anyone mapped while that was broken.
    'version': '19.0.0.0.8',
    'summary': 'project hours tracking',
    'category': 'Project',
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'project',
        'hr_timesheet',
        'bt_project_customization',
        'qa_testapp',
        'ft_sprint_management',
    ],
    'data': [
        'views/project_task_views.xml',
        'views/project_project_views.xml',
        'views/account_analytic_line_views.xml',
        'views/res_config_settings_views.xml',
    ],
'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
