import json
import logging
from datetime import timedelta
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

TICKET_STATES = [
    ('new', 'New'),
    ('open', 'In Progress'),
    ('pending_internal', 'Pending Internal'),
    ('pending_customer', 'Pending Customer'),
    ('resolved', 'Resolved'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]

# Labels use the customer-facing P1..P4 scheme. The stored keys are unchanged
# ('3' is still the most severe) so ordering, existing records and every
# domain filtering on '3'/'2' keep working. Note the numbering runs opposite
# to the keys: P1 is the most severe and maps to '3'.
PRIORITY_SELECTION = [
    ('0', 'P4 – Low'),
    ('1', 'P3 – Medium'),
    ('2', 'P2 – High'),
    ('3', 'P1 – Critical'),
]

CHANNEL_SELECTION = [
    ('portal', 'Portal'),
    ('email', 'Email'),
    ('internal', 'Internal'),
]


class HelpdeskTicket(models.Model):
    _name = 'ft.helpdesk.ticket'
    _description = 'Helpdesk Ticket'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'portal.mixin']
    _order = 'priority desc, create_date desc'
    _rec_name = 'display_name'

    # =====================
    # Core Fields
    # =====================
    name = fields.Char(
        string='Subject', required=True, tracking=True, index='trigram',
    )
    ticket_no = fields.Char(
        string='Ticket Number', readonly=True, copy=False,
        default='New', index=True,
    )
    display_name = fields.Char(
        string='Display Name', compute='_compute_display_name', store=True,
    )
    description = fields.Html(
        string='Description', sanitize_style=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer', required=True,
        tracking=True, index=True,
    )
    customer_email = fields.Char(
        string='Customer Email', related='customer_id.email',
        store=True, readonly=True,
    )
    customer_phone = fields.Char(
        string='Customer Phone', related='customer_id.phone',
        readonly=True,
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company,
        required=True, index=True,
    )

    color = fields.Integer(string='Color Index')

    # =====================
    # Classification
    # =====================
    team_id = fields.Many2one(
        'ft.helpdesk.team', string='Team', tracking=True, index=True,
    )
    assigned_user_id = fields.Many2one(
        'res.users', string='Assignee', tracking=True, index=True,
        domain="[('share', '=', False)]",
    )
    priority = fields.Selection(
        PRIORITY_SELECTION, string='Priority',
        default='1', tracking=True, index=True,
    )
    state = fields.Selection(
        TICKET_STATES, string='Status',
        default='new', required=True, tracking=True, index=True,
        group_expand='_group_expand_states',
    )
    type_id = fields.Many2one(
        'ft.helpdesk.ticket.type', string='Type', tracking=True,
    )
    category_id = fields.Many2one(
        'ft.helpdesk.category', string='Category', tracking=True,
    )
    subcategory_id = fields.Many2one(
        'ft.helpdesk.subcategory', string='Subcategory',
        domain="[('category_id', '=', category_id)]",
    )
    project_id = fields.Many2one(
        'project.project', string='Project', tracking=True,
    )
    product_id = fields.Many2one(
        'product.product', string='Related Product',
    )
    tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_helpdesk_ticket_tag_rel',
        'ticket_id', 'tag_id', string='Tags',
    )
    channel = fields.Selection(
        CHANNEL_SELECTION, string='Channel',
        default='portal', tracking=True,
    )

    # =====================
    # Dynamic Fields
    # =====================
    fieldset_id = fields.Many2one(
        related='type_id.fieldset_id', string='Fieldset', readonly=True,
    )
    dynamic_field_ids = fields.One2many(
        related='fieldset_id.field_ids', string='Dynamic Field Definitions',
        readonly=True,
    )
    dynamic_values = fields.Json(
        string='Dynamic Values', default=dict,
        help='JSON storage for dynamic form values.',
    )

    # =====================
    # Resolution & Close
    # =====================
    close_reason_id = fields.Many2one(
        'ft.helpdesk.close.reason', string='Close Reason',
    )
    resolution_summary = fields.Text(string='Resolution Summary')

    # =====================
    # Timestamps
    # =====================
    first_response_at = fields.Datetime(
        string='First Response At', readonly=True, copy=False,
    )
    resolved_at = fields.Datetime(
        string='Resolved At', readonly=True, copy=False,
    )
    closed_at = fields.Datetime(
        string='Closed At', readonly=True, copy=False,
    )
    cancelled_at = fields.Datetime(
        string='Cancelled At', readonly=True, copy=False,
    )
    due_date = fields.Datetime(string='Due Date', tracking=True)

    # =====================
    # Escalation
    # =====================
    is_escalated = fields.Boolean(
        string='Escalated', default=False, tracking=True,
    )
    escalation_level = fields.Integer(
        string='Escalation Level', default=0,
    )

    # =====================
    # Computed / Display
    # =====================
    age_hours = fields.Float(
        string='Age (Hours)', compute='_compute_age_hours',
        help='Hours since ticket creation.',
    )
    is_overdue = fields.Boolean(
        string='Overdue', compute='_compute_is_overdue',
        search='_search_is_overdue',
    )
    state_color = fields.Char(
        string='State Color', compute='_compute_state_color',
    )
    last_customer_reply_at = fields.Datetime(
        string='Last Customer Reply', readonly=True, copy=False,
    )
    last_agent_reply_at = fields.Datetime(
        string='Last Agent Reply', readonly=True, copy=False,
    )
    message_count = fields.Integer(
        string='Messages', compute='_compute_message_count',
    )
    customer_message_ids = fields.One2many(
        'mail.message', 'res_id', string='Customer Messages',
        compute='_compute_customer_messages',
    )

    # =====================
    # Portal
    # =====================
    access_token = fields.Char(string='Access Token', copy=False)

    # =====================
    # Computes
    # =====================

    @api.depends('ticket_no', 'name')
    def _compute_display_name(self):
        for ticket in self:
            if ticket.ticket_no and ticket.ticket_no != 'New':
                ticket.display_name = '[%s] %s' % (ticket.ticket_no, ticket.name)
            else:
                ticket.display_name = ticket.name

    def _compute_age_hours(self):
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.create_date:
                delta = now - ticket.create_date
                ticket.age_hours = delta.total_seconds() / 3600.0
            else:
                ticket.age_hours = 0.0

    def _compute_is_overdue(self):
        now = fields.Datetime.now()
        for ticket in self:
            ticket.is_overdue = (
                ticket.due_date and ticket.due_date < now
                and ticket.state not in ('resolved', 'closed', 'cancelled')
            )

    def _search_is_overdue(self, operator, value):
        now = fields.Datetime.now()
        if (operator == '=' and value) or (operator == '!=' and not value):
            return [
                ('due_date', '<', now),
                ('state', 'not in', ('resolved', 'closed', 'cancelled')),
            ]
        return [
            '|',
            ('due_date', '>=', now),
            ('due_date', '=', False),
        ]

    def _compute_state_color(self):
        color_map = {
            'new': '#6c757d',
            'open': '#0d6efd',
            'pending_customer': '#ffc107',
            'pending_internal': '#fd7e14',
            'resolved': '#198754',
            'closed': '#20c997',
            'cancelled': '#dc3545',
        }
        for ticket in self:
            ticket.state_color = color_map.get(ticket.state, '#6c757d')

    def _compute_message_count(self):
        for ticket in self:
            ticket.message_count = len(ticket.message_ids)

    def _compute_customer_messages(self):
        for ticket in self:
            ticket.customer_message_ids = ticket.message_ids.filtered(
                lambda msg: msg.message_type in ('comment', 'email')
                and not msg.is_internal
                and msg.subtype_id and not msg.subtype_id.internal
            )

    @api.model
    def _group_expand_states(self, states, domain):
        return [key for key, _ in TICKET_STATES]

    # =====================
    # CRUD Overrides
    # =====================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('ticket_no', 'New') == 'New':
                vals['ticket_no'] = self.env['ir.sequence'].next_by_code(
                    'ft.helpdesk.ticket') or 'New'
            # Auto-assign team from the customer's configured Support Team.
            # This takes priority over the ticket type's default team.
            if not vals.get('team_id') and vals.get('customer_id'):
                partner = self.env['res.partner'].browse(vals['customer_id'])
                customer_team = (
                    partner.commercial_partner_id.helpdesk_team_id
                    or partner.helpdesk_team_id
                )
                if customer_team:
                    vals['team_id'] = customer_team.id
            # Auto-assign team from type (fallback when the customer has no team)
            if not vals.get('team_id') and vals.get('type_id'):
                ticket_type = self.env['ft.helpdesk.ticket.type'].browse(vals['type_id'])
                if ticket_type.default_team_id:
                    vals['team_id'] = ticket_type.default_team_id.id
        tickets = super().create(vals_list)
        for ticket in tickets:
            # Auto-assign via round robin
            if (ticket.team_id and not ticket.assigned_user_id
                    and ticket.team_id.auto_assign_mode == 'round_robin'):
                assignee = ticket.team_id._get_next_assignee()
                if assignee:
                    ticket.assigned_user_id = assignee
            # Subscribe customer as follower and send creation confirmation
            if ticket.customer_id:
                ticket.message_subscribe(partner_ids=ticket.customer_id.ids)
                if ticket.customer_id.email:
                    try:
                        company = ticket.company_id or self.env.company
                        desc = ticket.description or 'N/A'
                        # Strip HTML tags from description for clean display
                        if hasattr(desc, '__str__'):
                            desc = str(desc)
                        body_html = (
                            '<div style="font-family: Arial, sans-serif; max-width: 600px;">'
                            '<p style="font-size: 15px;">Dear <strong>%s</strong>,</p>'
                            '<p style="font-size: 14px; color: #333;">Thank you for contacting us. '
                            'Your support ticket has been created successfully.</p>'
                            '<table style="border-collapse: collapse; width: 100%%; margin: 16px 0; '
                            'border: 1px solid #e0e0e0;">'
                            '<tr style="background-color: #f8f9fa;">'
                            '<td style="padding: 10px 14px; font-weight: bold; width: 150px; '
                            'border-bottom: 1px solid #e0e0e0; font-size: 13px; color: #555;">Ticket Number</td>'
                            '<td style="padding: 10px 14px; border-bottom: 1px solid #e0e0e0; '
                            'font-size: 14px; font-weight: 600; color: #6f42c1;">%s</td></tr>'
                            '<tr><td style="padding: 10px 14px; font-weight: bold; width: 150px; '
                            'border-bottom: 1px solid #e0e0e0; font-size: 13px; color: #555;">Subject</td>'
                            '<td style="padding: 10px 14px; border-bottom: 1px solid #e0e0e0; '
                            'font-size: 14px;">%s</td></tr>'
                            '<tr style="background-color: #f8f9fa;">'
                            '<td style="padding: 10px 14px; font-weight: bold; width: 150px; '
                            'font-size: 13px; color: #555; vertical-align: top;">Description</td>'
                            '<td style="padding: 10px 14px; font-size: 14px;">%s</td></tr>'
                            '</table>'
                            '<p style="font-size: 14px; color: #333;">Our support team will review '
                            'your request and get back to you as soon as possible.</p>'
                            '<p style="font-size: 14px; color: #333;">Best regards,<br/>'
                            '<strong>%s Support Team</strong></p></div>'
                        ) % (
                            ticket.customer_id.name,
                            ticket.ticket_no,
                            ticket.name,
                            desc,
                            company.name,
                        )
                        ticket.message_post(
                            body=Markup(body_html),
                            subject='Ticket %s - Confirmation' % ticket.ticket_no,
                            email_from='admin@fingertipplus.com',
                            partner_ids=ticket.customer_id.ids,
                            subtype_xmlid='ft_helpdesk_core.mt_ticket_new',
                            message_type='comment',
                        )
                    except Exception:
                        _logger.warning(
                            'Failed to send new-ticket email for ticket %s',
                            ticket.ticket_no, exc_info=True,
                        )
            # Notify the assigned internal user (covers both vals-set and
            # round-robin-set assignees). Skips self-assignment internally.
            ticket._notify_assignee()
        return tickets

    def write(self, vals):
        team_changed = 'team_id' in vals
        old_team_ids = (
            {t.id: t.team_id.id for t in self}
            if team_changed else {}
        )
        assignee_changed = 'assigned_user_id' in vals
        old_assignee_ids = (
            {t.id: t.assigned_user_id.id for t in self}
            if assignee_changed else {}
        )
        result = super().write(vals)
        # Track state-change timestamps
        if vals.get('state') == 'resolved':
            now = fields.Datetime.now()
            for ticket in self:
                if not ticket.resolved_at:
                    ticket.resolved_at = now
        elif vals.get('state') == 'closed':
            now = fields.Datetime.now()
            for ticket in self:
                if not ticket.closed_at:
                    ticket.closed_at = now
                if not ticket.resolved_at:
                    ticket.resolved_at = now
        elif vals.get('state') == 'cancelled':
            now = fields.Datetime.now()
            for ticket in self:
                if not ticket.cancelled_at:
                    ticket.cancelled_at = now
        # Auto-reassign when team changes. Mirrors the create() rule:
        #   round_robin team → _get_next_assignee() (rotates the counter)
        #   manual team with default_assignee_id → use it
        #   otherwise → clear, user picks manually
        # Skipped when the same write also sets assigned_user_id explicitly —
        # in that case respect the caller's choice.
        if team_changed and 'assigned_user_id' not in vals:
            for ticket in self:
                if ticket.team_id.id != old_team_ids.get(ticket.id):
                    new_assignee_id = False
                    team = ticket.team_id
                    if team:
                        if team.auto_assign_mode == 'round_robin':
                            next_user = team._get_next_assignee()
                            if next_user:
                                new_assignee_id = next_user.id
                        elif team.default_assignee_id:
                            new_assignee_id = team.default_assignee_id.id
                    # Setting via ORM triggers a recursive write that runs
                    # the assignee_changed branch below → notifies the new user.
                    ticket.assigned_user_id = new_assignee_id
        # Notify newly-assigned users when the assignee actually changed
        if assignee_changed:
            for ticket in self:
                if ticket.assigned_user_id.id != old_assignee_ids.get(ticket.id):
                    ticket._notify_assignee()
        return result

    # =====================
    # Actions
    # =====================

    def action_assign_to_me(self):
        """Assign ticket to current user and set to open if new."""
        for ticket in self:
            vals = {'assigned_user_id': self.env.uid}
            if ticket.state == 'new':
                vals['state'] = 'open'
            ticket.write(vals)

    def action_set_state_open(self):
        self.write({'state': 'open'})

    def action_set_state_pending_customer(self):
        self.write({'state': 'pending_customer'})

    def action_set_state_pending_internal(self):
        self.write({'state': 'pending_internal'})

    def action_set_state_resolved(self):
        return {
            'name': _('Resolve Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.helpdesk.ticket.resolve.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_id': self.id,
            },
        }

    def action_open_close_wizard(self):
        """Open close ticket wizard."""
        return {
            'name': _('Close Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.helpdesk.ticket.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_id': self.id,
                'default_is_cancel': False,
            },
        }

    def action_open_cancel_wizard(self):
        """Open cancel ticket wizard."""
        return {
            'name': _('Cancel Ticket'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.helpdesk.ticket.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_id': self.id,
                'default_is_cancel': True,
            },
        }

    def action_reopen(self):
        """Reopen a resolved/closed ticket."""
        for ticket in self:
            if ticket.state in ('resolved', 'closed', 'cancelled'):
                ticket.write({
                    'state': 'open',
                    'resolved_at': False,
                    'closed_at': False,
                    'cancelled_at': False,
                    'close_reason_id': False,
                })

    def action_escalate(self):
        """Escalate the ticket."""
        for ticket in self:
            ticket.write({
                'is_escalated': True,
                'escalation_level': ticket.escalation_level + 1,
                'priority': '3',  # Set to urgent
            })
            escalated_to = ''
            if ticket.team_id and ticket.team_id.leader_user_id:
                escalated_to = ticket.team_id.leader_user_id.name
            ticket.message_post(
                body=_('Ticket escalated to level %s.%s') % (
                    ticket.escalation_level,
                    _(' Escalated to: %s') % escalated_to if escalated_to else '',
                ),
                subtype_xmlid='ft_helpdesk_core.mt_ticket_internal_note',
                message_type='notification',
            )
            # Create planned activity for escalation
            notify_user = (
                ticket.team_id and ticket.team_id.leader_user_id
                or ticket.assigned_user_id
                or self.env.user
            )
            ticket.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=notify_user.id,
                summary=_('Escalated Ticket: %s') % ticket.ticket_no,
                note=_('Ticket %s has been escalated to level %s.') % (
                    ticket.ticket_no, ticket.escalation_level),
            )

    def action_request_info(self):
        """Move to pending_customer and prompt for a reply template."""
        self.write({'state': 'pending_customer'})

    def action_send_customer_reply(self):
        """Open a compose wizard to reply to the customer."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reply to Customer'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_model': 'ft.helpdesk.ticket',
                'default_res_ids': self.ids,
                'default_partner_ids': self.customer_id.ids if self.customer_id else [],
                'default_subtype_xmlid': 'ft_helpdesk_core.mt_ticket_public_reply',
                'default_email_from': 'admin@fingertipplus.com',
                'default_composition_mode': 'comment',
            },
        }

    # =====================
    # Mail Thread Overrides
    # =====================

    def _track_subtype(self, init_values):
        self.ensure_one()
        if 'state' in init_values:
            return self.env.ref('ft_helpdesk_core.mt_ticket_state_change')
        return super()._track_subtype(init_values)

    def message_post(self, **kwargs):
        """Override to track first response and customer replies."""
        kwargs['email_from'] = 'admin@fingertipplus.com'
        message = super().message_post(**kwargs)
        # Determine if this is a public reply by an agent
        subtype_id = kwargs.get('subtype_id')
        subtype_xmlid = kwargs.get('subtype_xmlid')
        is_internal = False
        if subtype_xmlid == 'ft_helpdesk_core.mt_ticket_internal_note':
            is_internal = True
        elif subtype_id:
            subtype = self.env['mail.message.subtype'].browse(subtype_id)
            if subtype == self.env.ref('ft_helpdesk_core.mt_ticket_internal_note', raise_if_not_found=False):
                is_internal = True

        if not is_internal and message.author_id:
            now = fields.Datetime.now()
            for ticket in self:
                # Agent reply
                if message.author_id != ticket.customer_id:
                    if not ticket.first_response_at:
                        ticket.first_response_at = now
                    ticket.last_agent_reply_at = now
                # Customer reply
                elif message.author_id == ticket.customer_id:
                    ticket.last_customer_reply_at = now
                    # Auto-reopen if pending_customer
                    if ticket.state == 'pending_customer':
                        ticket.state = 'open'
        return message

    def message_notify(self, **kwargs):
        """Force all helpdesk notifications (incl. activity-assigned emails)
        to be sent from admin@fingertipplus.com instead of the default."""
        kwargs['email_from'] = 'admin@fingertipplus.com'
        return super().message_notify(**kwargs)

    def _notify_assignee(self):
        """Send a short 'You've been assigned' email to assigned_user_id via
        message_notify (FYI to the assignee's partner; does not add them as a
        follower). No-op when there's no assignee, the assignee is the current
        user (self-assign), or they have no partner/email."""
        self.ensure_one()
        assignee = self.assigned_user_id
        if not assignee or assignee.id == self.env.uid:
            return
        partner = assignee.partner_id
        if not partner or not partner.email:
            return
        template = self.env.ref(
            'ft_helpdesk_core.mt_ticket_assigned_email_template',
            raise_if_not_found=False,
        )
        if not template:
            return
        try:
            rendered = template.sudo()._render_field('body_html', self.ids)
            subjects = template.sudo()._render_field('subject', self.ids)
            self.message_notify(
                partner_ids=partner.ids,
                body=Markup(rendered[self.id]),
                subject=subjects[self.id],
                email_layout_xmlid='mail.mail_notification_light',
                subtype_xmlid='mail.mt_note',
            )
        except Exception:
            _logger.warning(
                'Failed to send assignee notification for ticket %s',
                self.ticket_no, exc_info=True,
            )

    def _get_access_token(self):
        """Generate access token for portal sharing."""
        self.ensure_one()
        if not self.access_token:
            self.access_token = self.env['ir.config_parameter'].sudo()._generate_token()
        return self.access_token

    def _compute_access_url(self):
        super()._compute_access_url()
        for ticket in self:
            ticket.access_url = '/my/support/ticket/%s' % ticket.id

    # =====================
    # Bulk Actions
    # =====================

    def action_bulk_assign(self):
        """Open bulk assign wizard for selected tickets."""
        return {
            'name': _('Assign Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.helpdesk.ticket.assign.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_ids': [(6, 0, self.ids)],
            },
        }

    def action_bulk_close(self):
        """Open bulk close wizard for selected tickets."""
        return {
            'name': _('Close Tickets'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.helpdesk.ticket.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_ticket_ids': [(6, 0, self.ids)],
                'default_is_cancel': False,
            },
        }
