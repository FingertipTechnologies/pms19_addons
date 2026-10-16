# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class FtPmsStageApproval(models.Model):
    """Administrator approval for a gated project stage move (UAT).

    Requested by the Project Manager (or an admin); approved or rejected by
    base.group_system only. Approving re-runs every gate through the regular
    ``project.project.write`` and moves the project; it refuses a stale
    request (the project left the stage it was requested from).
    """
    _name = 'ft.pms.stage.approval'
    _description = 'PMS Stage Approval Request'
    _inherit = ['mail.thread']
    _order = 'request_date desc, id desc'
    # Project users hold read-only access; they may still discuss the request.
    _mail_post_access = 'read'

    name = fields.Char(compute='_compute_name', store=True)
    project_id = fields.Many2one(
        'project.project', string='Project', required=True, readonly=True,
        index=True, ondelete='cascade', tracking=True)
    from_stage_id = fields.Many2one(
        'project.project.stage', string='Requested From Stage', readonly=True,
        ondelete='set null')
    target_stage_id = fields.Many2one(
        'project.project.stage', string='Target Stage', required=True,
        readonly=True, ondelete='restrict', tracking=True)
    requested_by_id = fields.Many2one(
        'res.users', string='Requested By', readonly=True,
        default=lambda self: self.env.user)
    request_date = fields.Datetime(
        string='Requested On', readonly=True, default=fields.Datetime.now)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='pending', required=True, readonly=True,
        tracking=True, index=True)
    decided_by_id = fields.Many2one('res.users', string='Decided By', readonly=True)
    decided_on = fields.Datetime(string='Decided On', readonly=True)
    rejection_reason = fields.Text(string='Rejection Reason', readonly=True)
    company_id = fields.Many2one(
        related='project_id.company_id', store=True, string='Company')

    _pwf_one_pending = models.UniqueIndex(
        "(project_id, target_stage_id) WHERE state = 'pending'",
        "There is already a pending approval request for this project and stage.",
    )

    @api.depends('project_id.name', 'target_stage_id.name')
    def _compute_name(self):
        for approval in self:
            approval.name = '%s → %s' % (
                approval.project_id.name or '', approval.target_stage_id.name or '')

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        seen = set()
        for vals in vals_list:
            key = (vals.get('project_id'), vals.get('target_stage_id'))
            if vals.get('state', 'pending') != 'pending':
                continue
            if key in seen or self.sudo().search_count([
                ('project_id', '=', key[0]),
                ('target_stage_id', '=', key[1]),
                ('state', '=', 'pending'),
            ]):
                raise ValidationError(_(
                    "There is already a pending approval request for this "
                    "project and stage."))
            seen.add(key)
        return super().create(vals_list)

    _PWF_DECISION_FIELDS = (
        'state', 'decided_by_id', 'decided_on', 'rejection_reason',
        'project_id', 'from_stage_id', 'target_stage_id',
    )

    def write(self, vals):
        if (not self.env.su
                and not self.env.context.get('pwf_approval_decision')
                and any(f in vals for f in self._PWF_DECISION_FIELDS)):
            raise AccessError(_(
                "Use the Approve / Reject / Cancel buttons to change an "
                "approval request."))
        return super().write(vals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _pwf_check_approver(self):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_("Only an Administrator can approve or reject stage requests."))

    def _pwf_lock_pending(self):
        """Row-lock the requests and make sure each is still pending."""
        self.lock_for_update()
        self.invalidate_recordset(['state'])
        for approval in self:
            if approval.state != 'pending':
                raise UserError(_(
                    "Approval request '%(name)s' has already been %(state)s.",
                    name=approval.name,
                    state=dict(self._fields['state'].selection).get(approval.state),
                ))

    def _pwf_decide(self, vals):
        self.with_context(pwf_approval_decision=True).write(dict(
            vals,
            decided_by_id=self.env.user.id,
            decided_on=fields.Datetime.now(),
        ))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_approve(self):
        self._pwf_check_approver()
        for approval in self:
            approval._pwf_lock_pending()
            # Never under sudo: the gates (and bt's date requirements) must run.
            project = approval.project_id.sudo(False)
            if project.stage_id != approval.from_stage_id:
                raise UserError(_(
                    "Approval request '%(name)s' is out of date: the project is "
                    "now in '%(current)s', not '%(requested)s'. Reject or cancel "
                    "it and raise a new request.",
                    name=approval.name,
                    current=project.stage_id.name or '-',
                    requested=approval.from_stage_id.name or '-',
                ))
            project.with_context(pwf_approval_id=approval.id).write(
                {'stage_id': approval.target_stage_id.id})
            approval._pwf_decide({'state': 'approved'})
            approval.message_post(body=_("Approved; project moved to %s.",
                                         approval.target_stage_id.name))
        return True

    def action_reject(self):
        self._pwf_check_approver()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject Approval Request'),
            'res_model': 'ft.pms.stage.approval.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_approval_ids': self.ids},
        }

    def _pwf_do_reject(self, reason):
        self._pwf_check_approver()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_("A reason is required to reject an approval request."))
        self._pwf_lock_pending()
        self._pwf_decide({'state': 'rejected', 'rejection_reason': reason})
        for approval in self:
            approval.message_post(body=_("Rejected: %s", reason))
            approval.project_id.sudo().message_post(body=_(
                "Approval to move to %(stage)s rejected: %(reason)s",
                stage=approval.target_stage_id.name, reason=reason))
        return True

    def action_cancel(self):
        is_admin = self.env.su or self.env.user.has_group('base.group_system')
        for approval in self:
            if not is_admin and approval.requested_by_id != self.env.user:
                raise AccessError(_(
                    "Only the requester or an Administrator can cancel this request."))
        self._pwf_lock_pending()
        self.sudo()._pwf_decide({'state': 'cancelled'})
        return True
