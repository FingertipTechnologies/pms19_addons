import logging
from datetime import timedelta

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


TARGET_TIME_BY_PRIORITY = {
    'p1': ('15-30 mins',     30),
    'p2': ('1-2 hours',     120),
    'p3': ('4-8 hours',     480),
    'p4': ('1 business day', 24 * 60),
}


class QATicket(models.Model):
    _name = 'qa_testapp.ticket'
    _description = 'QA Bug Ticket'
    _order = 'id desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'title'

    bug_id = fields.Char(string='Bug ID', readonly=True, copy=False, default='New', tracking=True)
    title = fields.Char(string='Title / Summary', required=True, tracking=True,
                        help="One-line specific summary, e.g., 'Login fails with 500 when password contains #'.")
    description = fields.Text(string='Description', help="What's wrong + what you expected.")
    steps_to_reproduce = fields.Text(string='Steps to Reproduce', help="Numbered steps.")
    expected_result = fields.Text(string='Expected Result')
    actual_result = fields.Text(string='Actual Result')

    is_client = fields.Boolean(string='Client', help="Check if this bug was raised by a client.")
    is_internal = fields.Boolean(string='Internal', help="Check if this bug was found internally.")

    reporter_id = fields.Many2one('res.users', string='Reporter', default=lambda self: self.env.user, tracking=True)
    reporter_display = fields.Char(string='Reporter', compute='_compute_reporter_display')

    environment = fields.Selection([
        ('sandbox', 'Sandbox'),
        ('qa', 'QA'),
        ('production', 'Production')
    ], string='Environment', default='sandbox', required=True)
    device = fields.Selection([
        ('mobile', 'Mobile'),
        ('desktop', 'Desktop'),
        ('tablet', 'Tablet')
    ], string='Device', default='desktop')
    severity = fields.Selection([
        ('blocker', 'Blocker'),
        ('critical', 'Critical'),
        ('major', 'Major'),
        ('minor', 'Minor'),
        ('trivial', 'Trivial')
    ], string='Severity', default='major', tracking=True)
    priority = fields.Selection([
        ('p1', 'P1 - Urgent'),
        ('p2', 'P2 - High'),
        ('p3', 'P3 - Medium'),
        ('p4', 'P4 - Low'),
        ('p5', 'P5 - Backlog')
    ], string='Priority', default='p3', tracking=True)
    target_response_time = fields.Char(
        string='Target Response Time',
        compute='_compute_target_response', store=True, readonly=True,
        help='Auto-set from priority. Informational only (not required).',
    )
    target_deadline = fields.Datetime(
        string='Target Deadline',
        compute='_compute_target_response', store=True, readonly=True,
        help='Reported date + the upper bound of the priority response band.',
    )
    status = fields.Selection([
        ('open', 'Open'),
        ('in_progress', 'In Progress'),
        ('fixed', 'Fixed'),
        ('closed', 'Closed'),
        ('reopened', 'Re-Opened'),
        # Developer resolutions (set with the header buttons; Rejected asks
        # for a reason). QA closes or re-opens them like a Fixed bug.
        ('rejected', 'Rejected'),
        ('unable_to_reproduce', 'Unable to Reproduce'),
        ('duplicate', 'Duplicate'),
    ], string='Status', default='open', tracking=True)
    reproducibility = fields.Selection([
        ('always', 'Always'),
        ('sometimes', 'Sometimes'),
        ('rare', 'Rare'),
        ('unable', 'Unable to Reproduce')
    ], string='Reproducibility', default='always')
    evidence_notes = fields.Text(string='Evidence Notes')
    # Rich content area so testers can paste screenshots straight into the
    # evidence write-up. Kept alongside the legacy plain-text evidence_notes so
    # existing records keep their notes; new rich content lives here.
    evidence_description = fields.Html(
        string='Evidence Description', sanitize=True, sanitize_attributes=True,
    )
    evidence_attachment_ids = fields.Many2many(
        'ir.attachment', 'qa_testapp_ticket_attachment_rel',
        'ticket_id', 'attachment_id',
        string='Attachments',
    )
    url_ids = fields.One2many(
        'qa_testapp.resource_url', 'ticket_id', string='URLs')
    reported_date = fields.Datetime(string='Reported Date', default=fields.Datetime.now)
    project_id = fields.Many2one('project.project', string='Project', required=True)
    module = fields.Char(string='Module (legacy)', tracking=True)
    module_id = fields.Many2one(
        'cus.module', string='Module', tracking=True,
        domain="[('id', 'in', available_module_ids)]",
    )
    available_module_ids = fields.Many2many(
        'cus.module', compute='_compute_available_modules',
    )
    test_case_id = fields.Many2one('qa_testapp.test_case', string='Related Test Case')
    assignee_id = fields.Many2one('res.users', string='Assignee', required=True, tracking=True)
    reopen_count = fields.Integer(
        string='Reopen Count', default=0,
        readonly=True, copy=False, tracking=True,
        help='Number of times this bug has been re-opened.',
    )
    # One "Reason for Reopen" entry per press of Re-Open, numbered from
    # reopen_count ("Reopen 1", "Reopen 2", ...) - no second counter. Only the
    # entry of the current count is editable; see models/bug_reopen_reason.py.
    reopen_reason_ids = fields.One2many(
        'qa_testapp.bug_reopen_reason', 'ticket_id',
        string='Reasons for Reopen', copy=False,
    )
    latest_reopen_reason_id = fields.Many2one(
        'qa_testapp.bug_reopen_reason', string='Current Reopen Entry',
        compute='_compute_latest_reopen_reason_id', store=True, copy=False,
        help='The entry created by the most recent Re-Open: the only one still editable. '
             'Stored: the inline Reason for Reopen proxies are related through it and '
             'the ORM must be able to search tickets by it.',
    )
    # Writable proxies so the Reason for Reopen tab edits the latest entry
    # inline with the very same widgets as the Evidence tab (qa_evidence_html /
    # qa_evidence_files) instead of through a dialog. Writing them writes the
    # entry itself - through its own write(), so its read-only guard applies.
    # Older entries are only reachable read-only, through reopen_reason_ids.
    latest_reopen_reason = fields.Html(
        related='latest_reopen_reason_id.reason', readonly=False,
        string='Reason for Reopen',
    )
    latest_reopen_attachment_ids = fields.Many2many(
        related='latest_reopen_reason_id.attachment_ids', readonly=False,
        string='Reopen Attachments',
    )
    escalation_level = fields.Selection([
        ('none', 'None'),
        ('qa_lead', 'QA Lead'),
        ('manager', 'Manager'),
    ], string='Escalation', default='none',
       readonly=True, copy=False, tracking=True)

    approval_state = fields.Selection([
        ('pending_approval', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Approval State', default='approved', tracking=True, copy=False,
       help="Junior QA submissions start as Pending Approval. PM of the project approves or rejects. "
            "Working status (Open / In Progress / Fixed / ...) can only be changed once approved.")
    approver_id = fields.Many2one(
        'res.users', string='Approver (Project PM)',
        compute='_compute_approver_id', store=True, readonly=True,
    )
    rejection_reason = fields.Text(string='Rejection Reason', copy=False, readonly=True)
    is_current_user_approver = fields.Boolean(
        string='Current User Is Approver',
        compute='_compute_is_current_user_approver',
    )
    is_creator = fields.Boolean(
        string='Current User Is Creator',
        compute='_compute_is_creator',
    )
    creator_unlocked = fields.Boolean(
        string='Unlocked by Creator', default=False, copy=False,
        help="Set when the creator clicks Edit to change a record that is "
             "still pending approval. Only the creator can unlock it.",
    )

    dev_rejection_reason = fields.Text(
        string='Developer Rejection Reason', copy=False, readonly=True, tracking=True,
        help="Why the developer rejected the bug (status Rejected). Distinct from "
             "the PM's approval rejection_reason.",
    )

    is_dev_user = fields.Boolean(
        string='Current User Is Developer', compute='_compute_is_dev_user',
        help="The current user is the bug's assignee (developer) and not a "
             "Junior / Senior QA: only they see Rejected / Unable to Reproduce / Duplicate.")

    @api.depends('assignee_id')
    @api.depends_context('uid')
    def _compute_is_dev_user(self):
        is_qa = self._is_junior_qa() or self._is_senior_qa() \
            or self.env.user.has_group('qa_testapp.group_qa_bug_only')
        for rec in self:
            rec.is_dev_user = bool(rec.assignee_id) and rec.assignee_id == self.env.user and not is_qa

    @api.depends('reopen_count', 'reopen_reason_ids.number')
    def _compute_latest_reopen_reason_id(self):
        for rec in self:
            rec.latest_reopen_reason_id = rec.reopen_reason_ids.filtered(
                lambda r: r.number == rec.reopen_count)[:1]

    @api.depends('project_id', 'project_id.user_id')
    def _compute_approver_id(self):
        for rec in self:
            rec.approver_id = rec.project_id.user_id

    @api.depends('approver_id')
    def _compute_is_current_user_approver(self):
        senior = self._is_senior_qa()
        for rec in self:
            rec.is_current_user_approver = (rec.approver_id == self.env.user) or senior

    @api.depends_context('uid')
    def _compute_is_creator(self):
        for rec in self:
            rec.is_creator = bool(rec.create_uid) and rec.create_uid.id == self.env.uid

    @api.depends('project_id')
    def _compute_available_modules(self):
        for rec in self:
            if rec.project_id:
                tasks = self.env['project.task'].sudo().search([
                    ('project_id', '=', rec.project_id.id),
                    ('module_id', '!=', False),
                ])
                rec.available_module_ids = tasks.mapped('module_id')
            else:
                rec.available_module_ids = self.env['cus.module'].sudo().search([])

    @api.depends('priority', 'reported_date')
    def _compute_target_response(self):
        for rec in self:
            mapping = TARGET_TIME_BY_PRIORITY.get(rec.priority)
            if not mapping:
                rec.target_response_time = False
                rec.target_deadline = False
                continue
            label, offset_minutes = mapping
            rec.target_response_time = label
            rec.target_deadline = (
                rec.reported_date + timedelta(minutes=offset_minutes)
                if rec.reported_date else False
            )

    @api.depends('is_client', 'is_internal', 'reporter_id')
    def _compute_reporter_display(self):
        for rec in self:
            if rec.is_client:
                rec.reporter_display = "Client"
            elif rec.is_internal and rec.reporter_id:
                rec.reporter_display = rec.reporter_id.name
            else:
                rec.reporter_display = ""

    @api.onchange('project_id')
    def _onchange_project_id(self):
        self.module_id = False

    @api.onchange('is_client')
    def _onchange_is_client(self):
        if self.is_client:
            self.is_internal = False
            self.reporter_id = False
            self.priority = 'p1'
            if self.severity not in ('blocker', 'critical'):
                self.severity = 'critical'

    @api.onchange('is_internal')
    def _onchange_is_internal(self):
        if self.is_internal:
            self.is_client = False
            self.reporter_id = self.env.user

    can_manage_bug_reopen = fields.Boolean(
        compute='_compute_can_manage_bug_reopen',
    )

    def _can_manage_bug_reopen(self):
        user = self.env.user

        if user.has_group('qa_testapp.group_qa_bug_only'):
            return False

        return (
            user.has_group('qa_testapp.group_qa_junior')
            or user.has_group('qa_testapp.group_qa_senior')
        )

    def _check_qa_bug_action(self):
        if not self._can_manage_bug_reopen():
            raise UserError(
                "Only internal Junior QA or Senior QA can close or "
                "reopen bugs and modify reopen reasons."
            )

    @api.depends_context('uid')
    def _compute_can_manage_bug_reopen(self):
        allowed = self._can_manage_bug_reopen()
        for record in self:
            record.can_manage_bug_reopen = allowed

    def action_in_progress(self):
        self.write({'status': 'in_progress'})

    def action_fixed(self):
        self.write({'status': 'fixed'})

    def action_closed(self):
        self._check_qa_bug_action()
        self.write({'status': 'closed'})

    # Developer resolutions -------------------------------------------
    DEV_RESOLUTION_FROM = ('open', 'in_progress', 'reopened')

    def _check_dev_resolution_allowed(self):
        for rec in self:
            if not rec.is_dev_user and not self.env.user.has_group('base.group_system'):
                raise UserError(
                    "Only the developer assigned to bug %s can reject it or mark it "
                    "Unable to Reproduce / Duplicate." % (rec.bug_id or '',)
                )
            if rec.status not in self.DEV_RESOLUTION_FROM:
                raise UserError(
                    "Bug %s is %s: only an Open, In Progress or Re-Opened bug can be "
                    "rejected, marked Unable to Reproduce or Duplicate." % (
                        rec.bug_id or '', dict(rec._fields['status'].selection).get(rec.status, rec.status),
                    )
                )

    def action_dev_reject(self, reason=None):
        reason = (reason or '').strip()
        if not reason:
            raise UserError("A reason is required to reject a bug.")
        self._check_dev_resolution_allowed()
        for rec in self:
            rec.write({'status': 'rejected', 'dev_rejection_reason': reason})
            rec.message_post(body="Bug rejected by %s. Reason: %s" % (self.env.user.name, reason))

    def action_dev_reject_open_wizard(self):
        self.ensure_one()
        self._check_dev_resolution_allowed()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Bug',
            'res_model': 'qa_testapp.bug_dev_reject_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_model': 'qa_testapp.ticket', 'active_ids': self.ids},
        }

    def action_unable_to_reproduce(self):
        self._check_dev_resolution_allowed()
        self.write({'status': 'unable_to_reproduce'})
        for rec in self:
            rec.message_post(body="Marked Unable to Reproduce by %s." % self.env.user.name)

    def action_duplicate(self):
        self._check_dev_resolution_allowed()
        self.write({'status': 'duplicate'})
        for rec in self:
            rec.message_post(body="Marked Duplicate by %s." % self.env.user.name)

    def action_reopen(self):
        self._check_qa_bug_action()
        for ticket in self:
            new_count = ticket.reopen_count + 1
            ticket.write({'status': 'reopened', 'reopen_count': new_count,
                          'dev_rejection_reason': False})
            # The "Reason for Reopen" entry takes the count just written
            # ("Reopen <new_count>"); created after the write so a bug that
            # may not change status (pending approval / rejected) gets no
            # stray entry.
            ticket._create_reopen_reason_entry(new_count)
            ticket._escalate_on_reopen()

    def _create_reopen_reason_entry(self, number):
        """Create the empty "Reopen <number>" entry the tester then fills in
        (typed reason, pasted screenshots, uploaded files) on the Reason for
        Reopen tab. Runs as the user pressing Re-Open: whoever may write the
        bug may create and edit its latest entry (record rules mirror the
        bug's)."""
        self.ensure_one()
        return self.env['qa_testapp.bug_reopen_reason'].create({
            'ticket_id': self.id,
            'number': number,
            'reopened_by': self.env.user.id,
            'reopened_on': fields.Datetime.now(),
        })

    def _escalate_on_reopen(self):
        """Hierarchy-based escalation driven by reopen_count.
        3rd reopen -> project.qa_lead_id (fallback: project.user_id), level='qa_lead'.
        4th+ reopen -> project.user_id (Project Manager), level='manager'."""
        self.ensure_one()
        project = self.project_id
        if not project:
            return
        count = self.reopen_count
        if count < 3:
            return

        if count == 3:
            partner = project.partner_id
            customer_team = (
                partner.commercial_partner_id.helpdesk_team_id
                or partner.helpdesk_team_id
            ) if partner else self.env['ft.helpdesk.team']
            qa_lead = customer_team.leader_user_id
            target = qa_lead or project.user_id
            new_level = 'qa_lead'
            if qa_lead:
                target_role = 'QA Lead'
            elif not partner:
                target_role = 'Project Manager (no customer on project)'
            elif not customer_team:
                target_role = "Project Manager (customer has no Support Team)"
            else:
                target_role = 'Project Manager (customer Support Team has no leader)'
        else:
            target = project.user_id
            new_level = 'manager'
            target_role = 'Project Manager'

        if not target:
            _logger.warning(
                "Bug %s: cannot escalate to %s - no user configured on project '%s'",
                self.bug_id, new_level, project.name,
            )
            self.message_post(
                body=(
                    "<p>Reopen #%d reached but escalation skipped: no %s "
                    "configured on project <strong>%s</strong>.</p>"
                ) % (count, target_role, project.name),
                message_type='notification',
            )
            return

        self.write({'assignee_id': target.id, 'escalation_level': new_level})
        self.message_post(
            body=(
                "<p>Bug re-opened %d time(s). Escalated to <strong>%s</strong>: "
                "<strong>%s</strong>.</p>"
            ) % (count, target_role, target.name),
            message_type='notification',
        )
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=target.id,
            summary='Escalated bug: %s (%d reopens)' % (self.bug_id, count),
            note='Bug %s - "%s" has been escalated to you after %d reopens.' % (
                self.bug_id, self.title, count,
            ),
        )

    @api.model
    def _is_junior_qa(self, user=None):
        user = user or self.env.user
        return user.has_group('qa_testapp.group_qa_junior')

    @api.model
    def _is_senior_qa(self, user=None):
        user = user or self.env.user
        return user.has_group('qa_testapp.group_qa_senior')

    def _user_can_approve(self, user=None):
        """A pending bug may be approved/rejected by the project's PM
        (approver_id), any Senior QA, or a system admin."""
        self.ensure_one()
        user = user or self.env.user
        return (
            (self.approver_id and self.approver_id == user)
            or self._is_senior_qa(user)
            or user.has_group('base.group_system')
        )

    @api.model_create_multi
    def create(self, vals_list):
        junior = self._is_junior_qa()
        for vals in vals_list:
            if (
                vals.get('status') in ('closed', 'reopened')
                or vals.get('reopen_count')
                or vals.get('reopen_reason_ids')
                or vals.get('latest_reopen_reason_id')
                or vals.get('latest_reopen_reason')
                or vals.get('latest_reopen_attachment_ids')
            ):
                self._check_qa_bug_action()
            if vals.get('bug_id', 'New') == 'New':
                vals['bug_id'] = self.env['ir.sequence'].next_by_code('qa_testapp.ticket') or 'New'
            if junior:
                vals['approval_state'] = 'pending_approval'
                vals['status'] = 'open'
        records = super().create(vals_list)
        records._link_evidence_attachments()
        for record in records:
            # Junior-QA submissions sit in 'pending_approval' for the PM to review
            # from the Bugs list - no approval email is sent. A directly-created
            # (auto-approved) bug still notifies its assignee.
            if record.approval_state != 'pending_approval' and record.assignee_id:
                record._notify_assignee()
        return records

    def write(self, vals):
        protected_fields = {
            'reopen_count',
            'reopen_reason_ids',
            'latest_reopen_reason_id',
            'latest_reopen_reason',
            'latest_reopen_attachment_ids',
        }

        if (
            vals.get('status') in ('closed', 'reopened')
            or protected_fields.intersection(vals)
        ):
            self._check_qa_bug_action()
        WORKING_STATUS_FIELDS = {'status', 'reopen_count', 'escalation_level'}
        if vals.keys() & WORKING_STATUS_FIELDS:
            for rec in self:
                if rec.approval_state == 'pending_approval':
                    raise UserError(
                        "Bug %s is pending approval. The PM must approve it before status changes." % (rec.bug_id or '',)
                    )
                if rec.approval_state == 'rejected' and 'status' in vals:
                    raise UserError(
                        "Bug %s has been rejected. Status cannot change." % (rec.bug_id or '',)
                    )
        res = super().write(vals)
        if 'evidence_attachment_ids' in vals:
            self._link_evidence_attachments()
        if 'assignee_id' in vals:
            for rec in self:
                if rec.approval_state == 'approved':
                    rec._notify_assignee()
        # Re-lock once the creator's edit is saved, so Edit shows again for the
        # next round. The unlock is meant to last for one edit; without this the
        # flag stayed True forever and the button hid permanently. Skip when the
        # flag is itself being written (that write IS action_creator_edit), and
        # go through super() so this never recurses.
        if 'creator_unlocked' not in vals:
            unlocked = self.filtered('creator_unlocked')
            if unlocked:
                super(QATicket, unlocked).write({'creator_unlocked': False})
        return res

    def action_creator_edit(self):
        """Unlock a still-pending bug so its creator can edit it.
        Only the record's creator may unlock it."""
        self.ensure_one()
        if not self.is_creator:
            raise UserError(
                "Only the creator can edit bug %s while it is pending approval." % (self.bug_id or '',)
            )
        self.creator_unlocked = True

    def action_approve(self):
        for rec in self:
            if rec.approval_state != 'pending_approval':
                continue
            if not rec._user_can_approve():
                raise UserError(
                    "Only %s (PM of project '%s') or a Senior QA can approve bug %s." % (
                        rec.approver_id.name or 'the PM', rec.project_id.name, rec.bug_id,
                    )
                )
            rec.approval_state = 'approved'
            rec.message_post(body="Bug approved by %s." % self.env.user.name)
            if rec.assignee_id:
                rec._notify_assignee(approved=True)

    def action_reject(self, reason=None):
        for rec in self:
            if rec.approval_state != 'pending_approval':
                continue
            if not rec._user_can_approve():
                raise UserError(
                    "Only %s (PM of project '%s') or a Senior QA can reject bug %s." % (
                        rec.approver_id.name or 'the PM', rec.project_id.name, rec.bug_id,
                    )
                )
            rec.approval_state = 'rejected'
            if reason:
                rec.rejection_reason = reason
            rec.message_post(body="Bug rejected by %s. Reason: %s" % (self.env.user.name, reason or '(none)'))
            rec._notify_rejection()

    def action_reject_open_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reject Bug',
            'res_model': 'qa_testapp.bulk_approve_wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'qa_testapp.ticket',
                'active_ids': self.ids,
                'default_action_type': 'reject',
            },
        }

    def _link_evidence_attachments(self):
        for rec in self:
            atts = rec.sudo().evidence_attachment_ids
            orphans = atts.filtered(
                lambda a: a.res_model != 'qa_testapp.ticket' or a.res_id != rec.id
            )
            if orphans:
                orphans.write({'res_model': 'qa_testapp.ticket', 'res_id': rec.id})

    def _notify_assignee(self, approved=False):
        """Notify the assignee that they can start working.

        approved=True  -> a junior QA's bug was just approved by the PM
                          (use the "Approved" wording).
        approved=False -> the bug was created directly (e.g. by the PM, no
                          approval step) or reassigned -> use the neutral
                          "created & assigned" wording, no mention of approval.
        """
        self.ensure_one()
        if self.approval_state != 'approved':
            return
        if self.assignee_id and self.assignee_id.email:
            ref = 'qa_testapp.email_template_bug_approved' if approved \
                else 'qa_testapp.email_template_bug_assigned'
            template = self.env.ref(ref, raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)

    def _notify_pending_approval(self):
        self.ensure_one()
        if self.approver_id and self.approver_id.email:
            template = self.env.ref('qa_testapp.email_template_bug_pending_approval', raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)

    def _notify_rejection(self):
        self.ensure_one()
        if self.reporter_id and self.reporter_id.email:
            template = self.env.ref('qa_testapp.email_template_bug_rejected', raise_if_not_found=False)
            if template:
                template.sudo().send_mail(self.id, force_send=True)
