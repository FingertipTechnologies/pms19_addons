{
    'name': 'FT Target Management',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Define target types, periods and per-person targets with actual vs target tracking.',
    'description': """
FT Target Management
===================
A small standalone app to set and track targets.

* **Target Type** — a named target categorised by Department and Job Role.
* **Target Period** — a date range (Start / End) targets are measured over.
* **Target** — links a Target Type + Period, holds Target Value, Actual Value,
  the person it is Assigned To, and a computed achievement %.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'hr',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/target_type_views.xml',
        'views/target_period_views.xml',
        'views/target_views.xml',
        'views/target_menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
