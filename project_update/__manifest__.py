{
    'name': 'Project Activity Update',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Project Activity Updates with Date and Project Manager',
    'description': """
        Project Activity Update Module
        ====================
        - Add project activity update records
        - Track date and project manager
        - List and Pivot views
        - Restricted access to specific user group
    """,
    'depends': ['project'],
    'data': [
        'security/project_activity_update_security.xml',
        'security/ir.model.access.csv',
        'views/project_activity_update_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}