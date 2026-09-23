{
    'name': 'Project Custom Milestone',
    'version': '19.0.1.0',
    'summary': 'Manage project milestones with payment tracking',
    'category': 'Project',
    'author': 'Your Company',
    'depends': ['project','sale','mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_milestone_views.xml',
    ],
    'installable': True,
    'application': True,
}
