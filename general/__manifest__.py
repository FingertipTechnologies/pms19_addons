# -*- coding: utf-8 -*-
{
    'name': 'General',
    # 19.0.1.1.0: expense claim bulk Approve / Mark as Paid moved from the
    # list "Actions" dropdown to list header buttons (server actions removed).
    # 19.0.1.2.0: those header buttons now hide based on the selected rows
    # (Approve only for draft/submitted/rejected, Mark as Paid only for
    # approved+unpaid; nothing on approved+paid) via a ListController patch.
    # 19.0.1.3.0: ft_claim_can_approve / ft_claim_can_pay become technical
    # fields (hidden list columns) so the view validates - 19.0.1.2.0's
    # header buttons named them in `invisible` without a field behind them.
    # 19.0.1.4.0: claim status flow.
    #   Buttons (form and list, per selected rows): Approve while not yet
    #   approved, Mark as Paid while not yet paid (paying approves as well),
    #   neither once approved and paid. Rejected claims cannot be approved
    #   again - a new claim is raised instead - and Reject asks for a reason
    #   (wizard), kept on the claim and in the chatter. Approval Status on
    #   the Approval & Payment tab is read-only: the buttons drive it.
    # 19.0.1.5.0: advances and claims.
    #   Rejected claims show Rejected By / Rejected Date in place of Approved
    #   By / Approved Date. A new claim's Advance Paid is prefilled with the
    #   employee's available advance balance (sum of their open advances'
    #   Balance Amount) and stays editable; the oldest open advance is linked.
    #   One advance can be adjusted by several claims (Related Expense Claims
    #   tags + a Claims tab): Adjusted Amount is the sum of the claims'
    #   Advance Used (min of Total Amount and Advance Paid, 0 when rejected),
    #   Balance Amount the rest, and Status follows (computed). Replaces the
    #   claim-to-claim "Balance Carried Forward" of 19.0.1.4.0. Migration
    #   moves the old single Related Expense Claim link onto the claim.
    # 19.0.1.5.1: an employee could not Submit their own claim ("You cannot
    #   modify an expense claim that has already been submitted"): the status
    #   automation ran as a second write after the claim had left Draft. It
    #   is now part of the same write.
    # 19.0.1.5.2: a new claim defaults Employee to the logged-in user's
    #   employee, and Department follows the employee (still editable).
    'version': '19.0.1.5.2',
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
        'wizard/expense_claim_reject_views.xml',
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
            'general/static/src/js/expense_claim_list_header.js',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
