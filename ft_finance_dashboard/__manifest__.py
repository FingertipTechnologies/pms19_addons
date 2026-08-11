{
    'name': 'Finance Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Executive Finance dashboard — Revenue, Outstanding, Collection, Expense',
    'description': """
Finance Dashboard
=================
Admin-only OWL + Chart.js dashboard under the Dashboards app:
 * Revenue, Outstanding, Collection, Expense KPIs
 * Revenue vs Expense trend and a summary comparison
 * Date-range filtering
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['account', 'web', 'spreadsheet_dashboard'],
    'data': [
        'security/ir.model.access.csv',
        'views/finance_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_finance_dashboard/static/src/scss/finance_dashboard.scss',
            'ft_finance_dashboard/static/src/js/kpi_card.js',
            'ft_finance_dashboard/static/src/js/chart_card.js',
            'ft_finance_dashboard/static/src/js/finance_dashboard.js',
            'ft_finance_dashboard/static/src/xml/finance_dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
