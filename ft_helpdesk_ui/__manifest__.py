{
    'name': 'FT Helpdesk - UI Components',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Shared UI styling and components for helpdesk portal',
    'description': """
        FingertipTech Helpdesk UI Module
        ==================================
        - Shared portal CSS components and utilities
        - Responsive layout helpers
        - Common UI patterns and design tokens
        - Email notification templates
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
        'mail',
        'portal',
    ],
    'data': [
        'views/email_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ft_helpdesk_ui/static/src/scss/variables.scss',
            'ft_helpdesk_ui/static/src/scss/components.scss',
            'ft_helpdesk_ui/static/src/scss/responsive.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
}
