{
    'name': 'FT Helpdesk - Knowledge Base',
    'version': '19.0.1.0.0',
    'category': 'Services/Helpdesk',
    'summary': 'Knowledge base for self-service and ticket deflection',
    'description': """
        FingertipTech Helpdesk Knowledge Base Module
        ==============================================
        - KB categories and articles
        - Portal-facing knowledge base with search
        - Article suggestions during ticket creation (deflection)
        - Helpful votes tracking
        - Backend article management with rich editor
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
        'ft_helpdesk_reporting',
        'portal',
        'web',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/kb_backend_views.xml',
        'views/kb_portal_templates.xml',
        'views/kb_article_analysis_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'ft_helpdesk_knowledge/static/src/scss/kb_portal.scss',
        ],
    },
    'installable': True,
    'auto_install': False,
}
