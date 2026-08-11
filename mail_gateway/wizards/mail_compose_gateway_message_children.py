from odoo import api, models


class MailComposeGatewayMessage(models.TransientModel):
    _inherit = "mail.compose.gateway.message"

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_ids = self._extract_partner_ids(res)
        if not partner_ids:
            return res
        expanded = self._expand_company_children(partner_ids)
        if expanded == set(partner_ids):
            return res
        expanded_list = list(expanded)
        if "wizard_partner_ids" in fields_list:
            res["wizard_partner_ids"] = [(6, 0, expanded_list)]
        channel_ids = self._autocreate_gateway_channels(expanded_list)
        if channel_ids and "wizard_channel_ids" in fields_list:
            res["wizard_channel_ids"] = [(6, 0, channel_ids)]
        return res

    @api.model
    def _extract_partner_ids(self, res):
        val = res.get("wizard_partner_ids")
        if isinstance(val, list) and val and isinstance(val[0], (list, tuple)):
            if val[0][0] == 6:
                return list(val[0][2])
        return []

    @api.model
    def _expand_company_children(self, partner_ids):
        partners = self.env["res.partner"].browse(partner_ids)
        expanded = set(partner_ids)
        for partner in partners:
            if partner.is_company:
                expanded.update(partner.child_ids.ids)
        return expanded
