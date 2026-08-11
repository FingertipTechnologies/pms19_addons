from odoo import http
from odoo.http import request
from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tools.discuss import Store


class FtHelpdeskThreadController(ThreadController):

    @http.route("/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_messages(self, thread_model, thread_id, search_term=None,
                             before=None, after=None, around=None, limit=30):
        if thread_model != 'ft.helpdesk.ticket':
            return super().mail_thread_messages(
                thread_model, thread_id,
                search_term=search_term, before=before,
                after=after, around=around, limit=limit,
            )

        # For helpdesk tickets, exclude customer comment/email messages from chatter
        ticket = request.env['ft.helpdesk.ticket'].browse(int(thread_id))
        customer_partner_id = ticket.customer_id.id if ticket.exists() and ticket.customer_id else False

        domain = [
            ("res_id", "=", int(thread_id)),
            ("model", "=", thread_model),
            ("message_type", "!=", "user_notification"),
        ]

        # Exclude customer messages from chatter
        if customer_partner_id:
            domain += [
                '!', '&',
                ('author_id', '=', customer_partner_id),
                ('message_type', 'in', ('comment', 'email')),
            ]

        res = request.env["mail.message"]._message_fetch(
            domain, search_term=search_term, before=before,
            after=after, around=around, limit=limit,
        )
        messages = res.pop("messages")
        if not request.env.user._is_public():
            messages.set_message_done()
        return {
            **res,
            "data": Store(messages, for_current_user=True).get_result(),
            "messages": Store.many_ids(messages),
        }
