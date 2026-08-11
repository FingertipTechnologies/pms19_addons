import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class SLAStatus(models.Model):
    _name = 'ft.helpdesk.sla.status'
    _description = 'Helpdesk SLA Status (per ticket)'
    _order = 'create_date desc'

    ticket_id = fields.Many2one(
        'ft.helpdesk.ticket', string='Ticket',
        required=True, ondelete='cascade', index=True,
    )
    policy_id = fields.Many2one(
        'ft.helpdesk.sla.policy', string='SLA Policy',
        required=True, ondelete='cascade',
    )

    # Deadlines
    first_response_deadline = fields.Datetime(
        string='First Response Deadline', readonly=True,
    )
    resolution_deadline = fields.Datetime(
        string='Resolution Deadline', readonly=True,
    )

    # Completion timestamps
    first_response_done_at = fields.Datetime(
        string='First Response Done At', readonly=True,
    )
    resolution_done_at = fields.Datetime(
        string='Resolution Done At', readonly=True,
    )

    # Breach flags
    first_response_breached = fields.Boolean(
        string='First Response Breached', default=False,
    )
    resolution_breached = fields.Boolean(
        string='Resolution Breached', default=False,
    )

    # Computed
    first_response_remaining = fields.Float(
        string='First Response Remaining (hours)',
        compute='_compute_remaining',
    )
    resolution_remaining = fields.Float(
        string='Resolution Remaining (hours)',
        compute='_compute_remaining',
    )
    sla_state = fields.Selection([
        ('on_track', 'On Track'),
        ('at_risk', 'At Risk'),
        ('breached', 'Breached'),
        ('completed', 'Completed'),
    ], string='SLA Status', compute='_compute_sla_state', store=True)

    @api.depends('first_response_deadline', 'resolution_deadline',
                 'first_response_done_at', 'resolution_done_at',
                 'first_response_breached', 'resolution_breached')
    def _compute_remaining(self):
        now = fields.Datetime.now()
        for status in self:
            # First response remaining
            if status.first_response_done_at:
                status.first_response_remaining = 0
            elif status.first_response_deadline:
                delta = status.first_response_deadline - now
                status.first_response_remaining = delta.total_seconds() / 3600.0
            else:
                status.first_response_remaining = 0

            # Resolution remaining
            if status.resolution_done_at:
                status.resolution_remaining = 0
            elif status.resolution_deadline:
                delta = status.resolution_deadline - now
                status.resolution_remaining = delta.total_seconds() / 3600.0
            else:
                status.resolution_remaining = 0

    @api.depends('first_response_breached', 'resolution_breached',
                 'first_response_done_at', 'resolution_done_at',
                 'first_response_deadline', 'resolution_deadline')
    def _compute_sla_state(self):
        now = fields.Datetime.now()
        for status in self:
            # Check breached flags (set by cron) OR real-time deadline check
            fr_breached = status.first_response_breached or (
                status.first_response_deadline
                and not status.first_response_done_at
                and now > status.first_response_deadline
            )
            res_breached = status.resolution_breached or (
                status.resolution_deadline
                and not status.resolution_done_at
                and now > status.resolution_deadline
            )

            if fr_breached or res_breached:
                # Also update the breach flags so cron doesn't need to catch up
                vals = {}
                if fr_breached and not status.first_response_breached:
                    vals['first_response_breached'] = True
                if res_breached and not status.resolution_breached:
                    vals['resolution_breached'] = True
                if vals:
                    status.sudo().write(vals)
                status.sla_state = 'breached'
            elif status.first_response_done_at and status.resolution_done_at:
                status.sla_state = 'completed'
            else:
                # Check if at risk (within 25% of deadline)
                at_risk = False
                if (status.first_response_deadline and not status.first_response_done_at):
                    remaining = (status.first_response_deadline - now).total_seconds()
                    total = (status.first_response_deadline - status.create_date).total_seconds()
                    if total > 0 and remaining / total < 0.25:
                        at_risk = True
                if (status.resolution_deadline and not status.resolution_done_at):
                    remaining = (status.resolution_deadline - now).total_seconds()
                    total = (status.resolution_deadline - status.create_date).total_seconds()
                    if total > 0 and remaining / total < 0.25:
                        at_risk = True
                status.sla_state = 'at_risk' if at_risk else 'on_track'

    @api.model
    def _create_for_ticket(self, ticket):
        """Find matching SLA policy and create SLA status for a ticket."""
        policies = self.env['ft.helpdesk.sla.policy'].search([
            ('active', '=', True),
        ], order='sequence')

        for policy in policies:
            if policy._match_ticket(ticket):
                now = fields.Datetime.now()

                # Compute deadlines
                if policy.business_hours_id:
                    bh = policy.business_hours_id
                    fr_deadline = bh._add_business_hours(
                        now, policy.first_response_hours)
                    res_deadline = bh._add_business_hours(
                        now, policy.resolution_hours)
                else:
                    fr_deadline = now + timedelta(hours=policy.first_response_hours)
                    res_deadline = now + timedelta(hours=policy.resolution_hours)

                self.create({
                    'ticket_id': ticket.id,
                    'policy_id': policy.id,
                    'first_response_deadline': fr_deadline,
                    'resolution_deadline': res_deadline,
                })
                return True  # Use first matching policy
        return False

    @api.model
    def _cron_check_sla_breaches(self):
        """Cron job: check for SLA breaches and trigger escalations."""
        now = fields.Datetime.now()

        # Check first response breaches
        fr_breached = self.search([
            ('first_response_breached', '=', False),
            ('first_response_done_at', '=', False),
            ('first_response_deadline', '<', now),
            ('ticket_id.state', 'not in', ('closed', 'cancelled')),
        ])
        for status in fr_breached:
            status.first_response_breached = True
            _logger.info('SLA first response breached for ticket %s',
                         status.ticket_id.ticket_no)
            self._handle_breach(status, 'first_response')

        # Check resolution breaches
        res_breached = self.search([
            ('resolution_breached', '=', False),
            ('resolution_done_at', '=', False),
            ('resolution_deadline', '<', now),
            ('ticket_id.state', 'not in', ('closed', 'cancelled')),
        ])
        for status in res_breached:
            status.resolution_breached = True
            _logger.info('SLA resolution breached for ticket %s',
                         status.ticket_id.ticket_no)
            self._handle_breach(status, 'resolution')

    def _handle_breach(self, status, breach_type):
        """Handle SLA breach: escalate and notify."""
        ticket = status.ticket_id
        policy = status.policy_id

        breach_label = 'First Response' if breach_type == 'first_response' else 'Resolution'

        # Post internal note
        ticket.message_post(
            body=_('SLA Breach: %s deadline exceeded. Policy: %s') % (
                breach_label, policy.name),
            subtype_xmlid='ft_helpdesk_core.mt_ticket_internal_note',
            message_type='notification',
        )

        # Escalate if configured
        if policy.escalate_on_breach:
            ticket.action_escalate()

        # Notify users
        if policy.notify_user_ids:
            for user in policy.notify_user_ids:
                ticket.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=_('SLA %s Breached: %s') % (
                        breach_label, ticket.ticket_no),
                    note=_('SLA policy "%s" %s deadline has been breached for ticket %s.') % (
                        policy.name, breach_label.lower(), ticket.ticket_no),
                )
