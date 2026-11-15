from odoo import api, fields, models
from odoo.exceptions import UserError


class QABugReopenReason(models.Model):
    """One "Reason for Reopen" entry per press of the Re-Open button on a bug.

    The entry is created by qa_testapp.ticket.action_reopen right after the
    bug's reopen_count has been incremented and takes that count as its
    ``number`` ("Reopen 1", "Reopen 2", ...). There is deliberately no second
    counter: the numbering IS the existing reopen_count.

    Only the entry whose number equals the bug's CURRENT reopen_count (the
    latest one) may be changed or deleted; every earlier entry is frozen so
    the history of reasons and their attachments is never overwritten. That
    rule is enforced here, in write() / unlink() / create(); the views only
    mirror it. Like the module's other guards it is bypassed by sudo, so
    maintenance scripts and migrations can still touch old rows.

    The rich text (reason) and the attachments reuse the Evidence tab's exact
    mechanism: an Html field with the same sanitize options, rendered by the
    qa_evidence_html widget (type + paste screenshots, click-to-preview), and
    an ir.attachment Many2many rendered by qa_evidence_files (upload / delete
    / preview; screen recordings are ordinary uploaded files). Attachments are
    re-linked to the entry (res_model / res_id) the way
    qa_testapp.ticket._link_evidence_attachments does for Evidence, so the
    stock ir.attachment access check lets anyone who can read the entry open
    them and they survive the orphan clean-up.
    """

    _name = 'qa_testapp.bug_reopen_reason'
    _description = 'QA Bug Reopen Reason'
    _order = 'number, id'
    _rec_name = 'name'

    _ticket_number_unique = models.Constraint(
        'UNIQUE(ticket_id, number)',
        'This bug already has a reopen reason entry with that reopen number.',
    )

    ticket_id = fields.Many2one(
        'qa_testapp.ticket', string='Bug', required=True,
        ondelete='cascade', index=True,
    )
    number = fields.Integer(
        string='Reopen Number', required=True, readonly=True,
        help="The bug's reopen count at the moment this entry was created.",
    )
    name = fields.Char(string='Entry', compute='_compute_name', store=True)
    # Same field type and sanitize options as ticket.evidence_description.
    reason = fields.Html(
        string='Reason for Reopen', sanitize=True, sanitize_attributes=True,
    )
    # Same shape as ticket.evidence_attachment_ids (own relation table).
    attachment_ids = fields.Many2many(
        'ir.attachment', 'qa_testapp_bug_reopen_reason_attachment_rel',
        'reason_id', 'attachment_id', string='Attachments',
    )
    attachment_count = fields.Integer(
        string='Files', compute='_compute_attachment_count')
    reopened_by = fields.Many2one(
        'res.users', string='Re-Opened By', readonly=True,
        default=lambda self: self.env.user,
    )
    reopened_on = fields.Datetime(
        string='Re-Opened On', readonly=True, default=fields.Datetime.now)
    # Not stored: compared live against the bug's reopen_count, so the moment
    # the bug is re-opened again every older entry flips to read-only without
    # any recompute or write on the old rows.
    is_latest = fields.Boolean(
        string='Editable', compute='_compute_is_latest',
        help="True only for the entry of the bug's current reopen; that one can "
             "still be edited, every earlier entry is read-only.",
    )

    can_manage_bug_reopen = fields.Boolean(
        compute='_compute_can_manage_bug_reopen',
    )

    @api.depends_context('uid')
    def _compute_can_manage_bug_reopen(self):
        allowed = self.env[
            'qa_testapp.ticket'
        ]._can_manage_bug_reopen()

        for record in self:
            record.can_manage_bug_reopen = allowed

    @api.depends('number')
    def _compute_name(self):
        for rec in self:
            rec.name = "Reopen %d" % (rec.number or 0)

    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        for rec in self:
            rec.attachment_count = len(rec.attachment_ids)

    @api.depends('number', 'ticket_id.reopen_count')
    def _compute_is_latest(self):
        for rec in self:
            rec.is_latest = bool(rec.number) and rec.number == rec.ticket_id.reopen_count

    # ------------------------------------------------------------------
    # Server-side read-only rule
    # ------------------------------------------------------------------
    def _check_latest_editable(self, action):
        """Raise unless every record is the latest entry of its bug.

        ``action`` is the verb for the message ("modified" / "deleted").
        Sudo bypasses the check, as the module's other guards do.
        """
        if self.env.su:
            return
        for rec in self:
            if not rec.is_latest:
                raise UserError(
                    "%s of bug %s is read-only and cannot be %s: only the latest "
                    "entry (Reopen %d) can be changed. Earlier reasons and their "
                    "attachments are kept as history." % (
                        rec.name, rec.ticket_id.bug_id or '', action,
                        rec.ticket_id.reopen_count,
                    )
                )

    @api.model_create_multi
    def create(self, vals_list):
        self.env['qa_testapp.ticket']._check_qa_bug_action()
        Ticket = self.env['qa_testapp.ticket']
        for vals in vals_list:
            ticket = Ticket.browse(vals['ticket_id']) if vals.get('ticket_id') else Ticket
            if not ticket:
                continue  # the ORM raises the required-field error itself
            if not vals.get('number'):
                vals['number'] = ticket.reopen_count
            if self.env.su:
                continue
            # An entry only ever documents the bug's CURRENT reopen. Pressing
            # Re-Open is what increments the count and creates the entry, so a
            # user cannot hand-create one for a bug that was never re-opened,
            # for a past reopen, or twice for the same reopen.
            if not ticket.reopen_count:
                raise UserError(
                    "Bug %s has not been re-opened yet. Use the Re-Open button: it "
                    "creates the Reopen 1 entry." % (ticket.bug_id or '',)
                )
            if vals['number'] != ticket.reopen_count:
                raise UserError(
                    "A reopen reason entry must belong to the bug's current reopen "
                    "(Reopen %d), not Reopen %d." % (ticket.reopen_count, vals['number'])
                )
            if self.search_count([('ticket_id', '=', ticket.id), ('number', '=', vals['number'])]):
                raise UserError(
                    "Reopen %d of bug %s already exists." % (vals['number'], ticket.bug_id or '')
                )
        records = super().create(vals_list)
        records._link_attachments()
        return records

    def write(self, vals):
        self.env['qa_testapp.ticket']._check_qa_bug_action()
        self._check_latest_editable('modified')
        if not self.env.su and vals.keys() & {'ticket_id', 'number'}:
            # The identity of an entry is fixed by the reopen that created it.
            for rec in self:
                if ('ticket_id' in vals and vals['ticket_id'] != rec.ticket_id.id) or \
                   ('number' in vals and vals['number'] != rec.number):
                    raise UserError(
                        "%s of bug %s cannot be moved to another bug or renumbered." % (
                            rec.name, rec.ticket_id.bug_id or '')
                    )
        res = super().write(vals)
        if 'attachment_ids' in vals:
            self._link_attachments()
        return res

    def unlink(self):
        self.env['qa_testapp.ticket']._check_qa_bug_action()
        self._check_latest_editable('deleted')
        return super().unlink()

    def _link_attachments(self):
        """Make the entry the owner of its attachments.

        Files are uploaded by the widget against whatever record the form is
        showing (the bug, when the latest entry is edited inline on the bug
        form, or nothing yet), exactly as for Evidence. Pointing res_model /
        res_id at the entry is what lets the stock ir.attachment access check
        resolve through the entry's own rules and keeps the files out of the
        orphan clean-up.
        """
        for rec in self:
            atts = rec.sudo().attachment_ids
            orphans = atts.filtered(
                lambda a: a.res_model != self._name or a.res_id != rec.id
            )
            if orphans:
                orphans.write({'res_model': self._name, 'res_id': rec.id})
