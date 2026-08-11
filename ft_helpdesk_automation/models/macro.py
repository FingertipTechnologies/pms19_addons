import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

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


class HelpdeskMacro(models.Model):
    _name = 'ft.helpdesk.macro'
    _description = 'Helpdesk Macro'
    _order = 'sequence, name'

    # =====================
    # Core Fields
    # =====================
    name = fields.Char(
        string='Name', required=True, translate=True,
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    team_ids = fields.Many2many(
        'ft.helpdesk.team', 'ft_helpdesk_macro_team_rel',
        'macro_id', 'team_id', string='Teams',
        help='Limit this macro to specific teams. Leave empty for all teams.',
    )

    # =====================
    # Action Fields
    # =====================
    set_state = fields.Selection(
        TICKET_STATES, string='Set Status',
        help='Change the ticket status when this macro is applied.',
    )
    set_priority = fields.Selection(
        PRIORITY_SELECTION, string='Set Priority',
        help='Change the ticket priority when this macro is applied.',
    )
    set_assigned_user_id = fields.Many2one(
        'res.users', string='Set Assignee',
        domain="[('share', '=', False)]",
        help='Assign the ticket to this user when this macro is applied.',
    )
    add_tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_helpdesk_macro_add_tag_rel',
        'macro_id', 'tag_id', string='Add Tags',
        help='Tags to add to the ticket.',
    )
    remove_tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_helpdesk_macro_remove_tag_rel',
        'macro_id', 'tag_id', string='Remove Tags',
        help='Tags to remove from the ticket.',
    )

    # =====================
    # Reply Fields
    # =====================
    reply_body = fields.Html(
        string='Reply Body', sanitize_style=True,
        help='If set, post this reply on the ticket when the macro is applied.',
    )
    is_internal_note = fields.Boolean(
        string='Internal Note', default=False,
        help='If checked, the reply will be posted as an internal note instead of a public reply.',
    )

    # =====================
    # Methods
    # =====================

    def action_apply(self, ticket):
        """Apply all the macro's actions to a ticket.

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

        _logger.info(
            'Macro "%s" (id=%s) applied to ticket %s (id=%s)',
            self.name, self.id, ticket.ticket_no, ticket.id,
        )
        return True
