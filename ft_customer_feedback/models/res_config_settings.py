# -*- coding: utf-8 -*-
from odoo import fields, models

INTRO_PARAM = "ft_customer_feedback.intro_text"
THANKS_PARAM = "ft_customer_feedback.thanks_text"

DEFAULT_INTRO = (
    "Thank you for availing our services. "
    "Please take a minute to share your experience with us."
)
DEFAULT_THANKS = (
    "Thank you for your feedback. It helps us serve you better."
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    feedback_intro_text = fields.Char(
        string="Feedback Introduction",
        config_parameter=INTRO_PARAM,
        default=DEFAULT_INTRO,
        help="Shown at the top of the portal feedback page, under the "
        "customer greeting.",
    )
    feedback_thanks_text = fields.Char(
        string="Thank You Message",
        config_parameter=THANKS_PARAM,
        default=DEFAULT_THANKS,
        help="Shown after the customer submits the form.",
    )
