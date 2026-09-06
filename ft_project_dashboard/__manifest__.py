{
    'name': 'FT Project Dashboard',
    'version': '19.0.1.3.0',
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
 * An Analysis page on the project form carrying the Hours Utilisation and
   Tasks Summary sections, scoped to that one project and computed by the same
   server methods the board calls.
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
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_project_dashboard/static/src/scss/dashboard.scss',
            'ft_project_dashboard/static/src/scss/project_analysis.scss',
            'ft_project_dashboard/static/src/js/date_range.js',
            'ft_project_dashboard/static/src/js/kpi_card.js',
            'ft_project_dashboard/static/src/js/chart_card.js',
            'ft_project_dashboard/static/src/js/data_table.js',
            'ft_project_dashboard/static/src/js/search_select.js',
            'ft_project_dashboard/static/src/js/project_dashboard.js',
            'ft_project_dashboard/static/src/js/project_analysis.js',
            'ft_project_dashboard/static/src/xml/dashboard_templates.xml',
            'ft_project_dashboard/static/src/xml/project_analysis_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
