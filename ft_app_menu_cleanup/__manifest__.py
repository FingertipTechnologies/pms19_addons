{
    'name': 'FT App Menu Cleanup',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Hides app icons that are not on the approved list, for every user',
    'description': """
FT App Menu Cleanup
====================
Restricts the Odoo App Switcher / Homepage to only the approved set of
apps for this instance:

CRM, PMS, General, Training, Suggestions, To-do, Marketing,
Performance Reviews, Scorecard, KPI, AI Insights, Invoicing,
Contacts, Dashboards

Everything else that ships with the base install but isn't part of that
list is hidden for EVERY user (not just restricted by group). Currently
that means:

* Discuss
* Calendar
* Sales
* Website
* eLearning
* Email Marketing
* Timesheets

Employees, Helpdesk and Link Tracker are NOT hidden here — they are
role-restricted (visible to the relevant roles only) by
ft_homepage/data/menu_access_data.xml. Hiding them for everyone here would
override those role grants (e.g. it would hide Employees/Helpdesk from
Project Managers, who must see them).

Matching is done by the app's display name (rather than a hardcoded
external ID) so this keeps working even if the exact root-menu XML ID
differs between Odoo versions/editions, or if the app isn't installed
yet. The cleanup re-runs (and is idempotent) every time this module is
updated.

Note: 'Apps' and 'Settings' are intentionally left visible — they are
admin-only system menus and hiding Settings would lock admins out of
configuration.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['base'],
    'data': [
        'data/cleanup_data.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
