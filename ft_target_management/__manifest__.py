{
    'name': 'FT KPI Management',
    'version': '19.0.2.0.0',
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

Visibility
----------
The KPI app is open to **every internal user** — no group assignment needed.
What differs is what each person finds inside it:

* a user sees only the KPIs assigned to them, plus the KPIs of their direct
  reports (the *Manager* set on the employee record);
* somebody with no KPI of their own simply gets an empty list, not an access
  error and not a missing app;
* a KPI *Manager* sees every KPI, including unassigned ones.

Everyone except a *Manager* is strictly read-only: creating, editing and
deleting KPIs — and configuring KRAs and KPI Periods — is reserved for
Managers, so nobody can revise their own target or actual figure.

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
