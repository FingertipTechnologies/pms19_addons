# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .res_users import CONFIG_PARAM


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    homepage_default_landing = fields.Boolean(
        string="Land on Homepage after login",
        help="When enabled, all users (without a personal Home Action) are "
        "redirected to the Homepage (app icons grid) right after logging "
        "in, instead of Discuss or Invoicing. This is a system-wide "
        "default; it can still be overridden per user in "
        "Preferences.",
        config_parameter=CONFIG_PARAM,
        default=True,
    )

    def set_values(self):
        res = super().set_values()
        self.env["res.users"]._apply_homepage_landing_setting(
            self.homepage_default_landing
        )
        return res
