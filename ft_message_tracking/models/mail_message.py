from odoo import models


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _send_to_gateway_thread(self, gateway_channel_id):
        gateway = gateway_channel_id.gateway_id
        if not gateway._get_channel_id(gateway_channel_id.gateway_token):
            self._ft_ensure_gateway_channel(gateway_channel_id)
        return super()._send_to_gateway_thread(gateway_channel_id)

    def _ft_ensure_gateway_channel(self, gateway_channel_id):
        gateway = gateway_channel_id.gateway_id
        token = gateway_channel_id.gateway_token
        partner = gateway_channel_id.partner_id
        gateway_service = "mail.gateway.%s" % gateway.gateway_type
        if gateway_service not in self.env:
            return
        update = {
            "contacts": [{
                "wa_id": token,
                "profile": {
                    "name": partner.display_name if partner else token,
                },
            }],
            "messages": [{"from": token}],
        }
        self.env[gateway_service].sudo()._get_channel(
            gateway, token, update, force_create=True,
        )
