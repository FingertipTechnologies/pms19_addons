{
    'name': 'QA TestApp – Test & Bug Tracker',
    'version': '19.0.1.2.0',
    'category': 'Quality Assurance',
    'summary': 'Test Plans, Scenarios, Test Cases & Bug Tickets — all-in-one QA suite',
    'description': """
QA TestApp – Test & Bug Tracker
===============================
A comprehensive Quality Assurance suite for Odoo 18 with:
 * Test Plan management (scope, objectives, approach, schedule)
 * Test Scenario tracking (steps, coverage, status)
 * Test Case execution (data, preconditions, steps, actual/expected, severity)
 * Bug/Ticket tracking (Bug ID, reporter, description, reproducibility, attachments — full ticket lifecycle)
""",
    'author': 'Fingertip',
    'website': '',
    'depends': ['base', 'project', 'mail', 'bt_project_customization', 'hr_timesheet', 'project_update', 'project_custom_milestone', 'ft_helpdesk_core', 'ft_helpdesk_portal'],
    'data': [
            'security/qa_security.xml',
            'security/ir.model.access.csv',
            'data/ticket_sequence.xml',
            'data/approval_mail_templates.xml',
            'data/mayora_bug_user.xml',
            'views/test_plan_views.xml',
            'views/test_scenario_views.xml',
            'views/test_case_views.xml',
            'views/ticket_views.xml',
            'views/project_project_views.xml',
            'views/project_analysis_views.xml',
            'views/res_users_views.xml',
            'wizard/bulk_approve_wizard_views.xml',
            'views/menu.xml',
            'views/menu_reorganization.xml',
        ],
    'static': ['static/description/icon.svg'],
    'assets': {
        'web.assets_backend': [
            'qa_testapp/static/src/evidence_description/evidence.scss',
            'qa_testapp/static/src/evidence_description/evidence_html_field.js',
            'qa_testapp/static/src/evidence_attachments/evidence_attachments_field.js',
            'qa_testapp/static/src/evidence_attachments/evidence_attachments_field.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}