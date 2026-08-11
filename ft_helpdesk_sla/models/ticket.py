from datetime import timedelta

from odoo import api, fields, models


class HelpdeskTicketSLA(models.Model):
    _inherit = 'ft.helpdesk.ticket'

    sla_status_ids = fields.One2many(
        'ft.helpdesk.sla.status', 'ticket_id', string='SLA Status',
    )
    sla_state = fields.Selection([
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('breached', 'Breached'),
        ('completed', 'Completed'),
    ], string='SLA State', compute='_compute_sla_fields', store=False)
    sla_first_response_deadline = fields.Datetime(
        string='First Response Deadline',
        compute='_compute_sla_fields', store=False,
    )
    sla_resolution_deadline = fields.Datetime(
        string='Resolution Deadline',
        compute='_compute_sla_fields', store=False,
    )
    sla_breached = fields.Boolean(
        string='SLA Breached',
        compute='_compute_sla_fields', store=False,
    )

    @api.depends(
        'sla_status_ids',
        'sla_status_ids.first_response_deadline',
        'sla_status_ids.resolution_deadline',
        'sla_status_ids.first_response_breached',
        'sla_status_ids.resolution_breached',
        'sla_status_ids.sla_state',
    )
    def _compute_sla_fields(self):
        for ticket in self:
            status = ticket.sla_status_ids[:1]
            if status:
                ticket.sla_first_response_deadline = status.first_response_deadline
                ticket.sla_resolution_deadline = status.resolution_deadline
                ticket.sla_breached = (
                    status.first_response_breached or status.resolution_breached)
                ticket.sla_state = status.sla_state
            else:
                ticket.sla_first_response_deadline = False
                ticket.sla_resolution_deadline = False
                ticket.sla_breached = False
                ticket.sla_state = False

    @api.model_create_multi
    def create(self, vals_list):
        tickets = super().create(vals_list)
        for ticket in tickets:
            self.env['ft.helpdesk.sla.status']._create_for_ticket(ticket)
        return tickets

    def write(self, vals):
        result = super().write(vals)
        # Re-evaluate SLA when matching criteria change and no SLA exists yet
        sla_trigger_fields = {'team_id', 'category_id', 'type_id', 'priority'}
        if sla_trigger_fields & set(vals.keys()):
            for ticket in self:
                if not ticket.sla_status_ids:
                    self.env['ft.helpdesk.sla.status']._create_for_ticket(ticket)
        # Mark first response SLA as done
        if 'first_response_at' in vals and vals['first_response_at']:
            for ticket in self:
                for sla in ticket.sla_status_ids:
                    if not sla.first_response_done_at:
                        sla.first_response_done_at = vals['first_response_at']
        # Mark resolution SLA as done
        if vals.get('state') in ('resolved', 'closed'):
            now = fields.Datetime.now()
            for ticket in self:
                for sla in ticket.sla_status_ids:
                    if not sla.resolution_done_at:
                        sla.resolution_done_at = now
        return result

    @api.model
    def _cron_auto_close_tickets(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param('ft_helpdesk.auto_close_days', '0'))
        if days > 0:
            cutoff = fields.Datetime.now() - timedelta(days=days)
            tickets = self.search([
                ('state', '=', 'resolved'),
                ('resolved_at', '<', cutoff),
            ])
            for ticket in tickets:
                ticket.write({'state': 'closed'})
                ticket.message_post(
                    body='Ticket auto-closed after %d days in resolved state.' % days,
                    message_type='notification',
                    subtype_xmlid='ft_helpdesk_core.mt_ticket_state_change',
                )
