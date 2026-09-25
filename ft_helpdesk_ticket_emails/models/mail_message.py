from odoo import api, models

from .ticket import HELPDESK_EMAIL_FROM, LEGACY_EMAIL_FROM


class MailMessage(models.Model):
    _inherit = 'mail.message'

    @api.model_create_multi
    def create(self, vals_list):
        """Send every helpdesk mail from the support address.

        ft_helpdesk_core stamps admin@fingertipplus.com onto every ticket
        message in its message_post/message_notify overrides and in its own mail
        templates. That module can't be upgraded on this database, so the
        address is corrected here instead - narrowly, only where the legacy
        address was applied to a helpdesk ticket message, so a real author's
        email is never rewritten.
        """
        for vals in vals_list:
            if (vals.get('model') == 'ft.helpdesk.ticket'
                    and vals.get('email_from') == LEGACY_EMAIL_FROM):
                vals['email_from'] = HELPDESK_EMAIL_FROM
        return super().create(vals_list)
