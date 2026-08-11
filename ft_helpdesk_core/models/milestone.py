from odoo import fields, models


class FtHelpdeskMilestone(models.Model):
    _name = 'ft.helpdesk.milestone'
    _description = 'Helpdesk Ticket Milestone'
    _order = 'deadline asc, id asc'

    name = fields.Char(string='Milestone', required=True)
    ticket_id = fields.Many2one(
        comodel_name='ft.helpdesk.ticket',
        string='Ticket',
        required=True,
        ondelete='cascade',
    )
    deadline = fields.Date(string='Deadline')
    is_reached = fields.Boolean(string='Reached', default=False)
    description = fields.Text(string='Description')
