# -*- coding: utf-8 -*-
"""AMC task approval.

A completed task of an AMC project is approved or rejected by an approver:
the project's Project Manager (project.user_id), anybody whose job position
is one of PM_JOB_NAMES or a Team Lead role (_PWF_AMC_LEAD_JOB_NAMES), or an
Administrator (base.group_system).

The rules are enforced in write()/create() so they hold for every path -
form, list multi-edit, import and RPC - and are skipped only under
superuser. Approvers frequently have no write access on the task, so the
buttons (action_pwf_amc_*) validate as the real user and then write via
sudo, stamping the real user as the approver.
"""
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.bt_project_customization.models.project_project import PM_JOB_NAMES

PWF_AMC_APPROVAL = [('approved', 'Approved'), ('rejected', 'Rejected')]
_PWF_AMC_GUARDED = ('pwf_amc_approval', 'pwf_amc_rejection_reason')
_PWF_AMC_STAMPS = ('pwf_amc_approved_by_id', 'pwf_amc_approved_on')
_PWF_AMC_LIST_LIMIT = 10
# Team Lead positions, as spelled in bt_project_customization
# (DEVELOPER_JOB_NAMES / TESTER_JOB_NAMES), plus the generic 'team lead'.
_PWF_AMC_LEAD_JOB_NAMES = ('technical lead', 'testing lead', 'tester lead', 'team lead')
_PWF_AMC_APPROVER_JOB_NAMES = frozenset(PM_JOB_NAMES) | frozenset(_PWF_AMC_LEAD_JOB_NAMES)


def _pwf_amc_task_lines(tasks):
    """Bullet list naming up to 10 tasks, plus a count of the rest."""
    lines = ['- %s (#%s)' % (task.sudo().display_name or task.sudo().name or '', task.id)
             for task in tasks[:_PWF_AMC_LIST_LIMIT]]
    if len(tasks) > _PWF_AMC_LIST_LIMIT:
        lines.append(_('... and %s more', len(tasks) - _PWF_AMC_LIST_LIMIT))
    return '\n'.join(lines)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    pwf_amc_approval = fields.Selection(
        PWF_AMC_APPROVAL, string='Approval', tracking=True, copy=False, index=True,
        help="Approval of a completed AMC task by the Project Manager.")
    pwf_amc_approved_by_id = fields.Many2one(
        'res.users', string='Approved / Rejected By', readonly=True, copy=False)
    pwf_amc_approved_on = fields.Datetime(
        string='Approved / Rejected On', readonly=True, copy=False)
    pwf_amc_rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    pwf_amc_is_completed = fields.Boolean(
        string='Completed (Final Stage)', compute='_compute_pwf_amc_is_completed',
        search='_search_pwf_amc_is_completed')
    pwf_amc_can_approve = fields.Boolean(
        string='Can Approve', compute='_compute_pwf_amc_can_approve',
        help="The current user may approve / reject this task now: it is an "
             "AMC task, it is completed and the user is an approver.")

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('stage_id', 'stage_id.fold', 'stage_id.name')
    def _compute_pwf_amc_is_completed(self):
        final_ids = set(self._ft_final_stage_ids()) if self else set()
        for task in self:
            task.pwf_amc_is_completed = task.stage_id.id in final_ids

    def _search_pwf_amc_is_completed(self, operator, value):
        # Odoo 19 normalises ('f', '=', True) to ('f', 'in', [True]) and
        # ('f', '=', False) to ('f', 'not in', [True]); '='/'!=' are kept for
        # direct callers.
        if operator in ('in', 'not in'):
            values = {bool(v) for v in (value or ())}
            if len(values) != 1:
                # in [True, False] / not in [] -> everything; the opposite -> nothing.
                everything = (operator == 'in') == (len(values) == 2)
                return [] if everything else [('id', 'in', [])]
            positive = (True in values) == (operator == 'in')
        elif operator in ('=', '!='):
            positive = bool(value) == (operator == '=')
        else:
            return NotImplemented
        final_ids = self._ft_final_stage_ids()
        if positive:
            return [('stage_id', 'in', final_ids)]
        return ['|', ('stage_id', '=', False), ('stage_id', 'not in', final_ids)]

    @api.depends('stage_id', 'project_id', 'project_id.user_id', 'ft_project_type')
    @api.depends_context('uid')
    def _compute_pwf_amc_can_approve(self):
        final_ids = set(self._ft_final_stage_ids()) if self else set()
        global_approver = self._pwf_amc_is_global_approver() if self else False
        for task in self:
            task.pwf_amc_can_approve = bool(
                task.ft_project_type == 'amc'
                and task.stage_id.id in final_ids
                and (global_approver or task.sudo().project_id.user_id == self.env.user)
            )

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    @api.model
    def _pwf_amc_is_global_approver(self):
        """Administrator, or a PM-type / Team Lead job on any of the user's employees."""
        user = self.env.user
        if user.has_group('base.group_system'):
            return True
        employees = self.env['hr.employee'].sudo().with_context(active_test=False).search(
            [('user_id', '=', user.id)])
        return any((emp.job_id.name or '').strip().lower() in _PWF_AMC_APPROVER_JOB_NAMES
                   for emp in employees)

    def _pwf_amc_check_rules(self, vals=None, stage_id=None, check_reason=True):
        """Raise unless the current user may set the approval on every task.

        ``vals`` holds the values being written (pwf_amc_approval and/or
        pwf_amc_rejection_reason); fields missing from it keep the task's
        current value. ``stage_id`` is the stage the tasks are being moved to
        in the same write, if any. All tasks are validated before anything is
        written, so a bulk call is all-or-nothing.
        """
        if self.env.su or not self:
            return
        vals = vals or {}
        tasks = self.sudo()
        non_amc = tasks.filtered(lambda t: t.ft_project_type != 'amc')
        if non_amc:
            raise UserError(_(
                "Approval is only available on tasks of AMC projects.\n\n"
                "Not AMC:\n%s", _pwf_amc_task_lines(non_amc)))
        final_ids = set(self._ft_final_stage_ids())
        not_done = tasks.filtered(
            lambda t: (stage_id or t.stage_id.id) not in final_ids)
        if not_done:
            raise UserError(_(
                "Only a completed task (in a final stage) can be approved or "
                "rejected.\n\nNot completed:\n%s", _pwf_amc_task_lines(not_done)))
        if not self._pwf_amc_is_global_approver():
            if any(t.project_id.user_id != self.env.user for t in tasks):
                raise AccessError(_(
                    "Only the Project Manager of the project, a Project Manager / "
                    "Project Coordinator, a Team Lead or an Administrator can "
                    "approve or reject AMC tasks."))
        if check_reason:
            no_reason = tasks.filtered(lambda t: (
                (vals['pwf_amc_approval'] if 'pwf_amc_approval' in vals
                 else t.pwf_amc_approval) == 'rejected'
                and not ((vals['pwf_amc_rejection_reason'] if 'pwf_amc_rejection_reason' in vals
                          else t.pwf_amc_rejection_reason) or '').strip()
            ))
            if no_reason:
                raise UserError(_(
                    "A rejection reason is required to reject a task.\n\n"
                    "Missing reason:\n%s", _pwf_amc_task_lines(no_reason)))

    def _pwf_amc_stamp_vals(self, vals):
        """Return ``vals`` completed with approver / date / reason stamps."""
        if 'pwf_amc_approval' not in vals:
            return vals
        vals = dict(vals)
        if vals['pwf_amc_approval']:
            # env.uid stays the real user under sudo().
            vals.setdefault('pwf_amc_approved_by_id', self.env.uid)
            vals.setdefault('pwf_amc_approved_on', fields.Datetime.now())
            if vals['pwf_amc_approval'] == 'approved':
                vals['pwf_amc_rejection_reason'] = False
        else:
            vals.update(pwf_amc_approved_by_id=False, pwf_amc_approved_on=False)
            vals.setdefault('pwf_amc_rejection_reason', False)
        return vals

    @api.model
    def _pwf_amc_refuse_stamp_write(self, vals):
        if not self.env.su and any(f in vals for f in _PWF_AMC_STAMPS):
            raise AccessError(_(
                "The approver and approval date are set automatically and "
                "cannot be edited."))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._pwf_amc_refuse_stamp_write(vals)
        vals_list = [self._pwf_amc_stamp_vals(vals) for vals in vals_list]
        tasks = super().create(vals_list)
        if not self.env.su:
            guarded = tasks.filtered(
                lambda t: t.pwf_amc_approval or t.pwf_amc_rejection_reason)
            guarded._pwf_amc_check_rules()
        return tasks

    def write(self, vals):
        reopened_watch = self.browse()
        self._pwf_amc_refuse_stamp_write(vals)
        if any(f in vals for f in _PWF_AMC_GUARDED):
            if not self.env.su:
                if 'pwf_amc_approval' in vals:
                    # Every task is (re)stamped, so every task is checked -
                    # also those whose value does not change.
                    checked = self
                else:
                    checked = self.filtered(lambda t: (t.pwf_amc_rejection_reason or False)
                                            != (vals['pwf_amc_rejection_reason'] or False))
                checked._pwf_amc_check_rules(vals, stage_id=vals.get('stage_id'))
            vals = self._pwf_amc_stamp_vals(vals)
        if 'stage_id' in vals and 'pwf_amc_approval' not in vals:
            final_ids = set(self._ft_final_stage_ids())
            reopened_watch = self.sudo().filtered(
                lambda t: t.pwf_amc_approval == 'approved' and t.stage_id.id in final_ids)
        res = super().write(vals)
        if reopened_watch:
            final_ids = set(self._ft_final_stage_ids())
            reopened = reopened_watch.filtered(lambda t: t.stage_id.id not in final_ids)
            if reopened:
                reopened.write({'pwf_amc_approval': False})
                for task in reopened:
                    task.message_post(
                        body=_("AMC approval reset: the task was moved back out "
                               "of a completed stage (to %s).", task.stage_id.name or ''),
                        subtype_xmlid='mail.mt_note')
        return res

    # ------------------------------------------------------------------
    # actions (bulk-capable)
    # ------------------------------------------------------------------
    def _pwf_amc_apply(self, value, reason=False):
        tasks = self.exists()
        if not tasks:
            raise UserError(_("Select at least one task."))
        vals = {'pwf_amc_approval': value}
        if value == 'rejected':
            vals['pwf_amc_rejection_reason'] = reason
        # Validated as the real user, for every task, before anything is written.
        tasks._pwf_amc_check_rules(vals)
        tasks.sudo().write(vals)
        user = self.env.user.name or ''
        for task in tasks.sudo():
            if value == 'approved':
                body = _("AMC task approved by %s.", user)
            elif value == 'rejected':
                body = Markup('%s<br/>%s') % (
                    _("AMC task rejected by %s.", user),
                    _("Reason: %s", reason or ''),
                )
            else:
                body = _("AMC approval reset by %s.", user)
            task.message_post(body=body, subtype_xmlid='mail.mt_note')
        return tasks

    @api.model
    def _pwf_amc_notification(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("AMC Approval"),
                'message': message,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_pwf_amc_approve(self):
        tasks = self._pwf_amc_apply('approved')
        return self._pwf_amc_notification(_("%s task(s) approved.", len(tasks)))

    def action_pwf_amc_reset(self):
        tasks = self._pwf_amc_apply(False)
        return self._pwf_amc_notification(_("%s task(s) reset.", len(tasks)))

    def action_pwf_amc_reject(self):
        tasks = self.exists()
        if not tasks:
            raise UserError(_("Select at least one task."))
        # Check everything but the reason now, so the wizard is not opened
        # for a selection that will be refused anyway.
        tasks._pwf_amc_check_rules({'pwf_amc_approval': 'rejected'}, check_reason=False)
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject AMC Task(s)"),
            'res_model': 'ft.pms.amc.reject.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_task_ids': [(6, 0, tasks.ids)]},
        }


class FtPmsAmcRejectWizard(models.TransientModel):
    _name = 'ft.pms.amc.reject.wizard'
    _description = 'Reject AMC Task'

    task_ids = fields.Many2many('project.task', string='Tasks')
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_("A rejection reason is required."))
        tasks = self.task_ids._pwf_amc_apply('rejected', self.reason.strip())
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("AMC Approval"),
                'message': _("%s task(s) rejected.", len(tasks)),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
