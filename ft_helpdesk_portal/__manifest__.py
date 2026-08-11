{
    'name': 'FT Helpdesk - Customer Portal',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Modern customer portal for ticket management',
    'description': """
        FingertipTech Helpdesk Portal Module
        ======================================
        - Modern SaaS-like customer support portal
        - Ticket creation with category selection and dynamic fields
        - Ticket listing with filters, search, and sorting
        - Ticket detail with conversation thread
        - Reply with attachments
        - KB article suggestions during ticket creation
        - Responsive mobile-friendly design
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
        'ft_helpdesk_knowledge',
        'project_custom_milestone',
        'portal',
        'project',
        'web',
        'website',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/portal_templates.xml',
        'views/portal_ticket_create.xml',
        'views/portal_ticket_list.xml',
        'views/portal_ticket_detail.xml',
        'views/portal_menu.xml',
        'views/login_templates.xml',
        'views/release_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ft_helpdesk_portal/static/src/scss/portal.scss',
            'ft_helpdesk_portal/static/src/js/portal.js',
        ],
    },
    'installable': True,
    'auto_install': False,
}
