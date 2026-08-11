from odoo import _, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_ft_send_whatsapp(self):
        return {
            "name": _("WhatsApp message"),
            "type": "ir.actions.act_window",
            "res_model": "mail.compose.gateway.message",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {
                "default_model": "res.partner",
                "default_res_ids": self.ids,
                "default_partner_ids": self.ids,
                "default_wizard_partner_ids": self.ids,
                "default_subtype_xmlid": "mail.mt_comment",
            },
        }
