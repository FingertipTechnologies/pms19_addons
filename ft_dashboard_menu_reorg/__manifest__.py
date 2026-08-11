{
    'name': 'FT Dashboard Menu Reorganization',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Moves each department dashboard menu from the standalone Dashboards app into its own module',
    'description': """
FT Dashboard Menu Reorganization
=================================
Reparents the existing department dashboard menu items — which by default
live under Odoo's standalone "Dashboards" app (spreadsheet_dashboard) — so
each one instead appears inside the app it belongs to:

* Project Dashboard  -> PMS (project.menu_main_pm)
* Sales Dashboard     -> CRM (crm.crm_menu_root)
* Marketing Dashboard -> Marketing (marketing_content.menu_marketing_root)
* HR Dashboard        -> General (general.menu_general_root)
* Finance Dashboard   -> Invoicing (account.menu_finance)

This module makes no changes to the original dashboard modules' Python/data
files; it only overrides the `parent_id`, `name`, `sequence` and `groups_id`
of their existing menu records, plus ADDS (never removes) read-only model
access for each dashboard's data model, so it can be installed/uninstalled
independently.

IMPORTANT — access widening: each dashboard originally shipped hardcoded to
`groups="base.group_system"` (Administrator only), on BOTH the menu and the
underlying model (see each dashboard module's own ir.model.access.csv). Left
as-is, moving them "first" in their app would have no effect for anyone but
literal Administrators. This module opens each dashboard's menu (clears its
groups_id) and grants READ-only model access to whoever can already see the
app it now lives in, matching that app's own access matrix in
ft_homepage/data/menu_access_data.xml:

* Project Dashboard  -> base.group_user (PMS is open to all)
* Sales Dashboard     -> sales_team.group_sale_salesman (CRM)
* Marketing Dashboard -> Project_Scorecards.group_scorecard_marketing
* HR Dashboard        -> base.group_user (General is open to all)
* Finance Dashboard   -> base.group_system + sales_team.group_sale_salesman
                         (Invoicing)

The original admin-only access rules are left in place (untouched) in each
dashboard module; this only ADDS a broader read grant on top.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'ft_project_dashboard',
        'ft_sales_dashboard',
        'ft_marketing_dashboard',
        'ft_hr_dashboard',
        'ft_finance_dashboard',
        'project',
        'crm',
        'marketing_content',
        'general',
        'account',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/menu_reorganization.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
