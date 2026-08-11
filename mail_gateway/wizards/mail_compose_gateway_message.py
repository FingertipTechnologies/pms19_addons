# Copyright 2024 Dixmit
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class MailComposeGatewayMessage(models.TransientModel):
    _name = "mail.compose.gateway.message"
    _inherit = "mail.compose.message"
    _description = "Mail Compose Gateway Message"

    def _autocreate_gateway_channels(self, partner_ids):
        if not partner_ids:
            return []
        Channel = self.env["res.partner.gateway.channel"].sudo()
        Gateway = self.env["mail.gateway"].sudo()
        gateways = Gateway.search([("gateway_type", "=", "whatsapp")])
        channel_ids = []
        for partner in self.env["res.partner"].browse(partner_ids):
            number = partner.phone
            if not number:
                continue
            try:
                sanitized = partner._phone_format(number=number) or ""
            except Exception:
                sanitized = number or ""
            sanitized = (sanitized or "").replace("+", "").replace(" ", "")
            for gateway in gateways:
                channel = Channel.search(
                    [("partner_id", "=", partner.id),
                     ("gateway_id", "=", gateway.id)], limit=1
                )
                if not channel and sanitized:
                    channel = Channel.create({
                        "partner_id": partner.id,
                        "gateway_id": gateway.id,
                        "gateway_token": sanitized,
                    })
                if channel:
                    channel_ids.append(channel.id)
                    if sanitized and not gateway._get_channel_id(sanitized):
                        gateway_service = "mail.gateway.%s" % gateway.gateway_type
                        if gateway_service in self.env:
                            self.env[gateway_service].sudo()._get_channel(
                                gateway,
                                sanitized,
                                {
                                    "contacts": [{
                                        "wa_id": sanitized,
                                        "profile": {"name": partner.display_name},
                                    }],
                                    "messages": [{"from": sanitized}],
                                },
                                force_create=True,
                            )
        return list(set(channel_ids))

    @api.onchange("wizard_partner_ids", "partner_ids", "model", "res_ids")
    def _onchange_autopopulate_channels(self):
        partner_ids = self.wizard_partner_ids.ids or self.partner_ids.ids or []
        if not partner_ids and self.model == "res.partner" and self.res_ids:
            try:
                import ast
                ids = ast.literal_eval(self.res_ids) if isinstance(self.res_ids, str) else self.res_ids
                partner_ids = list(ids) if isinstance(ids, (list, tuple)) else [ids]
            except Exception:
                partner_ids = []
        channel_ids = self._autocreate_gateway_channels(partner_ids)
        if channel_ids:
            self.wizard_channel_ids = [(6, 0, channel_ids)]
            if not self.wizard_partner_ids:
                self.wizard_partner_ids = [(6, 0, partner_ids)]

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        partner_ids = res.get("partner_ids") or self.env.context.get(
            "default_partner_ids"
        ) or []
        if isinstance(partner_ids, list) and partner_ids and isinstance(
            partner_ids[0], (list, tuple)
        ):
            partner_ids = partner_ids[0][2] if partner_ids[0][0] == 6 else []
        if not partner_ids:
            active_model = self.env.context.get("active_model")
            active_id = self.env.context.get("active_id")
            if active_model == "res.partner" and active_id:
                partner_ids = [active_id]
        if not partner_ids:
            default_model = res.get("model") or self.env.context.get("default_model")
            default_res_ids = res.get("res_ids") or self.env.context.get("default_res_ids")
            if isinstance(default_res_ids, str):
                try:
                    import ast
                    default_res_ids = ast.literal_eval(default_res_ids)
                except Exception:
                    default_res_ids = []
            if default_model == "res.partner" and default_res_ids:
                partner_ids = list(default_res_ids) if isinstance(default_res_ids, (list, tuple)) else [default_res_ids]
        if not partner_ids:
            return res
        channel_ids = self._autocreate_gateway_channels(partner_ids)
        if channel_ids and "wizard_channel_ids" in fields_list:
            res["wizard_channel_ids"] = [(6, 0, channel_ids)]
        if partner_ids and "wizard_partner_ids" in fields_list:
            res["wizard_partner_ids"] = [(6, 0, partner_ids)]
        return res

    wizard_partner_ids = fields.Many2many(
        "res.partner",
        "mail_compose_gateway_message_res_partner_rel",
        "wizard_id",
        "partner_id",
    )
    wizard_channel_ids = fields.Many2many(
        "res.partner.gateway.channel",
        "mail_compose_gateway_message_gateway_channel_rel",
        "wizard_id",
        "channel_id",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "mail_compose_gateway_message_ir_attachments_rel",
        "wizard_id",
        "attachment_id",
        "Attachments",
    )
    partner_ids = fields.Many2many(
        "res.partner",
        "mail_compose_gateway_message_res_partner_rel",
        "wizard_id",
        "partner_id",
        "Additional Contacts",
        domain=lambda r: r._partner_ids_domain(),
    )
    # Dummy compatibility with other OCA modules
    # OCA/mail_attach_existing_attachment
    object_attachment_ids = fields.Many2many(
        comodel_name="ir.attachment",
        relation="mail_compose_gateway_message_ir_attachments_object_rel",
        column1="wizard_id",
        column2="attachment_id",
        string="Object Attachments",
    )
    # OCA/mail_composer_cc_bcc
    partner_cc_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="mail_compose_gateway_message_res_partner_cc_rel",
        column1="wizard_id",
        column2="partner_id",
        string="Cc",
    )
    partner_bcc_ids = fields.Many2many(
        comodel_name="res.partner",
        relation="mail_compose_gateway_message_res_partner_bcc_rel",
        column1="wizard_id",
        column2="partner_id",
        string="Bcc",
    )

    def _partner_ids_domain(self):
        return [("id", "in", self.env.context.get("default_partner_ids", []))]

    def _prepare_mail_values_dynamic(self, res_ids):
        self.ensure_one()
        values = super()._prepare_mail_values_dynamic(res_ids)
        values[res_ids[0]]["gateway_notifications"] = [
            {
                "partner_id": channel.partner_id.id,
                "channel_type": "gateway",
                "gateway_channel_id": channel.id,
            }
            for channel in self.wizard_channel_ids
        ]
        return values

    def _prepare_mail_values_static(self):
        values = super()._prepare_mail_values_static()
        values["gateway_notifications"] = [
            {
                "partner_id": channel.partner_id.id,
                "channel_type": "gateway",
                "gateway_channel_id": channel.id,
            }
            for channel in self.wizard_channel_ids
        ]
        return values
