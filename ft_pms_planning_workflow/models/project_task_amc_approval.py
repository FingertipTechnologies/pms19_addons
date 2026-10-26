# -*- coding: utf-8 -*-
"""Task approval (AMC projects only).

A task of an AMC project (project_id.ft_project_type == 'amc'), at any
stage, is approved or rejected by an approver:
the project's Project Manager (project.user_id), anybody whose job position
is one of PM_JOB_NAMES or a Team Lead role (_PWF_AMC_LEAD_JOB_NAMES), or an
Administrator (base.group_system).

The rules are enforced in write()/create() so they hold for every path -
form, list multi-edit, import and RPC - and are skipped only under
superuser. Approvers frequently have no write access on the task, so the
buttons (action_pwf_amc_*) validate as the real user and then write via
sudo, stamping the real user as the approver.

Implementation and General projects do not use task-level approval (their
work is reviewed through the weekly timesheet approval only): approve /
reject / reset and direct writes of the approval are refused on their tasks,
and the form hides the buttons and the Approval section. Values already
stored on such tasks (from when approval applied to every project type) are
left untouched - no migration - but can no longer be changed.
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
        help="Approval of an AMC task (at any stage) by the Project Manager or another approver.")
    pwf_amc_approved_by_id = fields.Many2one(
        'res.users', string='Approved / Rejected By', readonly=True, copy=False)
    pwf_amc_approved_on = fields.Datetime(
        string='Approved / Rejected On', readonly=True, copy=False)
    pwf_amc_rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    # Informational only (and searchable): approval does NOT depend on it.
    pwf_amc_is_completed = fields.Boolean(
        string='Completed (Final Stage)', compute='_compute_pwf_amc_is_completed',
        search='_search_pwf_amc_is_completed',
        help="The task is in a final (completed) stage. Informational only: "
             "tasks can be approved in any stage.")
    pwf_amc_can_approve = fields.Boolean(
        string='Can Approve', compute='_compute_pwf_amc_can_approve',
        help="The current user may approve / reject this task: it belongs "
             "to an AMC project and the user is an approver.")

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

    @api.depends('stage_id', 'project_id', 'project_id.user_id', 'project_id.ft_project_type')
    @api.depends_context('uid')
    def _compute_pwf_amc_can_approve(self):
        global_approver = self._pwf_amc_is_global_approver() if self else False
        for task in self:
            project = task.sudo().project_id
            task.pwf_amc_can_approve = bool(
                project
                and project.ft_project_type == 'amc'
                and (global_approver or project.user_id == self.env.user)
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
        written, so a bulk call is all-or-nothing. Only tasks of AMC
        projects can be approved: a selection containing any Implementation /
        General task is refused as a whole.

        The task's stage is deliberately NOT checked: an approver may approve
        or reject a task in any stage (Working, Testing, Completed, ...), and
        approving never changes the stage.
        """
        if self.env.su or not self:
            return
        vals = vals or {}
        tasks = self.sudo()
        no_project = tasks.filtered(lambda t: not t.project_id)
        if no_project:
            raise UserError(_(
                "Approval is only available on tasks that belong to a project.\n\n"
                "Without a project:\n%s", _pwf_amc_task_lines(no_project)))
        non_amc = tasks.filtered(lambda t: t.project_id.ft_project_type != 'amc')
        if non_amc:
            first = non_amc[0]
            type_labels = dict(first.project_id._fields['ft_project_type']
                               ._description_selection(self.env))
            message = _(
                "Task approval is only used on AMC projects. '%(task)s' belongs "
                "to a %(type)s project.",
                task=first.display_name or first.name or '',
                type=type_labels.get(first.project_id.ft_project_type) or _("non-AMC"))
            if len(non_amc) > 1:
                message += "\n\n" + _(
                    "Tasks not on an AMC project:\n%s", _pwf_amc_task_lines(non_amc))
            raise UserError(message)
        if not self._pwf_amc_is_global_approver():
            if any(t.project_id.user_id != self.env.user for t in tasks):
                raise AccessError(_(
                    "Only the Project Manager of the project, a Project Manager / "
                    "Project Coordinator, a Team Lead or an Administrator can "
                    "approve or reject tasks."))
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
        # Approval is independent of the stage: moving the task does not
        # touch it.
        return super().write(vals)

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
        # Not named `user`: _() reads a local `user` to pick the language.
        approver_name = self.env.user.name or ''
        for task in tasks.sudo():
            if value == 'approved':
                body = _("Task approved by %s.", approver_name)
            elif value == 'rejected':
                body = Markup('%s<br/>%s') % (
                    _("Task rejected by %s.", approver_name),
                    _("Reason: %s", reason or ''),
                )
            else:
                body = _("Approval reset by %s.", approver_name)
            task.message_post(body=body, subtype_xmlid='mail.mt_note')
        return tasks

    @api.model
    def _pwf_amc_notification(self, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Task Approval"),
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
            'name': _("Reject Task(s)"),
            'res_model': 'ft.pms.amc.reject.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_task_ids': [(6, 0, tasks.ids)]},
        }


class FtPmsAmcRejectWizard(models.TransientModel):
    _name = 'ft.pms.amc.reject.wizard'
    _description = 'Reject Task'

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
                'title': _("Task Approval"),
                'message': _("%s task(s) rejected.", len(tasks)),
                'type': 'warning',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
