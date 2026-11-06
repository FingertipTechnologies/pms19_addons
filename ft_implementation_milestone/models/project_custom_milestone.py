# -*- coding: utf-8 -*-
"""Requirement 56: once an Implementation project has left KICKOFF its payment
milestone plan is an agreement with the customer. Names, percentages, amounts
and dates can then only change through an approved Milestone Change Request;
the Date Extension Approvers keep their direct edit right, exactly as they do
for the due date in project_date_extension.

The rule is enforced here, in create / write / unlink, so the project form's
inline list, the standalone milestone views, imports and RPC all obey it. The
``ft_milestone_plan_locked`` flag only mirrors it in the views.

project_date_extension's own write() guard on ``due_date`` runs AFTER this one
(it sits lower in the MRO) and is left untouched: a normal user is refused the
date change here first, an approver passes both.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import email_normalize, float_compare

_logger = logging.getLogger(__name__)

from .milestone_template import ft_format_percent

APPROVER_GROUP = 'project_date_extension.group_project_date_extension_approver'
# Context key under which an approved Milestone Change Request applies its
# change. Together with superuser and the approver group it is the only way
# past the plan lock.
CHANGE_APPROVAL_CONTEXT_KEY = 'ft_milestone_change_approval'
# Context key carrying {project id: locked?} as it stood BEFORE the project
# write that is in progress (see project.project.write). A PM who enters the
# plan and moves KICKOFF -> DISC in one save must not be refused because the
# new stage is already in the cache when the milestone lines are written.
LOCK_SNAPSHOT_CONTEXT_KEY = 'ft_milestone_lock_snapshot'
# Once a milestone is Completed (or any later status) it is frozen: only the
# status may move forward and the paid amount be recorded; the chatter and
# activities stay usable. Only the superuser (system jobs) bypasses it.
FT_DONE_EDITABLE_FIELDS = ('status', 'paid_amount')
# The agreed plan: everything a change request may alter. Status, paid
# amount, hours, attachments and description stay editable after lock.
LOCKED_FIELDS = ('name', 'percentage', 'amount', 'due_date', 'project_id')
COMPLETION_TEMPLATE_XMLID = 'ft_implementation_milestone.mail_template_milestone_completed'


class ProjectCustomMilestone(models.Model):
    _inherit = 'project.custom.milestone'

    ft_milestone_done_locked = fields.Boolean(
        string='Completed (Locked)', compute='_compute_ft_milestone_done_locked',
        help='Technical: True once the milestone is Completed or later; it '
             'can then no longer be changed (only status and paid amount).')
    ft_milestone_plan_locked = fields.Boolean(
        string='Plan Locked', compute='_compute_ft_milestone_plan_locked',
        help='Technical: True when this user may not change the name, '
             'percentage, amount or date directly (the project has left '
             'KICKOFF and the user is no Date Extension Approver). The '
             'server enforces it; the views mirror it.')
    ft_change_request_ids = fields.One2many(
        'ft.milestone.change.request', 'milestone_id',
        string='Milestone Change Requests')
    ft_change_request_count = fields.Integer(
        compute='_compute_ft_change_request_count')

    # ------------------------------------------------------------------
    # Requirement 52: a share of the contract is between 0 and 100 percent
    # ------------------------------------------------------------------
    @api.constrains('percentage')
    def _check_ft_percentage_range(self):
        for milestone in self:
            if milestone.percentage < 0 or milestone.percentage > 100:
                raise ValidationError(_(
                    "The percentage of milestone '%(name)s' must be between 0 "
                    "and 100 (got %(value)s).",
                    name=milestone.name,
                    value=ft_format_percent(milestone.percentage)))

    # ------------------------------------------------------------------
    # Lock
    # ------------------------------------------------------------------
    @api.model
    def _ft_milestone_user_may_bypass(self):
        """Superuser, the change-request approval itself, and the Date
        Extension Approvers may edit a locked plan directly."""
        return bool(
            self.env.su
            or self.env.context.get(CHANGE_APPROVAL_CONTEXT_KEY)
            or self.env.user.has_group(APPROVER_GROUP)
        )

    @api.depends('status')
    def _compute_ft_milestone_done_locked(self):
        for milestone in self:
            milestone.ft_milestone_done_locked = milestone._ft_is_done()

    def _ft_is_done(self):
        self.ensure_one()
        return bool(self.status) and self.status != 'not_started'

    def _ft_check_done_lock(self, vals=None):
        """Refuse any change to a Completed (or later) milestone, and its
        deletion (vals=None). Status may only move forward, never back to
        Not Started; the paid amount and the chatter stay editable."""
        if self.env.su:
            return
        done = self.filtered(lambda m: m._ft_is_done())
        if not done:
            return
        if vals is not None:
            blocked = [
                f for f in vals
                if f not in FT_DONE_EDITABLE_FIELDS
                and not f.startswith(('message_', 'activity_'))
            ]
            if vals.get('status') == 'not_started':
                blocked.append('status')
            if not blocked:
                return
            action = _("changed")
        else:
            action = _("deleted")
        raise UserError(_(
            "Completed milestones cannot be %(action)s: %(names)s.\n\n"
            "Once a milestone is Completed only its status (forward) and "
            "paid amount can be updated.",
            action=action, names=', '.join(done.mapped('display_name'))))

    @api.depends('project_id.ft_milestone_plan_locked')
    @api.depends_context('uid', CHANGE_APPROVAL_CONTEXT_KEY)
    def _compute_ft_milestone_plan_locked(self):
        bypass = self._ft_milestone_user_may_bypass()
        for milestone in self:
            milestone.ft_milestone_plan_locked = bool(
                milestone.project_id.ft_milestone_plan_locked and not bypass)

    @api.depends('ft_change_request_ids')
    def _compute_ft_change_request_count(self):
        for milestone in self:
            milestone.ft_change_request_count = len(milestone.ft_change_request_ids)

    def _ft_project_plan_locked(self, project):
        """Locked state of ``project``, read from the pre-write snapshot when
        a project write is in progress (see LOCK_SNAPSHOT_CONTEXT_KEY)."""
        snapshot = self.env.context.get(LOCK_SNAPSHOT_CONTEXT_KEY) or {}
        if project.id in snapshot:
            return snapshot[project.id]
        return project._ft_milestone_plan_is_locked()

    def _ft_check_plan_lock(self, projects, action):
        """Refuse ``action`` ('create' / 'write' / 'unlink') on the milestones
        of any locked project, for users who may not bypass the lock."""
        if self._ft_milestone_user_may_bypass():
            return
        locked = projects.filtered(lambda p: p and self._ft_project_plan_locked(p))
        if not locked:
            return
        verbs = {
            'create': _("add a milestone to"),
            'write': _("change the agreed milestones of"),
            'unlink': _("remove a milestone from"),
        }
        raise UserError(_(
            "You cannot %(verb)s project '%(project)s': its payment milestone "
            "plan is locked because the project has left KICKOFF.\n\n"
            "Milestone names, percentages, amounts and dates can only be "
            "changed through an approved Milestone Change Request "
            "(Milestones > Milestone Change Requests). Status, paid amount, "
            "hours and attachments stay editable.",
            verb=verbs[action],
            project=', '.join(locked.mapped('display_name')),
        ))

    def _ft_locked_values_changed(self, vals):
        """True when ``vals`` really changes one of LOCKED_FIELDS on this
        record. A write re-stating the current value (the form sends only
        dirty fields, but RPC callers may not) is not a plan change."""
        self.ensure_one()
        for fname in LOCKED_FIELDS:
            if fname not in vals:
                continue
            field = self._fields[fname]
            new = vals[fname]
            current = self[fname]
            if field.type == 'many2one':
                current = current.id
                if isinstance(new, models.BaseModel):
                    new = new.id
            elif field.type == 'date':
                new = fields.Date.to_date(new) if new else False
            elif field.type == 'float':
                if float_compare(current or 0.0, new or 0.0, precision_digits=4):
                    return True
                continue
            if (current or False) != (new or False):
                return True
        return False

    @api.model_create_multi
    def create(self, vals_list):
        if not self._ft_milestone_user_may_bypass():
            Project = self.env['project.project']
            projects = Project.browse(
                {vals['project_id'] for vals in vals_list if vals.get('project_id')})
            self._ft_check_plan_lock(projects, 'create')
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Customer e-mail on completion
    # ------------------------------------------------------------------
    def _ft_milestone_completion_candidates(self):
        """The milestones of ``self`` whose completion is e-mailed: payment
        milestones of an Implementation project with the switch on. AMC
        monthly milestones (ft_amc_payment_milestone) have their own e-mail
        and are excluded by their flag when that module is installed."""
        return self.filtered(
            lambda m: m.project_id.ft_project_type == 'implementation'
            and m.project_id.ft_milestone_completion_email
            and not ('is_amc_monthly' in m._fields and m.is_amc_monthly))

    def _ft_milestone_send_completion_email(self):
        """Queue the "Milestone Completed" e-mail to the project's customer
        for every milestone of ``self`` and log it on the project. A
        customer without e-mail address gets a chatter note instead; nothing
        here ever blocks the status change."""
        template = self.env.ref(COMPLETION_TEMPLATE_XMLID, raise_if_not_found=False)
        if not template:
            return
        for milestone in self:
            project = milestone.project_id
            partner = project.partner_id
            email = partner.email if partner and email_normalize(partner.email or '') else False
            if not email:
                milestone.message_post(body=_(
                    "Milestone '%s' completed: no e-mail sent, the customer has "
                    "no e-mail address.", milestone.name))
                continue
            try:
                # Queued (no force_send): a rollback discards the mail too.
                template.sudo().send_mail(
                    milestone.id, force_send=False,
                    email_values={'email_to': email, 'recipient_ids': [],
                                  'auto_delete': False})
            except Exception as exc:  # noqa: BLE001 - never block the status change
                _logger.exception("Milestone %s: completion e-mail failed", milestone.id)
                milestone.message_post(body=_(
                    "Milestone '%(name)s' completed: the customer e-mail could "
                    "not be prepared (%(error)s).",
                    name=milestone.name, error=str(exc) or exc.__class__.__name__))
                continue
            milestone.message_post(body=_(
                "Milestone '%(name)s' completed: e-mail sent to %(email)s.",
                name=milestone.name, email=email))

    def write(self, vals):
        completing = self.browse()
        if vals.get('status') == 'completed':
            completing = self.filtered(lambda m: m.status != 'completed')
        self._ft_check_done_lock(vals)
        res = self._ft_write_locked(vals)
        if completing:
            completing._ft_milestone_completion_candidates()._ft_milestone_send_completion_email()
        return res

    def _ft_write_locked(self, vals):
        if set(vals) & set(LOCKED_FIELDS) and not self._ft_milestone_user_may_bypass():
            changed = self.filtered(lambda m: m._ft_locked_values_changed(vals))
            # The project a milestone is moved TO is locked as well: adding to
            # a locked plan through a re-parenting is still adding to it.
            projects = changed.mapped('project_id')
            if changed and vals.get('project_id'):
                target = vals['project_id']
                if isinstance(target, models.BaseModel):
                    target = target.id
                projects |= self.env['project.project'].browse(target)
            self._ft_check_plan_lock(projects, 'write')
        return super(ProjectCustomMilestone, self).write(vals)

    def unlink(self):
        self._ft_check_done_lock()
        if not self._ft_milestone_user_may_bypass():
            self._ft_check_plan_lock(self.mapped('project_id'), 'unlink')
        return super().unlink()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_ft_request_change(self):
        """New Milestone Change Request for this milestone, pre-filled."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Milestone Change Request'),
            'res_model': 'ft.milestone.change.request',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_project_id': self.project_id.id,
                'default_milestone_id': self.id,
                'default_change_type': 'update',
            },
        }

    def action_ft_view_change_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'ft_implementation_milestone.action_ft_milestone_change_request')
        action.update({
            'domain': [('milestone_id', '=', self.id)],
            'context': {
                **self.env.context,
                'default_project_id': self.project_id.id,
                'default_milestone_id': self.id,
            },
        })
        return action
