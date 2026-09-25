import logging

from markupsafe import Markup

from odoo import api, fields, models, tools, _

_logger = logging.getLogger(__name__)

# Every helpdesk mail goes out as this address. ft_helpdesk_core hardcodes
# admin@fingertipplus.com in its message_post/message_notify overrides and in
# its own mail templates, so LEGACY_EMAIL_FROM is rewritten to it wherever it
# turns up on a ticket message (see models/mail_message.py).
HELPDESK_EMAIL_FROM = 'support@fingertipplus.com'
LEGACY_EMAIL_FROM = 'admin@fingertipplus.com'

# Wording for the single "Ticket Emails" notification, keyed by the event that
# triggered it. Passed through the context to the mail template: the first
# item heads the subject, the second opens the body. A stage change and a
# customer reply are both "Ticket Updated" - they are the two things the
# requested subject list groups under that heading.
TICKET_EVENT_WORDING = {
    'created': (
        'Ticket Created',
        'A new helpdesk ticket has been created.',
    ),
    'escalated': (
        'Ticket Escalated',
        'This helpdesk ticket has been escalated and needs attention.',
    ),
    'closed': (
        'Ticket Closed',
        'This helpdesk ticket has been closed.',
    ),
    'cancelled': (
        'Ticket Cancelled',
        'This helpdesk ticket has been cancelled.',
    ),
    'stage': (
        'Ticket Updated',
        'The status of this helpdesk ticket has changed.',
    ),
    'conversation': (
        'Ticket Updated',
        'A new message has been posted on this helpdesk ticket.',
    ),
}


class HelpdeskTicket(models.Model):
    _inherit = 'ft.helpdesk.ticket'

    # =====================
    # Recipients & sending
    # =====================

    def _ft_ticket_email_recipients(self):
        """Every address that should receive this ticket's event email.

        Order is stable and meaningful - customer, assignee, team lead, PM,
        then the users configured in Settings - and duplicates are dropped
        case-insensitively so someone holding two roles is still listed once.
        """
        self.ensure_one()
        company = (self.company_id or self.env.company).sudo()
        emails = []
        seen = set()

        def _add(value):
            for addr in tools.email_split(value or ''):
                if addr.lower() not in seen:
                    seen.add(addr.lower())
                    emails.append(addr)

        if company.helpdesk_ticket_email_to_customer:
            _add(self.customer_id.email or self.customer_email)
        if company.helpdesk_ticket_email_to_assignee:
            _add(self.assigned_user_id.email)
        team = self.team_id
        if team and company.helpdesk_ticket_email_to_team_lead:
            _add(team.leader_user_id.email)
        if team and company.helpdesk_ticket_email_to_pm:
            _add(team.pm_user_id.email)
        for user in company.helpdesk_ticket_email_user_ids:
            _add(user.email)
        return emails

    def _send_ticket_event_email(self, event, detail=None, detail_title=None):
        """Send ONE email for a ticket event to every configured recipient.

        The whole recipient list rides in Cc of a single mail.mail and
        ``recipient_ids`` is deliberately left empty: Odoo splits a mail into
        one outgoing message per entry in ``recipient_ids``, which is exactly
        the per-person fan-out this feature must avoid.

        Callers that already notify about the same user action pass
        ``ft_skip_ticket_event_email`` in the context to avoid a second mail.
        """
        if self.env.context.get('ft_skip_ticket_event_email'):
            return
        template = self.env.ref(
            'ft_helpdesk_ticket_emails.mt_ticket_event_email_template',
            raise_if_not_found=False,
        )
        if not template:
            return
        label, intro = TICKET_EVENT_WORDING.get(
            event, TICKET_EVENT_WORDING['stage'])
        for ticket in self:
            company = (ticket.company_id or self.env.company).sudo()
            if not company.helpdesk_ticket_emails:
                continue
            recipients = ticket._ft_ticket_email_recipients()
            if not recipients:
                continue
            try:
                rendering = template.sudo().with_context(
                    ft_event=event,
                    ft_event_label=label,
                    ft_event_intro=intro,
                    ft_event_detail=detail,
                    ft_event_detail_title=detail_title,
                )
                body = rendering._render_field('body_html', ticket.ids)[ticket.id]
                subject = rendering._render_field('subject', ticket.ids)[ticket.id]
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': body,
                    'email_from': HELPDESK_EMAIL_FROM,
                    'reply_to': HELPDESK_EMAIL_FROM,
                    # A message needs a To; the recipients themselves all go in
                    # Cc, as configured.
                    'email_to': company.email or HELPDESK_EMAIL_FROM,
                    'email_cc': ', '.join(recipients),
                    'model': 'ft.helpdesk.ticket',
                    'res_id': ticket.id,
                    'auto_delete': True,
                })
            except Exception:
                _logger.warning(
                    'Failed to send %s ticket email for ticket %s',
                    event, ticket.ticket_no, exc_info=True,
                )

    # =====================
    # Event hooks
    # =====================

    @api.model_create_multi
    def create(self, vals_list):
        # The assignee is in Cc of the "Ticket Created" mail, so the core's
        # separate "you've been assigned" mail is skipped during creation
        # (see _notify_assignee). Later reassignments still send it.
        tickets = super(
            HelpdeskTicket, self.with_context(ft_ticket_creating=True),
        ).create(vals_list).with_env(self.env)
        for ticket in tickets:
            ticket._send_ticket_event_email('created')
        return tickets

    def write(self, vals):
        state_changed = 'state' in vals
        old_states = {t.id: t.state for t in self} if state_changed else {}
        result = super().write(vals)
        # Sent after super() so the mail renders the ticket as it now stands,
        # including the closed_at / resolved_at timestamps set by the core.
        if state_changed:
            states = dict(self._fields['state'].selection)
            for ticket in self:
                old_state = old_states.get(ticket.id)
                if ticket.state == old_state:
                    continue
                event = ticket.state if ticket.state in (
                    'closed', 'cancelled') else 'stage'
                ticket._send_ticket_event_email(
                    event,
                    detail='%s → %s' % (
                        states.get(old_state, ''), states.get(ticket.state, '')),
                    detail_title=_('Status Change'),
                )
        return result

    def action_escalate(self):
        """Manual Escalate button and the SLA-breach cron both land here."""
        result = super().action_escalate()
        for ticket in self:
            escalated_to = ticket.team_id.leader_user_id.name
            ticket._send_ticket_event_email(
                'escalated',
                detail=_('Escalation level %s.%s') % (
                    ticket.escalation_level,
                    _(' Escalated to: %s') % escalated_to if escalated_to else '',
                ),
                detail_title=_('Escalation'),
            )
        return result

    def _notify_get_reply_to(self, default=None, author_id=False):
        """Replies come back to the support mailbox, not the admin one."""
        return dict.fromkeys(self.ids, HELPDESK_EMAIL_FROM)

    def _ft_ticket_emails_on(self):
        """True when Ticket Emails is enabled for the company of every ticket
        in self - i.e. when the single Cc'd mail is THE notification."""
        return bool(self) and all(
            (ticket.company_id or self.env.company).sudo().helpdesk_ticket_emails
            for ticket in self
        )

    def _notify_get_recipients(self, message, msg_vals=False, **kwargs):
        """Drop the per-person notifications the single Cc'd mail replaces.

        ft_helpdesk_core posts three kinds of ticket message that Odoo then
        fans out into one email per recipient:

          * the status change - one mail per follower group, five for a
            single change;
          * the creation confirmation, posted to the customer - which also
            reached every follower subscribed to new tickets;
          * a public reply - mailed separately to the customer and to each
            follower, the project manager among them.

        Each of those events already sends this module's one email with
        everyone in Cc, so with Ticket Emails on the customer and the project
        manager were getting the same event twice - once on their own and once
        in the Cc'd mail. The separate copies are suppressed; the messages
        themselves still land in the chatter. With Ticket Emails off, nothing
        is suppressed and the core notifications are the only ones sent.
        """
        recipients = super()._notify_get_recipients(
            message, msg_vals=msg_vals, **kwargs)
        replaced = {
            subtype.id
            for xmlid in (
                'ft_helpdesk_core.mt_ticket_state_change',
                'ft_helpdesk_core.mt_ticket_new',
                'ft_helpdesk_core.mt_ticket_public_reply',
            )
            if (subtype := self.env.ref(xmlid, raise_if_not_found=False))
        }
        subtype_id = (msg_vals or {}).get('subtype_id') or message.subtype_id.id
        if subtype_id not in replaced or not self._ft_ticket_emails_on():
            return recipients
        return []

    def _notify_assignee(self):
        """Skip the core "you've been assigned" mail on ticket creation when
        the assignee is already copied on the "Ticket Created" mail."""
        if self.env.context.get('ft_ticket_creating') and self._ft_ticket_emails_on():
            company = (self.company_id or self.env.company).sudo()
            if company.helpdesk_ticket_email_to_assignee:
                return
        return super()._notify_assignee()

    def _notify_project_manager(self):
        """Keep the project manager following the ticket - so it stays in
        their chatter and discuss inbox - but send no separate email while
        Ticket Emails is on: the ticket's one Cc'd mail is the only
        notification sent."""
        if not self._ft_ticket_emails_on():
            return super()._notify_project_manager()
        self.ensure_one()
        manager = self.project_id.user_id
        partner = manager.partner_id
        if manager and manager.id != self.env.uid and partner \
                and partner not in self.message_partner_ids:
            self.message_subscribe(partner_ids=partner.ids)

    def message_post(self, **kwargs):
        # ft_helpdesk_core reopens a pending_customer ticket when the customer
        # replies. That nested write must not also fire a status email - the
        # conversation email sent below already reports the new status, and one
        # customer reply must not produce two mails.
        message = super(
            HelpdeskTicket,
            self.with_context(ft_skip_ticket_event_email=True),
        ).message_post(**kwargs)
        # Customer conversation only, so internal notes, status notifications
        # and the creation confirmation are all left out.
        public_reply = self.env.ref(
            'ft_helpdesk_core.mt_ticket_public_reply', raise_if_not_found=False)
        if public_reply and message.subtype_id == public_reply:
            self._send_ticket_event_email(
                'conversation',
                # Already sanitized by mail.message; mark it safe so the
                # template renders the reply as HTML instead of escaping it.
                detail=Markup(message.body or ''),
                detail_title=_('Message from %s') % (
                    message.author_id.name or _('Unknown')),
            )
        return message
