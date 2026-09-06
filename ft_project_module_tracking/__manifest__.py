{
    'name': 'Project Modules and Stage-wise Time',
    'version': '19.0.1.0.0',
    'summary': 'Configure project applications and report timesheet hours by project stage',
    'category': 'Project',
    'author': 'Fingertip',
    'license': 'LGPL-3',
    'depends': ['bt_project_customization'],
    'data': [
        'security/ir.model.access.csv',
        'views/ft_project_module_views.xml',
    ],
    'pre_init_hook': 'pre_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
