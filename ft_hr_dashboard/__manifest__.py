{
    'name': 'FT HR Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Executive HR Dashboard — KPI cards & Chart.js analytics (OWL)',
    'description': """
FT HR Dashboard
===============
A modern, executive-level HR dashboard for management:
 * KPI cards (assets, recruitment pipeline, candidates, interviews, positions).
 * Analytical charts built with OWL components + Chart.js, drill-down to records.

Reads the asset and recruitment models provided by the `general` module.
Extracted from `general` into its own standalone module.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'general',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_hr_dashboard/static/src/scss/hr_dashboard.scss',
            'ft_hr_dashboard/static/src/js/kpi_card.js',
            'ft_hr_dashboard/static/src/js/chart_card.js',
            'ft_hr_dashboard/static/src/js/hr_dashboard.js',
            'ft_hr_dashboard/static/src/xml/hr_dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
