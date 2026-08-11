{
    'name': 'FT Helpdesk - Automation',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Macros and triggers for ticket automation',
    'description': """
        FingertipTech Helpdesk Automation Module
        ==========================================
        - Macros: one-click actions (change state, priority, tags, assignment + template reply)
        - Triggers: condition-based automation (on create, state change, SLA breach, customer reply)
        - Domain builder for trigger conditions
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': ['ft_helpdesk_core'],
    'data': [
        'security/ir.model.access.csv',
        'views/macro_views.xml',
        'views/trigger_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'auto_install': False,
}
