import ast
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

TICKET_STATES = [
    ('new', 'New'),
    ('open', 'In Progress'),
    ('pending_customer', 'Pending Customer'),
    ('pending_internal', 'Pending Internal'),
    ('resolved', 'Resolved'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]

PRIORITY_SELECTION = [
    ('0', 'P4 – Low'),
    ('1', 'P3 – Medium'),
    ('2', 'P2 – High'),
    ('3', 'P1 – Critical'),
]

TRIGGER_ON_SELECTION = [
    ('create', 'Ticket Created'),
    ('state_change', 'Status Changed'),
    ('sla_breach', 'SLA Breach'),
    ('customer_reply', 'Customer Reply'),
]


class HelpdeskTrigger(models.Model):
    _name = 'ft.helpdesk.trigger'
    _description = 'Helpdesk Trigger'
    _order = 'sequence, name'

    # =====================
    # Core Fields
    # =====================
    name = fields.Char(
        string='Name', required=True, translate=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    trigger_on = fields.Selection(
        TRIGGER_ON_SELECTION, string='Trigger On', required=True,
        help='When this trigger should be evaluated.',
    )
    domain = fields.Text(
        string='Domain Filter', default='[]',
        help='Domain expression to filter which tickets this trigger applies to. '
             'Uses standard Odoo domain syntax, e.g. '
             '[(\'team_id.name\', \'=\', \'Support\'), (\'priority\', \'>=\', \'2\')]',
    )

    # =====================
    # Action Fields
    # =====================
    set_state = fields.Selection(
        TICKET_STATES, string='Set Status',
        help='Change the ticket status when this trigger fires.',
    )
    set_priority = fields.Selection(
        PRIORITY_SELECTION, string='Set Priority',
        help='Change the ticket priority when this trigger fires.',
    )
    set_assigned_user_id = fields.Many2one(
        'res.users', string='Set Assignee',
        domain="[('share', '=', False)]",
        help='Assign the ticket to this user when this trigger fires.',
    )
    add_tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_helpdesk_trigger_add_tag_rel',
        'trigger_id', 'tag_id', string='Add Tags',
        help='Tags to add to the ticket.',
    )
    remove_tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_helpdesk_trigger_remove_tag_rel',
        'trigger_id', 'tag_id', string='Remove Tags',
        help='Tags to remove from the ticket.',
    )

    # =====================
    # Reply Fields
    # =====================
    reply_body = fields.Html(
        string='Reply Body', sanitize_style=True,
        help='If set, post this reply on the ticket when the trigger fires.',
    )
    is_internal_note = fields.Boolean(
        string='Internal Note', default=False,
        help='If checked, the reply will be posted as an internal note.',
    )

    # =====================
    # Notification Fields
    # =====================
    notify_user_ids = fields.Many2many(
        'res.users', 'ft_helpdesk_trigger_notify_user_rel',
        'trigger_id', 'user_id', string='Notify Users',
        domain="[('share', '=', False)]",
        help='Users to notify when this trigger fires.',
    )

    # =====================
    # Constraints
    # =====================

    @api.constrains('domain')
    def _check_domain(self):
        """Validate that the domain field contains a valid domain expression."""
        for trigger in self:
            if trigger.domain:
                try:
                    domain = ast.literal_eval(trigger.domain)
                    if not isinstance(domain, list):
                        raise ValidationError(
                            _('The domain filter must be a valid list expression.')
                        )
                except (ValueError, SyntaxError):
                    raise ValidationError(
                        _('The domain filter contains an invalid expression: %s') % trigger.domain
                    )

    # =====================
    # Methods
    # =====================

    def _evaluate_domain(self, ticket):
        """Check whether the given ticket matches this trigger's domain.

        :param ticket: ft.helpdesk.ticket recordset (single record)
        :returns: True if the ticket matches, False otherwise
        """
        self.ensure_one()
        ticket.ensure_one()

        if not self.domain or self.domain == '[]':
            return True

        try:
            domain = ast.literal_eval(self.domain)
        except (ValueError, SyntaxError):
            _logger.warning(
                'Trigger "%s" (id=%s) has invalid domain: %s',
                self.name, self.id, self.domain,
            )
            return False

        # Search for the ticket within the domain; if found, it matches
        combined_domain = Domain.AND([
            domain,
            [('id', '=', ticket.id)],
        ])
        return bool(self.env['ft.helpdesk.ticket'].search_count(combined_domain))

    def _apply_actions(self, ticket):
        """Apply the trigger's actions to the ticket.

        :param ticket: ft.helpdesk.ticket recordset (single record)
        """
        self.ensure_one()
        ticket.ensure_one()

        vals = {}

        # Set state
        if self.set_state:
            vals['state'] = self.set_state

        # Set priority
        if self.set_priority:
            vals['priority'] = self.set_priority

        # Set assignee
        if self.set_assigned_user_id:
            vals['assigned_user_id'] = self.set_assigned_user_id.id

        # Update tags: add and remove
        tag_commands = []
        if self.add_tag_ids:
            for tag in self.add_tag_ids:
                tag_commands.append((4, tag.id))
        if self.remove_tag_ids:
            for tag in self.remove_tag_ids:
                tag_commands.append((3, tag.id))
        if tag_commands:
            vals['tag_ids'] = tag_commands

        # Write all field changes at once
        if vals:
            ticket.write(vals)

        # Post reply if configured
        if self.reply_body:
            if self.is_internal_note:
                subtype_xmlid = 'ft_helpdesk_core.mt_ticket_internal_note'
            else:
                subtype_xmlid = 'mail.mt_comment'
            ticket.message_post(
                body=self.reply_body,
                subtype_xmlid=subtype_xmlid,
                message_type='comment',
            )

        # Notify users
        if self.notify_user_ids:
            ticket.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=self.notify_user_ids[0].id,
                summary=_('Automation Trigger: %s') % self.name,
                note=_('Trigger "%s" fired on ticket %s.') % (
                    self.name, ticket.ticket_no or ticket.name),
            )

        _logger.info(
            'Trigger "%s" (id=%s) fired on ticket %s (id=%s)',
            self.name, self.id, ticket.ticket_no, ticket.id,
        )

    def _check_and_apply(self, ticket):
        """Evaluate the domain and apply actions if the ticket matches.

        This is the main entry point for trigger evaluation.

        :param ticket: ft.helpdesk.ticket recordset (single record)
        :returns: True if the trigger fired, False otherwise
        """
        self.ensure_one()
        ticket.ensure_one()

        if not self.active:
            return False

        if self._evaluate_domain(ticket):
            self._apply_actions(ticket)
            return True

        return False
