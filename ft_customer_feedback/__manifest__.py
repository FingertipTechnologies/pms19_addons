# -*- coding: utf-8 -*-
{
    "name": "FT Customer Feedback",
    "version": "19.0.1.2.0",
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
        "data/feedback_question_data.xml",
        "views/feedback_question_views.xml",
        "views/feedback_response_views.xml",
        "views/feedback_report_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
        "views/portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "ft_customer_feedback/static/src/scss/feedback_portal.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
