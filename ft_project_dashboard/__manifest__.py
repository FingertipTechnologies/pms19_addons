{
    'name': 'FT Project Dashboard',
    'version': '19.0.1.1.0',
    'category': 'Project',
    'summary': 'Executive Project Dashboard — KPI cards & Chart.js analytics (OWL)',
    'description': """
FT Project Dashboard
====================
A modern, executive-level Project Dashboard for management:
 * 10 KPI cards (Active Projects, Hours Spent/Billable, Developers/Testers/PMs,
   Estimated/Remaining hours, Resource Need/Available).
 * 6 analytical charts (status distribution, resource overview, project hours,
   billable vs non-billable, team composition, progress trend).
 * Date-range filters (Today / Week / Month / Quarter / Year / Custom).
 * Built with OWL components + Chart.js, drill-down to records.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'project',
        'hr',
        'hr_timesheet',
        'bt_project_customization',
        'ft_task_hours_tracker',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_project_dashboard/static/src/scss/dashboard.scss',
            'ft_project_dashboard/static/src/js/kpi_card.js',
            'ft_project_dashboard/static/src/js/chart_card.js',
            'ft_project_dashboard/static/src/js/data_table.js',
            'ft_project_dashboard/static/src/js/search_select.js',
            'ft_project_dashboard/static/src/js/project_dashboard.js',
            'ft_project_dashboard/static/src/xml/dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
