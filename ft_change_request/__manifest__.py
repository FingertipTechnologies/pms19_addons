{
    'name': 'FT Project Change Request',
    'version': '19.0.1.0.0',
    'category': 'Project',
    'summary': 'Change Request tab on projects — auto-numbered requests with status and estimated hours.',
    'description': """
FT Project Change Request
========================
Adds a **Change Request** notebook tab to the Project form. Each project keeps
a list of change requests with an auto-generated request number, date, status
(Submitted / Approved / Rejected / Implemented) and estimated hours.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'project',
        'mail',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/change_request_sequence.xml',
        'views/change_request_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
