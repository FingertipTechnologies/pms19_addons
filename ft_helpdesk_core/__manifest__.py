{
    'name': 'FT Helpdesk - Core',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Ticket Management System - Core Module',
    'description': """
        FingertipTech Helpdesk Core Module
        ===================================
        - Ticket creation, assignment, and lifecycle management
        - Teams, categories, tags, and dynamic fields
        - Agent console with list, kanban, search, and form views
        - Mail thread integration for conversations
        - Internal notes vs public replies
        - Close/cancel with reason enforcement
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'portal',
        'product',
        'project',
        'project_custom_milestone',
        'web',
    ],
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        # Data
        'data/sequence.xml',
        'data/mail_subtypes.xml',
        'data/mail_templates.xml',
        'data/ticket_stages.xml',
        'data/default_data.xml',
        'data/portal_rule.xml',
        # Wizard
        'wizard/ticket_close_wizard_views.xml',
        'wizard/ticket_resolve_wizard_views.xml',
        'wizard/ticket_assign_wizard_views.xml',
        # Views
        'views/ticket_views.xml',
        'views/team_views.xml',
        'views/category_views.xml',
        'views/tag_views.xml',
        'views/close_reason_views.xml',
        'views/ticket_type_views.xml',
        'views/fieldset_views.xml',
        'views/canned_response_views.xml',
        'views/business_hours_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        'views/menus.xml',
        # Portal
        'views/portal_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_helpdesk_core/static/src/scss/helpdesk_backend.scss',
            'ft_helpdesk_core/static/src/js/helpdesk_backend.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'sequence': 1,
}
