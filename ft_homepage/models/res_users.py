# -*- coding: utf-8 -*-
from odoo import api, fields, models

CONFIG_PARAM = "ft_homepage.default_landing_homepage"


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.depends("action_id")
    def _compute_redirect_home(self):
        
        homepage_is_default = (
            self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM, "True")
            == "True"
        )
        for user in self:
            if user.action_id:
                user.is_redirect_home = False
            else:
                user.is_redirect_home = homepage_is_default

    @api.model
    def _init_homepage_landing(self):
        """Called from data/apply_landing_page.xml on every module
        install/upgrade: actually pushes the system-wide landing page
        setting onto all existing users. Without this, `is_redirect_home`
        (a STORED field from web_responsive) keeps its old value and users
        keep landing on Discuss/Invoicing.
        """
        enabled = (
            self.env["ir.config_parameter"].sudo().get_param(CONFIG_PARAM, "True")
            == "True"
        )
        self._apply_homepage_landing_setting(enabled)

    def _apply_homepage_landing_setting(self, enabled):
        """Mass-apply the system-wide landing page setting to every user.

        When enabling, this also clears any personal "Home Action"
        (res.users.action_id) — e.g. Discuss or Invoicing — that was set on
        users before this setting existed, since the requirement is that
        the Homepage becomes the default landing page for ALL users, not
        just the ones without a pre-existing Home Action.
        """
        all_users = self.sudo().search([])
        if enabled:
            all_users.write({"action_id": False, "is_redirect_home": True})
        else:
            all_users.filtered(lambda u: not u.action_id).write(
                {"is_redirect_home": False}
            )
