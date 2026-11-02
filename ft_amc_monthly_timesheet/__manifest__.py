{
    'name': 'FT AMC Monthly Timesheet',
    # 19.0.2.1.0: the project tab's "Generate" opens a month picker (wizard)
    #   instead of always building the previous calendar month, which a
    #   contract that started this month does not cover.
    'version': '19.0.2.1.0',
    'license': 'LGPL-3',
    'category': 'Services/Timesheets',
    'summary': 'Monthly PDF/Excel timesheet report of approved AMC tasks, emailed to the customer',
    'depends': [
        'mail',
        'hr_timesheet',
        'project',
        'bt_project_customization',
        'ft_pms_planning_workflow',
    ],
    'external_dependencies': {'python': ['xlsxwriter', 'pytz', 'reportlab']},
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        'data/cron.xml',
        'views/monthly_report_views.xml',
        'views/project_views.xml',
        'wizard/generate_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
