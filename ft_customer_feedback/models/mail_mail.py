# -*- coding: utf-8 -*-
from odoo import models

RECIPIENT_MODEL = "ft.feedback.request.recipient"


class MailMail(models.Model):
    _inherit = "mail.mail"

    def _postprocess_sent_message(self, success_pids, success_emails,
                                  failure_reason=False, failure_type=None):
        """Update the email status of the feedback request recipients as soon
        as the mail queue has sent (or failed to send) their email, so the
        request status is kept current without any extra cron."""
        res = super()._postprocess_sent_message(
            success_pids, success_emails,
            failure_reason=failure_reason, failure_type=failure_type,
        )
        if self:
            self.env[RECIPIENT_MODEL].sudo().search([
                ("mail_id", "in", self.ids),
                ("email_state", "=", "queued"),
            ])._ft_sync_email_states()
        return res
