{
    'name': 'FT Sales Dashboard',
    # 19.0.1.6.2 gives every funnel stage its own colour, with Won and Lost
    # on reserved status colours, replacing the single-hue blue ramp.
    'version': '19.0.1.6.2',
    'category': 'Sales/CRM',
    'summary': 'Executive Sales Dashboard — KPI cards & Chart.js analytics (OWL)',
    'description': """
FT Sales Dashboard
==================
A modern, executive-level Sales/CRM dashboard for management:
 * KPI cards (opportunities, pipeline value, conversion ratio, closed sales).
 * Analytical charts (pipeline by stage, sales funnel, trends).
 * Built with OWL components + Chart.js, drill-down to records.

Extracted from bt_crm_customization into its own standalone module.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'crm',
        'spreadsheet_dashboard',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/sales_dashboard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_sales_dashboard/static/src/scss/sales_dashboard.scss',
            'ft_sales_dashboard/static/src/js/kpi_card.js',
            'ft_sales_dashboard/static/src/js/chart_card.js',
            'ft_sales_dashboard/static/src/js/funnel_chart.js',
            'ft_sales_dashboard/static/src/js/table_card.js',
            'ft_sales_dashboard/static/src/js/month_board.js',
            'ft_sales_dashboard/static/src/js/sales_dashboard.js',
            'ft_sales_dashboard/static/src/xml/sales_dashboard_templates.xml',
        ],
    },
    # Three data repairs the dashboard depends on, all idempotent:
    #  * fills the Closed Date that won/lost opportunities imported straight
    #    into a Won stage never received (Sales Closed / Lost would otherwise
    #    under-report against a CRM export);
    #  * moves archived opportunities into the Lost stage, so a list, export or
    #    pivot never shows a dead deal under Discussion / Demo / Negotiation;
    #  * moves opportunities won by probability into the Won stage, so the same
    #    reports never show a won deal under Demo either.
    # See models/crm_lead.py.
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
