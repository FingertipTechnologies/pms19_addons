from odoo import api, fields, models

# Statuses a developer sets that the reporter must verify (popup + inbox).
RESOLVED_STATUSES = ('fixed', 'unable_to_reproduce', 'rejected', 'duplicate', 'known_issue')


class BugNotification(models.Model):
    _name = 'qa_testapp.bug_notification'
    _description = 'Bug App Notification'
    _order = 'id'

    ticket_id = fields.Many2one('qa_testapp.ticket', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('assigned', 'Bug Assigned'), ('fixed', 'Bug Fixed')], required=True)
    seen = fields.Boolean(default=False, index=True)

    @api.model
    def pending_popups(self):
        notices = self.search([('user_id', '=', self.env.uid), ('seen', '=', False)], limit=100)
        tickets = self.env['qa_testapp.ticket'].search([('id', 'in', notices.ticket_id.ids)])
        accessible = {ticket.id: ticket for ticket in tickets}
        result = []
        for notice in notices:
            ticket = accessible.get(notice.ticket_id.id)
            if not ticket:
                continue
            relevant = (ticket.assignee_id == self.env.user and ticket.approval_state == 'approved'
                        and ticket.status in ('open', 'in_progress', 'reopened')) if notice.kind == 'assigned' else (
                            ticket.reporter_id == self.env.user and ticket.status in RESOLVED_STATUSES)
            if not relevant:
                notice.sudo().write({'seen': True})
                continue
            if notice.kind == 'assigned':
                title = 'Bug assigned to you'
            else:
                label = dict(ticket._fields['status']._description_selection(self.env)).get(ticket.status)
                title = 'Bug marked %s — please verify' % label
            result.append({'id': notice.id, 'ticket_id': ticket.id, 'kind': notice.kind,
                           'title': title,
                           'message': '%s — %s' % (ticket.bug_id, ticket.title)})
        return result

    def dismiss_popup(self):
        # RPC callers cannot acknowledge somebody else's notification.
        notices = self.search([('id', 'in', self.ids), ('user_id', '=', self.env.uid)])
        notices.sudo().write({'seen': True})
        return True
