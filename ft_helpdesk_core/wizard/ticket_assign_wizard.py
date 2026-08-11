from odoo import fields, models


class TicketAssignWizard(models.TransientModel):
    _name = 'ft.helpdesk.ticket.assign.wizard'
    _description = 'Assign Tickets Wizard'

    ticket_ids = fields.Many2many('ft.helpdesk.ticket', string='Tickets')
    assigned_user_id = fields.Many2one(
        'res.users', string='Assignee', required=True,
        domain="[('share', '=', False)]",
    )
    team_id = fields.Many2one('ft.helpdesk.team', string='Team')

    def action_confirm(self):
        """Assign selected tickets to user/team."""
        vals = {'assigned_user_id': self.assigned_user_id.id}
        if self.team_id:
            vals['team_id'] = self.team_id.id
        for ticket in self.ticket_ids:
            if ticket.state == 'new':
                vals['state'] = 'open'
            ticket.write(vals)
        return {'type': 'ir.actions.act_window_close'}
