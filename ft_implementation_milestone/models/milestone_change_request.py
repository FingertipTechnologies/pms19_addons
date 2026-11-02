# -*- coding: utf-8 -*-
"""Requirement 56, the exception: a Milestone Change Request.

Once an Implementation project has left KICKOFF its milestone plan is locked
(see project_custom_milestone.py). A Project Manager who needs to change it
raises a request (update one milestone, add one, remove one), submits it, and
a Date Extension Approver (the same admin group that controls the dates)
approves or rejects it. Approval applies the change itself, under sudo and
the ``ft_milestone_change_approval`` context key that the lock honours, and
is refused when the plan would not total 100% afterwards.

Mirrors project_date_extension's request (states, requester / approver,
decision stamps, history kept: only drafts can be deleted), kept compact.
"""
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .milestone_template import PERCENT_DIGITS, ft_format_percent, ft_percent_is_100
from .project_custom_milestone import APPROVER_GROUP, CHANGE_APPROVAL_CONTEXT_KEY

# Milestones already invoiced or paid are facts, not plan: a request may not
# remove them (their percentage can still be corrected through an update).
UNREMOVABLE_STATUSES = ('invoice_raised', 'partially_paid', 'paid')


class FtMilestoneChangeRequest(models.Model):
    _name = 'ft.milestone.change.request'
    _description = 'Milestone Change Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Reference', default=lambda self: _('New'), copy=False,
        readonly=True)
    project_id = fields.Many2one(
        'project.project', string='Project', required=True, tracking=True,
        ondelete='cascade', index=True,
        domain="[('ft_project_type', '=', 'implementation')]")
    milestone_id = fields.Many2one(
        'project.custom.milestone', string='Milestone', tracking=True,
        # set null: an approved 'remove' deletes the milestone and the
        # request must survive it (the snapshot below keeps what it was).
        ondelete='set null',
        domain="[('project_id', '=', project_id)]")
    change_type = fields.Selection(
        [
            ('update', 'Update a milestone'),
            ('add', 'Add a milestone'),
            ('remove', 'Remove a milestone'),
        ],
        string='Change', required=True, default='update', tracking=True)

    # Snapshot of the milestone when the request was raised. Filled by the
    # onchange / create and never recomputed, so the history survives the
    # approval (which changes the live milestone) and the removal.
    current_name = fields.Char(string='Current Name', readonly=True)
    current_percentage = fields.Float(
        string='Current %', readonly=True, digits=(16, PERCENT_DIGITS))
    current_amount = fields.Float(string='Current Amount', readonly=True)
    current_due_date = fields.Date(string='Current Due Date', readonly=True)

    new_name = fields.Char(string='New Name')
    new_percentage = fields.Float(
        string='New %', digits=(16, PERCENT_DIGITS))
    new_amount = fields.Float(string='New Amount')
    new_due_date = fields.Date(string='New Due Date')

    reason = fields.Text(string='Reason', required=True)
    requester_id = fields.Many2one(
        'res.users', string='Requested By', default=lambda self: self.env.user,
        tracking=True)
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('request', 'Request'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
        ],
        string='Status', default='draft', copy=False, tracking=True, index=True)
    approver_id = fields.Many2one(
        'res.users', string='Approved/Rejected By', readonly=True, copy=False,
        tracking=True)
    decision_date = fields.Datetime(string='Decision Date', readonly=True, copy=False)
    rejection_reason = fields.Text(string='Rejection Reason', copy=False, tracking=True)
    approval_comment = fields.Text(string='Approval Comment', copy=False, tracking=True)
    company_id = fields.Many2one(
        related='project_id.company_id', store=True, readonly=True)

    # What the plan would total if this request were approved now - shown on
    # the form so the requester sees a shortfall before submitting.
    resulting_percentage_total = fields.Float(
        string='Resulting Plan Total %', compute='_compute_resulting_total',
        digits=(16, PERCENT_DIGITS))
    is_approver = fields.Boolean(compute='_compute_rights')
    can_submit = fields.Boolean(compute='_compute_rights')

    # ------------------------------------------------------------------
    # Computes / onchange
    # ------------------------------------------------------------------
    @api.depends('project_id.custom_milestone_ids.percentage', 'milestone_id',
                 'milestone_id.percentage', 'change_type', 'new_percentage')
    def _compute_resulting_total(self):
        for rec in self:
            rec.resulting_percentage_total = rec._ft_resulting_total()

    @api.depends('state', 'requester_id')
    @api.depends_context('uid')
    def _compute_rights(self):
        decider = self._ft_user_is_decider()
        for rec in self:
            rec.is_approver = decider
            rec.can_submit = rec.state == 'draft' and (
                decider or self.env.user == rec.requester_id)

    @api.onchange('milestone_id', 'change_type')
    def _onchange_milestone_id(self):
        """Snapshot the milestone and start the new values from it, so the
        requester only edits what changes."""
        if self.change_type == 'add':
            self.milestone_id = False
        milestone = self.milestone_id
        self.current_name = milestone.name
        self.current_percentage = milestone.percentage
        self.current_amount = milestone.amount
        self.current_due_date = milestone.due_date
        if self.change_type == 'update' and milestone:
            self.new_name = milestone.name
            self.new_percentage = milestone.percentage
            self.new_amount = milestone.amount
            self.new_due_date = milestone.due_date

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _ft_user_is_decider(self):
        return (self.env.su
                or self.env.user.has_group(APPROVER_GROUP)
                or self.env.user.has_group('base.group_system'))

    def _ft_resulting_total(self):
        """Plan total after this change, from the LIVE milestones."""
        self.ensure_one()
        total = sum(self.project_id.custom_milestone_ids.mapped('percentage'))
        live = self.milestone_id.percentage if self.milestone_id else 0.0
        if self.change_type == 'update':
            return total - live + (self.new_percentage or 0.0)
        if self.change_type == 'add':
            return total + (self.new_percentage or 0.0)
        if self.change_type == 'remove':
            return total - live
        return total

    def _ft_milestone_vals(self):
        """Values an approved 'update' writes / an 'add' creates. For an
        update only the fields that really change are written, so an
        unchanged date is not pushed through project_date_extension's guard
        for nothing and the chatter tracks only what moved."""
        self.ensure_one()
        vals = {
            'name': self.new_name,
            'percentage': self.new_percentage or 0.0,
            'amount': self.new_amount or 0.0,
            'due_date': self.new_due_date or False,
        }
        if self.change_type == 'add':
            vals['project_id'] = self.project_id.id
            return vals
        milestone = self.milestone_id
        changed = {}
        for fname, value in vals.items():
            if fname == 'name' and not value:
                continue  # a blank new name means "keep it"
            if milestone[fname] != value:
                changed[fname] = value
        return changed

    # ------------------------------------------------------------------
    # Constraints / ORM
    # ------------------------------------------------------------------
    @api.constrains('change_type', 'milestone_id', 'new_name', 'new_percentage',
                    'project_id')
    def _check_request_consistency(self):
        for rec in self:
            if rec.change_type != 'add' and not rec.milestone_id:
                raise ValidationError(_(
                    "Please select the milestone to %s.",
                    dict(rec._fields['change_type'].selection)[rec.change_type].lower()))
            if rec.milestone_id and rec.milestone_id.project_id != rec.project_id:
                raise ValidationError(_(
                    "Milestone '%(milestone)s' does not belong to project "
                    "'%(project)s'.",
                    milestone=rec.milestone_id.display_name,
                    project=rec.project_id.display_name))
            if rec.change_type == 'add' and not (rec.new_name or '').strip():
                raise ValidationError(_("Please give the new milestone a name."))
            if rec.change_type != 'remove' and (
                    rec.new_percentage < 0 or rec.new_percentage > 100):
                raise ValidationError(_(
                    "The new percentage must be between 0 and 100 (got %s).",
                    ft_format_percent(rec.new_percentage)))

    @api.model_create_multi
    def create(self, vals_list):
        Milestone = self.env['project.custom.milestone']
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('ft.milestone.change.request')
                    or _('New'))
            # Freeze the snapshot server-side too (RPC / tests do not run the
            # onchange), and default an update's new values to the current
            # ones so a request changing only the percentage keeps the rest.
            milestone = Milestone.browse(vals.get('milestone_id')) if vals.get('milestone_id') else Milestone
            if milestone:
                vals.setdefault('current_name', milestone.name)
                vals.setdefault('current_percentage', milestone.percentage)
                vals.setdefault('current_amount', milestone.amount)
                vals.setdefault('current_due_date', milestone.due_date)
                if vals.get('change_type', 'update') == 'update':
                    vals.setdefault('new_name', milestone.name)
                    vals.setdefault('new_percentage', milestone.percentage)
                    vals.setdefault('new_amount', milestone.amount)
                    vals.setdefault('new_due_date', milestone.due_date)
        return super().create(vals_list)

    def write(self, vals):
        # Project users hold write access so they can edit and submit their
        # drafts; a decided or submitted request is frozen for them.
        if not self._ft_user_is_decider():
            frozen = self.filtered(lambda r: r.state != 'draft')
            if frozen:
                raise UserError(_(
                    "Only draft Milestone Change Requests can be edited "
                    "(%s). Ask an approver, or raise a new request.",
                    ', '.join(frozen.mapped('name'))))
        return super().write(vals)

    def unlink(self):
        """History is kept: only a never-submitted draft may be deleted."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    "Submitted, approved or rejected Milestone Change Requests "
                    "cannot be deleted (%s), in order to keep the full history "
                    "of the agreed plan.", rec.name))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_can_decide(self):
        if not self._ft_user_is_decider():
            raise AccessError(_(
                "Only a Date Extension Approver or an Administrator can approve "
                "or reject Milestone Change Requests."))

    def action_submit_request(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft requests can be submitted for approval."))
            if not (self._ft_user_is_decider() or self.env.user == rec.requester_id):
                raise AccessError(_(
                    "Only the requester or an approver can submit this request."))
            if rec.change_type == 'remove' and rec.milestone_id.status in UNREMOVABLE_STATUSES:
                raise UserError(_(
                    "Milestone '%s' has already been invoiced or paid and cannot "
                    "be removed. Raise an update instead.", rec.milestone_id.name))
            rec.write({'state': 'request'})
            rec.message_post(body=_(
                "Milestone change submitted for approval by %s.", self.env.user.name))
        return True

    def _do_approve(self, comment=None):
        self._check_can_decide()
        for rec in self:
            if rec.state != 'request':
                raise UserError(_(
                    "Only submitted requests (in Request state) can be approved."))
            if rec.change_type != 'add' and not rec.milestone_id:
                raise UserError(_(
                    "The milestone of request %s no longer exists.", rec.name))
            if rec.change_type == 'remove' and rec.milestone_id.status in UNREMOVABLE_STATUSES:
                raise UserError(_(
                    "Milestone '%s' has already been invoiced or paid and cannot "
                    "be removed.", rec.milestone_id.name))
            # The plan must still be complete afterwards (requirement 52),
            # measured against the milestones as they stand NOW, not when
            # the request was raised.
            total = rec._ft_resulting_total()
            if not ft_percent_is_100(total):
                raise UserError(_(
                    "Request %(name)s cannot be approved: the milestone "
                    "percentages of project '%(project)s' would add up to "
                    "%(total)s%% instead of 100%%. Adjust the request (or "
                    "approve a complementary one first).",
                    name=rec.name, project=rec.project_id.display_name,
                    total=ft_format_percent(total)))
            # Apply under sudo and both bypass keys: the plan lock of this
            # module and project_date_extension's due_date guard.
            Milestone = rec.milestone_id.sudo().with_context(**{
                CHANGE_APPROVAL_CONTEXT_KEY: True,
                'date_extension_approval': True,
            })
            if rec.change_type == 'update':
                vals = rec._ft_milestone_vals()
                if vals:
                    Milestone.write(vals)
                labels = {f: Milestone._fields[f].string for f in vals}
                summary = _("Milestone '%(old)s' updated: %(fields)s.",
                            old=rec.current_name,
                            fields=', '.join(
                                '%s = %s' % (labels[f], v) for f, v in vals.items())
                            or _("nothing changed"))
            elif rec.change_type == 'add':
                Milestone = self.env['project.custom.milestone'].sudo().with_context(**{
                    CHANGE_APPROVAL_CONTEXT_KEY: True,
                    'date_extension_approval': True,
                })
                created = Milestone.create(rec._ft_milestone_vals())
                rec.milestone_id = created.id
                summary = _("Milestone '%(name)s' (%(pct)s%%) added.",
                            name=created.name, pct=ft_format_percent(created.percentage))
            else:
                summary = _("Milestone '%(name)s' (%(pct)s%%) removed.",
                            name=rec.current_name,
                            pct=ft_format_percent(rec.current_percentage))
                Milestone.unlink()
            vals = {
                'state': 'approved',
                'approver_id': self.env.user.id,
                'decision_date': fields.Datetime.now(),
            }
            if comment:
                vals['approval_comment'] = comment
            rec.write(vals)
            # Markup: message_post escapes a plain str, so the line break
            # and bold tag must be marked as safe HTML and the user-entered
            # parts escaped explicitly.
            body = escape(_("Milestone change approved by %(user)s. %(summary)s "
                            "Plan total: %(total)s%%.",
                            user=self.env.user.name, summary=summary,
                            total=ft_format_percent(total)))
            if comment:
                body += Markup("<br/><b>%s</b> %s") % (_("Approval Comment:"), comment)
            rec.message_post(body=body)
        return True

    def _do_reject(self, reason=None):
        self._check_can_decide()
        for rec in self:
            if rec.state != 'request':
                raise UserError(_(
                    "Only submitted requests (in Request state) can be rejected."))
            reason = (reason or rec.rejection_reason or '').strip()
            if not reason:
                raise UserError(_("Please give the reason for rejecting the request."))
            rec.write({
                'state': 'rejected',
                'approver_id': self.env.user.id,
                'decision_date': fields.Datetime.now(),
                'rejection_reason': reason,
            })
            rec.message_post(body=Markup("%s<br/><b>%s</b> %s") % (
                _("Milestone change rejected by %s.", self.env.user.name),
                _("Rejection Reason:"), reason))
        return True

    def action_approve(self):
        """Approve straight away; the optional Approval Comment field on the
        form is taken as the comment."""
        self._check_can_decide()
        return self._do_approve(comment=self.env.context.get('comment'))

    def action_reject(self):
        """Opens the small reason wizard, unless ``skip_wizard`` is set (then
        the Rejection Reason field / ``comment`` context must be filled)."""
        self._check_can_decide()
        self.ensure_one()
        if self.env.context.get('skip_wizard'):
            return self._do_reject(reason=self.env.context.get('comment'))
        return {
            'name': _('Reject Milestone Change'),
            'type': 'ir.actions.act_window',
            'res_model': 'ft.milestone.change.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_request_id': self.id},
        }

    def action_reset_to_draft(self):
        """A rejected request may be reworked and resubmitted."""
        self._check_can_decide()
        for rec in self:
            if rec.state != 'rejected':
                raise UserError(_("Only rejected requests can be reset to draft."))
            rec.write({
                'state': 'draft',
                'approver_id': False,
                'decision_date': False,
                'rejection_reason': False,
                'approval_comment': False,
            })
        return True
