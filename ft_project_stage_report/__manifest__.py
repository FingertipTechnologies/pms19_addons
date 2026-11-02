{
    'name': 'FT Implementation Project Stage Report',
    # 19.0.1.0.0 first release:
    #   - ft.project.stage.line: one stored row per (Implementation project,
    #     Implementation stage) carrying the planned completion date, the
    #     actual entry / exit dates, Days Worked, Overdue Days and the
    #     Extension Days attributed to that stage by approved Date Extension
    #     Requests. Rebuilt on the project / request writes that change it,
    #     by a daily cron (days grow every day), on install, and on demand
    #     with the Refresh button of the report.
    #   - project.project.pl_total_extension_days: stored sum of the Delay
    #     Days of the project's approved requests ("Total Extension Days"
    #     in the Actual Stage Dates group of the form), plus a "Stage
    #     Report" smart button.
    #   - Menu Project > Implementation Report > Days Worked / Overdue &
    #     Delays: the same list / pivot / graph with different default
    #     measures.
    # 19.0.1.1.0: the three menus are gone. The table now lives INSIDE the
    #   Project Dashboard (ft_project_dashboard, Dashboards > Project) as the
    #   "Implementation Stages" section, after Project Performance, with the
    #   Days Worked / Overdue-Delays choice as a switch in the table itself
    #   (OWL component ImplementationStageTable fed by
    #   ft.project.stage.line.get_dashboard_rows). The two act_window actions
    #   stay for the project form's Stage Report smart button.
    # 19.0.1.2.0: the dashboard table is a matrix (one row per project, one
    #   column per stage, Days Worked / Overdue Days switch, summary strip)
    #   fed by get_dashboard_matrix; get_dashboard_rows stays for lists.
    # 19.0.1.3.0: Planned Date is the date the project must REACH the stage
    #   by (project_date_extension's remapped STAGE_PLANNED_DATE_FIELD, the
    #   same-named date on the project form, after approved extensions);
    #   Overdue Days = entry - planned for reached stages, today - planned
    #   for the next stage not yet reached only.
    # 19.0.1.4.0: the approved Date Extension days of a stage ARE its delay:
    #   Overdue Days = Extension Days + the days still missed after the
    #   extension (entry - extended planned date / today - it for the next
    #   unreached stage). A stage extended by 10 days and then reached on the
    #   extended date shows 10 overdue, not 0. Stored lines are rebuilt by
    #   the migration.
    # 19.0.1.5.0: Overdue Days = Extension Days only. The days missed against
    #   the planned date are no longer added; a stage without an approved
    #   Date Extension is never overdue. Stored lines rebuilt by migration.
    'version': '19.0.1.5.0',
    'summary': 'Stage-wise Days Worked, Overdue Days and Extension Days '
               'report for Implementation projects.',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'bt_project_customization',
        'ft_project_lifecycle',
        'project_date_extension',
        'ft_project_stage_dates',
        # The stage table is rendered inside ft_project_dashboard's board and
        # reuses its DataTable component and ftpd_* styles; being a dependency
        # also guarantees our assets load after the dashboard's.
        'ft_project_dashboard',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/stage_line_views.xml',
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_project_stage_report/static/src/js/implementation_stage_table.js',
            'ft_project_stage_report/static/src/xml/implementation_stage_table.xml',
            'ft_project_stage_report/static/src/scss/implementation_stage_table.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
