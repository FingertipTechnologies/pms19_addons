import logging
import re
from odoo import api, models, tools

_logger = logging.getLogger(__name__)

# Matches [TKT-000123], (TKT-000123), TKT-000123 etc. (case-insensitive)
TICKET_NO_REGEX = re.compile(r'(?:\[|\b)(TKT-\d{4,8})(?:\]|\b)', re.IGNORECASE)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_route(self, message, message_dict, model=None, thread_id=None, custom_values=None):
        """Override message_route to identify ticket numbers in the email subject.

        - If the subject contains a valid existing ticket number (e.g. [TKT-000123]),
          route the email directly to that ticket so it updates the Chatter.
        - If no ticket number is present, route normally to create a new ticket.
        - If an invalid ticket number is present (e.g. [TKT-999999]), create a new ticket
          rather than linking to an unrelated ticket.
        """
        routes = super().message_route(
            message, message_dict, model=model, thread_id=thread_id, custom_values=custom_values
        )

        subject = message_dict.get('subject') or ''
        match = TICKET_NO_REGEX.search(subject)

        # Fallback: check In-Reply-To, References, or Message-ID for ticket reference
        if not match:
            for header_val in (
                message_dict.get('in_reply_to'),
                message_dict.get('references'),
                message_dict.get('message_id'),
            ):
                if header_val:
                    match = TICKET_NO_REGEX.search(str(header_val))
                    if match:
                        break

        if match:
            ticket_ref = match.group(1).upper()
            ticket = self.env['ft.helpdesk.ticket'].sudo().search([
                ('ticket_no', '=ilike', ticket_ref)
            ], limit=1)

            if ticket:
                _logger.info(
                    "Email-to-Ticket: Matched valid ticket reference %s (ID: %s) in subject '%s'. Routing to existing ticket Chatter.",
                    ticket_ref, ticket.id, subject
                )
                email_from = message_dict.get('email_from')
                user_id = self._mail_find_user_for_gateway(email_from).id or self.env.uid

                # If existing routes contain ft.helpdesk.ticket, update thread_id
                updated_routes = []
                replaced = False
                for r_model, r_thread_id, r_custom, r_user, r_alias in (routes or []):
                    if r_model == 'ft.helpdesk.ticket':
                        updated_routes.append(('ft.helpdesk.ticket', ticket.id, r_custom, r_user or user_id, r_alias))
                        replaced = True
                    else:
                        updated_routes.append((r_model, r_thread_id, r_custom, r_user, r_alias))

                if not replaced:
                    updated_routes = [('ft.helpdesk.ticket', ticket.id, custom_values or {}, user_id, None)]

                return updated_routes
            else:
                _logger.warning(
                    "Email-to-Ticket: Ticket reference %s in subject '%s' not found in database. Proceeding to create a new ticket.",
                    ticket_ref, subject
                )
                # Scenario 3: Ticket number does not exist.
                # If routes had assigned a thread_id on ft.helpdesk.ticket, clear it so a new ticket is created.
                new_routes = []
                for r_model, r_thread_id, r_custom, r_user, r_alias in (routes or []):
                    if r_model == 'ft.helpdesk.ticket':
                        new_routes.append(('ft.helpdesk.ticket', False, r_custom, r_user, r_alias))
                    else:
                        new_routes.append((r_model, r_thread_id, r_custom, r_user, r_alias))
                return new_routes

        return routes
