# -*- coding: utf-8 -*-
{
    "name": "PMS Suggestions / Feedback",
    # 18.0.1.1.0 replaces the email notification with a real-time bus popup.
    # The version bump is what makes the new data file and JS asset load on
    # upgrade.
    "version": "19.0.1.1.0",
    "category": "Productivity",
    "summary": "Employee suggestion box for PMS improvements, with approval "
                "workflow, lock-after-approval, and admin notifications.",
    "description": """

- Employees submit a PMS improvement suggestion with an auto-generated ID,
  a title, the module/area it relates to, and a rich-text description
  (supports pasted images) plus a normal attachment button (via chatter).
- "Suggested By" is auto-filled from the logged-in user.
- Status flow: Suggestion -> Approved -> Implemented.
- Once Approved, the suggestion becomes read-only for everyone. Admins get
  an "Unlock for Editing" button to override this when genuinely needed.
- On submission, a real-time popup is pushed over the Odoo bus to the
  administrators and to the logins listed in the
  `ft_pms_suggestions.notify_logins` system parameter. No email is sent and
  no outgoing mail server is involved. Recipients who are not logged in at
  the time see the suggestion from the Suggestions menu instead.
""",
    "author": "Fingertip",
    "license": "LGPL-3",
    "depends": ["base", "mail", "general"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_config_parameter.xml",
        "views/pms_suggestion_category_views.xml",
        "views/pms_suggestion_views.xml",
        "views/suggestion_app_menu.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ft_pms_suggestions/static/src/js/suggestion_notification.js",
        ],
    },
    "installable": True,
    "application": True,
}
