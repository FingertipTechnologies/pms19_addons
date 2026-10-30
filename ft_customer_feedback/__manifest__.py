# -*- coding: utf-8 -*-
{
    "name": "FT Customer Feedback",
    "version": "19.0.2.3.1",
    "category": "Services/Helpdesk",
    "summary": "Configurable customer feedback survey on the customer portal "
               "with smiley ratings, 0-10 scores and free text answers.",
    "description": """
FT Customer Feedback
====================
- Questions are configured in the backend (Customer Feedback > Configuration).
  Each question is just a subject plus an answer type:
  * Rating      - 5 smiley faces (Poor / Fair / Good / Very Good / Excellent)
  * Score 0-10  - coloured 0..10 scale (Poor / Good / Excellent)
  * Free Text   - text area
  Questions can be grouped under sections and ordered with drag and drop.
- Logged-in customers get an orange "Feedback" button in the portal header
  and a "Feedbacks" tab (after Knowledge Base) listing the feedback already
  given, each opening to its answers. The form page lists all
  active questions; the answers are stored in one Response record
  (date, customer, user) with one line per question holding the number or
  the free text.
- Responses are reviewed from Customer Feedback > Responses (list, form,
  pivot and graph views). Each answer keeps the question text and type as
  they were when the customer answered.
- Reporting menu: customer-wise feedback, question-wise analysis, average
  ratings and monthly trends. All figures are averages over submitted
  responses only; 1-5 ratings and 0-10 scores are never mixed.
- Monthly feedback requests: one request per enabled project and month,
  sent by email to the project's feedback contacts with a project-specific
  link (single cron on the 1st of every month, per-contact channel status,
  Send Now / Retry Failed). The email status of each contact is updated by
  the mail queue when the email is sent.
  WhatsApp sending is in the separate module ft_customer_feedback_whatsapp.

Changelog
---------
- 19.0.2.3.1: no daily cron any more; the email status (Queued -> Sent /
  Failed) is updated by the mail queue when it sends the email. Migration
  removes the "Synchronise Request Status" cron.
- 19.0.2.3.0: the monthly feedback request cron now runs on the 1st of every
  month (03:30 UTC / 09:00 IST) instead of daily. Migration updates the
  existing cron record.
- 19.0.2.1.0: WhatsApp moved to the new module ft_customer_feedback_whatsapp
  (no more dependency on mail_gateway_whatsapp / ft_message_tracking); this
  module now sends the monthly requests by email only and exposes channel
  hooks on ft.feedback.request.recipient (_ft_send_channels,
  _ft_channel_states, _ft_channel_done_states, _ft_sync_channel_states,
  _ft_cron_sync_channel_states).
- 19.0.2.0.0: monthly customer feedback requests (email + WhatsApp).
""",
    "author": "Fingertip",
    "website": "https://www.fingertiptech.com",
    "license": "LGPL-3",
    "depends": [
        "portal",
        "mail",
        "project",
        "ft_helpdesk_portal",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "data/ir_config_parameter.xml",
        "data/mail_template_feedback_request.xml",
        "data/feedback_request_cron.xml",
        # "data/feedback_question_data.xml",
        "views/feedback_question_views.xml",
        "views/feedback_response_views.xml",
        "views/feedback_report_views.xml",
        "views/res_config_settings_views.xml",
        "views/feedback_request_views.xml",
        "views/menus.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "ft_customer_feedback/static/src/scss/feedback_portal.scss",
        ],
        "web.assets_backend": [
            "ft_customer_feedback/static/src/scss/feedback_backend.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
