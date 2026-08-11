from odoo import api, fields, models, _


class TicketCloseWizard(models.TransientModel):
    _name = 'ft.helpdesk.ticket.close.wizard'
    _description = 'Close/Cancel Ticket Wizard'

    ticket_id = fields.Many2one('ft.helpdesk.ticket', string='Ticket')
    ticket_ids = fields.Many2many('ft.helpdesk.ticket', string='Tickets')
    is_cancel = fields.Boolean(string='Is Cancellation', default=False)
    close_reason_id = fields.Many2one(
        'ft.helpdesk.close.reason', string='Reason', required=True,
    )
    resolution_summary = fields.Text(string='Resolution Summary')

    @api.onchange('is_cancel')
    def _onchange_is_cancel(self):
        if self.is_cancel:
            return {'domain': {'close_reason_id': [('is_cancel_reason', '=', True)]}}
        return {'domain': {'close_reason_id': [('is_cancel_reason', '=', False)]}}

    def action_confirm(self):
        """Close or cancel the ticket(s) with reason."""
        tickets = self.ticket_id | self.ticket_ids
        state = 'cancelled' if self.is_cancel else 'closed'
        vals = {
            'state': state,
            'close_reason_id': self.close_reason_id.id,
        }
        if self.resolution_summary:
            vals['resolution_summary'] = self.resolution_summary
        tickets.write(vals)
        # Post a note about the close/cancel
        action_word = _('cancelled') if self.is_cancel else _('closed')
        for ticket in tickets:
            ticket.message_post(
                body=_('Ticket %s. Reason: %s') % (action_word, self.close_reason_id.name),
                subtype_xmlid='ft_helpdesk_core.mt_ticket_state_change',
                message_type='notification',
            )
        return {'type': 'ir.actions.act_window_close'}
