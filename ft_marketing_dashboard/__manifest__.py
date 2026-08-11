{
    'name': 'FT Marketing Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Marketing',
    'summary': 'Executive Marketing Dashboard — KPI cards & Chart.js analytics (OWL)',
    'description': """
FT Marketing Dashboard
======================
A modern, executive-level Marketing dashboard for management:
 * KPI cards (enquiries, leads, campaigns).
 * Analytical charts built with OWL components + Chart.js, drill-down to records.

Reads `marketing.enquiry` (from `marketing_content`) plus `crm.lead` /
`utm.campaign`. Extracted from `marketing_content` into its own standalone module.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'marketing_content',
        'crm',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/marketing_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_marketing_dashboard/static/src/scss/marketing_dashboard.scss',
            'ft_marketing_dashboard/static/src/js/kpi_card.js',
            'ft_marketing_dashboard/static/src/js/chart_card.js',
            'ft_marketing_dashboard/static/src/js/marketing_dashboard.js',
            'ft_marketing_dashboard/static/src/xml/marketing_dashboard_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
