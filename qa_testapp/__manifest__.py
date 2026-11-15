{
    'name': 'QA TestApp – Test & Bug Tracker',
    # 19.0.1.4.0 (Bugs: "Reason for Reopen" tab):
    #   - New model qa_testapp.bug_reopen_reason: one entry per press of
    #     Re-Open, named "Reopen 1", "Reopen 2", ... from the EXISTING
    #     reopen_count (no second counter), created by action_reopen right
    #     after the count is incremented. Rich text + attachments use the
    #     Evidence tab's exact mechanism (Html field with the same sanitize
    #     options rendered by qa_evidence_html; ir.attachment Many2many
    #     rendered by qa_evidence_files; attachments re-linked to the entry).
    #   - Bug form: new "Reason for Reopen" tab beside Evidence (Evidence is
    #     unchanged). The latest entry is edited inline through writable
    #     related fields on the bug; all entries are listed below and open
    #     read-only as history.
    #   - Only the latest entry (number == bug.reopen_count) can be modified
    #     or deleted; older entries raise on write/unlink (server-side, sudo
    #     bypasses). Entries can only be created for the bug's current reopen.
    #   - ACL (base.group_user, full) + record rules mirroring the bug's.
    #   - New table only, no data migration: reopens made before this version
    #     have no entry; the next Re-Open creates "Reopen <count>".
    # 19.0.1.4.1: latest_reopen_reason_id stored (saving the inline reason
    #   failed: 'Cannot convert ...latest_reopen_reason_id to SQL').
    'version': '19.0.1.4.1',
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
            'security/bug_reopen_reason_security.xml',
            'data/ticket_sequence.xml',
            'data/approval_mail_templates.xml',
            'data/mayora_bug_user.xml',
            'views/test_plan_views.xml',
            'views/test_scenario_views.xml',
            'views/test_case_views.xml',
            'views/bug_reopen_reason_views.xml',
            'views/ticket_views.xml',
            'views/project_project_views.xml',
            'views/project_analysis_views.xml',
            'views/res_users_views.xml',
            'wizard/bulk_approve_wizard_views.xml',
            'wizard/bug_dev_reject_wizard_views.xml',
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