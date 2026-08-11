{
    'name': 'FT Helpdesk - SLA',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'SLA policies, deadline tracking, and breach detection',
    'description': """
        FingertipTech Helpdesk SLA Module
        ==================================
        - SLA policy definitions with matching criteria
        - Per-ticket SLA status with deadlines
        - First response and resolution SLA tracking
        - Breach detection cron job
        - Escalation notifications on SLA breach
        - Business hours support for SLA computation
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/sla_views.xml',
        'views/ticket_sla_widgets.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'auto_install': False,
}
