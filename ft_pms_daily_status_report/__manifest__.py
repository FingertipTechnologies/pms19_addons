{
    'name': 'FT PMS Daily Status Report',
    # 19.0.1.0.0 first release: one consolidated e-mail per Project Manager /
    #   Technical Lead every day with the Implementation stage figures
    #   (ft_project_stage_report) and the AMC task overdue table
    #   (ft_amc_overdue_dashboard) of their projects. Adds
    #   project.project.technical_lead_id, the send-hour / sender / Excel
    #   row-limit settings on res.company, a send log with a dedupe per
    #   (recipient, day) and a "Send now" wizard.
    'version': '19.0.1.0.0',
    'summary': 'Daily Implementation and AMC status e-mail to Project '
               'Managers and Technical Leads',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': [
        'project',
        'mail',
        'ft_project_stage_report',
        'ft_amc_overdue_dashboard',
    ],
    'external_dependencies': {'python': ['xlsxwriter', 'pytz']},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'data/email_templates.xml',
        'views/project_project_views.xml',
        'views/daily_report_log_views.xml',
        'wizard/daily_report_wizard_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
