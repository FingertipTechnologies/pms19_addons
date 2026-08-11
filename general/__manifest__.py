# -*- coding: utf-8 -*-
{
    'name': 'General',
    'version': '19.0.1.0.0',
    'category': 'Human Resources',
    'summary': 'Asset Management, Expense Management and Recruitment',
    'description': """
General
===========
Single module providing three internal-operations sub-systems:

* **Asset Management** — categories, asset master, employee assignment,
  maintenance / repair.
* **Expense Management** — categories, employee expense claims with
  multi-line bills, advances.
* **Recruitment** — job positions, candidate database, interviews,
  offers and onboarding to HR.

Each sub-system has its own top-level menu, sequences and security groups.
""",
    'author': 'Your Company',
    'website': 'https://www.example.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'hr',
        'board',
    ],
    'data': [
        # Security
        'security/pms_security.xml',
        'security/ir.model.access.csv',

        # Sequences
        'data/ir_sequence_data.xml',

        # Master app menu (must load before module menus)
        'views/general_menus.xml',

        # Asset views
        'views/asset_category_views.xml',
        'views/company_asset_views.xml',
        'views/asset_assignment_views.xml',
        'views/asset_maintenance_views.xml',
        'views/asset_reports.xml',
        'views/asset_menus.xml',

        # Expense views
        'views/expense_category_views.xml',
        'views/employee_expense_claim_views.xml',
        'views/employee_advance_views.xml',
        'views/expense_reports.xml',
        'views/expense_menus.xml',

        # Recruitment views
        'views/recruitment_skill_views.xml',
        'views/recruitment_job_position_views.xml',
        'views/recruitment_candidate_views.xml',
        'views/recruitment_interview_views.xml',
        'views/recruitment_offer_views.xml',
        'views/employee_onboarding_views.xml',
        'views/recruitment_reports.xml',
        'views/recruitment_menus.xml',

        # Dashboards (load last — reference report actions + root menus)
        'views/asset_dashboard.xml',
        'views/expense_dashboard.xml',
        'views/recruitment_dashboard.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'general/static/src/js/many2many_binary_preview.js',
            'general/static/src/xml/many2many_binary_preview.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
