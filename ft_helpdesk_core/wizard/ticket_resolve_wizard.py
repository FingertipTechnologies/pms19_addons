from odoo import _, fields, models


class TicketResolveWizard(models.TransientModel):
    _name = 'ft.helpdesk.ticket.resolve.wizard'
    _description = 'Resolve Ticket Wizard'

    ticket_id = fields.Many2one('ft.helpdesk.ticket', string='Ticket')
    resolution_summary = fields.Text(string='Resolution Summary', required=True)

    def action_confirm(self):
        vals = {'state': 'resolved'}
        if self.resolution_summary:
            vals['resolution_summary'] = self.resolution_summary
        self.ticket_id.write(vals)
        self.ticket_id.message_post(
            body=_('Ticket resolved.'),
            subtype_xmlid='ft_helpdesk_core.mt_ticket_state_change',
            message_type='notification',
        )
        return {'type': 'ir.actions.act_window_close'}
