# -*- coding: utf-8 -*-
from odoo import api, fields, models

INTRO_PARAM = "ft_customer_feedback.intro_text"
THANKS_PARAM = "ft_customer_feedback.thanks_text"
START_MONTH_PARAM = "ft_customer_feedback.monthly_start_month"

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

    # ------------------------------------------------------------------
    # Monthly feedback requests
    # ------------------------------------------------------------------
    ft_feedback_monthly_start_month = fields.Date(
        string="First Feedback Month",
        help="Monthly feedback requests are only created for this month and "
        "later months (avoids sending requests for old months on install). "
        "Leave empty to start with the previous month.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        raw = self.env["ir.config_parameter"].sudo().get_param(START_MONTH_PARAM)
        value = False
        if raw:
            try:
                value = fields.Date.to_date(raw.strip())
            except (TypeError, ValueError):
                value = False
        res["ft_feedback_monthly_start_month"] = value
        return res

    def set_values(self):
        super().set_values()
        value = self.ft_feedback_monthly_start_month
        self.env["ir.config_parameter"].sudo().set_param(
            START_MONTH_PARAM,
            fields.Date.to_string(value.replace(day=1)) if value else False,
        )
