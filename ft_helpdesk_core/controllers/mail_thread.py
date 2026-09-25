from werkzeug.exceptions import NotFound

from odoo import http
from odoo.fields import Domain
from odoo.http import request
from odoo.addons.mail.controllers.thread import ThreadController
from odoo.addons.mail.tools.discuss import Store


class FtHelpdeskThreadController(ThreadController):

    @http.route("/mail/thread/messages", methods=["POST"], type="jsonrpc", auth="user")
    def mail_thread_messages(self, thread_model, thread_id, fetch_params=None):
        if thread_model != 'ft.helpdesk.ticket':
            return super().mail_thread_messages(
                thread_model, thread_id, fetch_params=fetch_params,
            )

        thread = self._get_thread_with_access(thread_model, thread_id, mode="read")
        if not thread:
            raise NotFound()

        # Customer comments/emails are shown in the ticket's Conversation tab,
        # so they are kept out of the chatter. Everything else - tracked field
        # changes, status changes, notes, activities, agent replies - stays.
        domain = None
        if thread.customer_id:
            domain = ~(
                Domain('author_id', '=', thread.customer_id.id)
                & Domain('message_type', 'in', ('comment', 'email'))
            )

        res = request.env["mail.message"]._message_fetch(
            domain=domain, thread=thread, **(fetch_params or {}),
        )
        messages = res.pop("messages")
        if not request.env.user._is_public():
            messages.set_message_done()
        return {
            **res,
            "data": Store().add(messages).get_result(),
            "messages": messages.ids,
        }
