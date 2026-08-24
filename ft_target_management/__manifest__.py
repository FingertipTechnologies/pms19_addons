{
    'name': 'FT KPI Management',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Define KRAs, periods and per-person KPIs with actual vs target tracking.',
    'description': """
FT KPI Management
=================
A small standalone app to set and track KPIs.

* **KRA** (Key Result Area) — a named result area categorised by Department
  and Job Role.
* **KPI Period** — a date range (Start / End) KPIs are measured over.
* **KPI** — links a KRA + Period, holds Target Value, Actual Value, the person
  it is Assigned To, and a computed achievement %.

The technical names (models ``ft.target``, ``ft.target.type``,
``ft.target.period``, and this module's directory) are deliberately left
unchanged — only the labels users see were renamed, so no data migration is
needed.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'hr',
    ],
    'data': [
        'security/target_security.xml',
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
