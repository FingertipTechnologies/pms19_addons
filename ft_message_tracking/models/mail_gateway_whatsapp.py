from odoo import models
from odoo.tools import html2plaintext


class MailGatewayWhatsappService(models.AbstractModel):
    _inherit = "mail.gateway.whatsapp"

    def _send(
        self,
        gateway,
        record,
        auto_commit=False,
        raise_exception=False,
        parse_mode=False,
    ):
        result = super()._send(
            gateway,
            record,
            auto_commit=auto_commit,
            raise_exception=raise_exception,
            parse_mode=parse_mode,
        )
        if record.notification_status == "sent" and record.gateway_message_id:
            self._ft_log_outbound_whatsapp(gateway, record)
        return result

    def _ft_log_outbound_whatsapp(self, gateway, record):
        message = record.mail_message_id
        channel = record.gateway_channel_id
        to_number = channel.gateway_channel_token if channel else False
        partner_id = record.res_partner_id.id if record.res_partner_id else False
        if not partner_id and to_number:
            gw_partner = self.env["res.partner.gateway.channel"].sudo().search(
                [("gateway_id", "=", gateway.id),
                 ("gateway_token", "=", to_number)],
                limit=1,
            )
            partner_id = gw_partner.partner_id.id if gw_partner else False
        subject = message.subject if message and message.subject else False
        if not subject and message and message.body:
            preview = html2plaintext(message.body).strip()
            subject = (preview[:100] + "…") if len(preview) > 100 else preview
        self.env["ft.message.tracking"].sudo().create({
            "message_type": "whatsapp",
            "from_number": gateway.whatsapp_from_phone,
            "to_number": to_number,
            "partner_id": partner_id,
            "subject": subject or False,
            "external_message_id": record.gateway_message_id,
        })

    def _receive_update(self, gateway, update):
        result = super()._receive_update(gateway, update)
        if not update:
            return result
        for entry in update.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                for message in value.get("messages", []):
                    self._ft_log_inbound_whatsapp(gateway, message, value)
                for status_info in value.get("statuses", []):
                    if status_info.get("status") == "read":
                        self._ft_register_whatsapp_read(status_info)
        return result

    def _ft_register_whatsapp_read(self, status_info):
        external_id = status_info.get("id")
        if not external_id:
            return
        tracking = self.env["ft.message.tracking"].sudo().search(
            [
                ("external_message_id", "=", external_id),
                ("message_type", "=", "whatsapp"),
            ],
            limit=1,
        )
        if tracking:
            tracking.register_open()

    def _ft_log_inbound_whatsapp(self, gateway, message, value):
        from_number = message.get("from")
        if not from_number:
            return
        external_id = message.get("id")
        if external_id and self.env["ft.message.tracking"].sudo().search_count(
            [("external_message_id", "=", external_id),
             ("message_type", "=", "whatsapp"),
             ("direction", "=", "inbound")]
        ):
            return
        gw_channel = self.env["res.partner.gateway.channel"].sudo().search(
            [("gateway_id", "=", gateway.id),
             ("gateway_token", "=", from_number)],
            limit=1,
        )
        partner_id = gw_channel.partner_id.id if gw_channel else False
        subject = self._ft_extract_inbound_preview(message)
        self.env["ft.message.tracking"].sudo().create({
            "message_type": "whatsapp",
            "direction": "inbound",
            "from_number": from_number,
            "to_number": gateway.whatsapp_from_phone,
            "partner_id": partner_id,
            "subject": subject or False,
            "external_message_id": external_id or False,
        })

    def _ft_extract_inbound_preview(self, message):
        text = ""
        if message.get("text"):
            text = message["text"].get("body") or ""
        elif message.get("image"):
            text = message["image"].get("caption") or "[Image]"
        elif message.get("video"):
            text = message["video"].get("caption") or "[Video]"
        elif message.get("audio"):
            text = "[Audio]"
        elif message.get("document"):
            doc = message["document"]
            text = doc.get("caption") or doc.get("filename") or "[Document]"
        elif message.get("sticker"):
            text = "[Sticker]"
        elif message.get("location"):
            text = "[Location]"
        elif message.get("contacts"):
            text = "[Contact card]"
        text = text.strip()
        return (text[:100] + "…") if len(text) > 100 else text

    def _get_author(self, gateway, update):
        author = super()._get_author(gateway, update)
        if not author or author._name != "mail.guest":
            return author
        author_id = (update.get("messages") or [{}])[0].get("from")
        if not author_id:
            return author
        name = None
        for contact in update.get("contacts", []) or []:
            if contact.get("wa_id") == author_id:
                name = (contact.get("profile") or {}).get("name")
                break
        partner = self.env["res.partner"].sudo().create({
            "name": name or f"WhatsApp +{author_id}",
            "phone": "+" + str(author_id),
        })
        self.env["res.partner.gateway.channel"].sudo().create({
            "name": gateway.name,
            "partner_id": partner.id,
            "gateway_id": gateway.id,
            "gateway_token": str(author_id),
        })
        author.sudo().unlink()
        return partner
