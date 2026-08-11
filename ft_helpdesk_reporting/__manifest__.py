{
    'name': 'FT Helpdesk - Reporting',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Dashboards, KPIs, and reporting for helpdesk',
    'description': """
        FingertipTech Helpdesk Reporting Module
        ========================================
        - Ticket analysis report (pivot/graph views)
        - KPI tracking: avg response time, resolution time, SLA compliance
        - Team performance dashboards
        - Backlog aging analysis
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': ['ft_helpdesk_core', 'ft_helpdesk_sla'],
    'data': [
        'security/ir.model.access.csv',
        'views/ticket_analysis_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'auto_install': False,
}
