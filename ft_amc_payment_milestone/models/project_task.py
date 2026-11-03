# -*- coding: utf-8 -*-
"""Deployed task status (requirements 46-49) and the task <-> milestone link.

"Deployed" is a status of its own, separate from the Completed stage: a task
is finished when it reaches a final stage, deployed when the PM says the fix
is live at the customer. Only then - and only once it is AMC-approved - does
it become billable, and it is billed in the month it was deployed in:
``custom_milestone_id`` (project_date_extension's task <-> milestone link)
is set to the project's AMC monthly milestone of the deployment month, and
ALL the task's APPROVED timesheet hours (weekly timesheet approval,
``_ft_amc_approved_hours``) count there, whatever month they were logged in
(requirement 49).

Rights, as decided: the people ``_pwf_amc_is_global_approver`` accepts
(Administrator, PM / Project Coordinator jobs, Team Lead jobs) plus the
project's own Project Manager - the same circle that approves AMC tasks.
QA cannot mark deployments.

The three deployment fields are written only by the actions (validated as
the real user, written under sudo, exactly like pwf_amc_approval): a direct
write by a normal user is refused, so the list's multi-edit, imports and RPC
cannot bypass the rules.

Deployed is also a value of the task's standard Status (``state``), right
after Done: ``1_deployed``. ``ft_deployed`` stays the source of truth and
the two move together:

* Mark Deployed      -> ft_deployed = True,  state = 1_deployed
* Undo Deployed      -> ft_deployed = False, state = 1_done
* reopen (stage leaves a final stage) -> ft_deployed = False,
                                        state = 01_in_progress
* a user setting the Status widget to 1_deployed is refused (the buttons own
  the transition, with their rights check); setting any other status on a
  deployed task undoes the deployment through the same rules first (the
  user needs the Undo right, else the write is refused).
"""
import logging
from datetime import timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.ft_amc_monthly_timesheet.models.periods import month_start
from odoo.addons.ft_pms_planning_workflow.models.project_task_amc_approval import _pwf_amc_task_lines
from odoo.addons.project.models.project_task import CLOSED_STATES

from .project_custom_milestone import AMC_INVOICED_STATUSES, AMC_OPEN_STATUSES, amc_fmt_hours

_logger = logging.getLogger(__name__)

_FT_DEPLOY_FIELDS = ('ft_deployed', 'ft_deployed_date', 'ft_deployed_by_id')

FT_DEPLOYED_STATE = '1_deployed'

# Deployed is a CLOSED state. Core project keeps the closed states in this
# module-level dict and reads it at runtime everywhere "closed" matters:
# _compute_state keeps a task whose state is in it (otherwise a stage move
# would reset a deployed task to In Progress), is_closed / _search_is_closed
# (the Open and Closed filters, task_ids on the project), OPEN_STATES, the
# dependency "waiting" logic, the closed subtask / milestone / sale order
# counters and the rotting rules. Registering the value here, at import,
# makes all of that treat Deployed exactly like Done. The core `state`
# selection, however, was built from the dict when core's class body ran -
# before this module was imported - so the value still has to be added to
# the field with selection_add below.
CLOSED_STATES.setdefault(FT_DEPLOYED_STATE, 'Billable')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # Deployed right after Done: the two singleton anchors pin it between
    # Done and Cancelled (merge_sequences only honours the relative order and
    # otherwise biases a new value towards the END of the list, so a single
    # "after Done" anchor would land it last). The field is required, so
    # uninstalling this module must map the value back to something core
    # knows: Done.
    state = fields.Selection(
        selection_add=[('1_done',), (FT_DEPLOYED_STATE, 'Billable'), ('1_canceled',)],
        ondelete={FT_DEPLOYED_STATE: lambda recs: recs.write({'state': '1_done'})})

    ft_deployed = fields.Boolean(
        string='Billable', tracking=True, copy=False, index=True,
        help="The completed work is live at the customer (AMC projects). Set "
             "with 'Mark Billable'; an approved, billable task is billed in "
             "the AMC milestone of the month it was marked billable in.")
    ft_deployed_date = fields.Datetime(string='Marked Billable On', readonly=True, copy=False)
    ft_deployed_by_id = fields.Many2one(
        'res.users', string='Marked Billable By', readonly=True, copy=False)
    ft_deploy_state = fields.Selection([
        ('deployed', 'Billable'),
        ('to_deploy', 'To Bill'),
    ], string='Billable', compute='_compute_ft_deploy_state',
        help="Billable, or To Bill (AMC-approved and completed but not yet marked billable).")
    ft_can_deploy = fields.Boolean(
        string='Can Mark Billable', compute='_compute_ft_can_deploy',
        help="The current user may mark / undo billable status on this task: it "
             "belongs to an AMC project and the user is an AMC approver or "
             "the project's Project Manager.")

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('ft_deployed', 'pwf_amc_approval', 'stage_id', 'project_id.ft_project_type')
    def _compute_ft_deploy_state(self):
        for task in self:
            if task.ft_deployed:
                task.ft_deploy_state = 'deployed'
            elif (task.sudo().project_id.ft_project_type == 'amc'
                    and task.pwf_amc_approval == 'approved'
                    and task.pwf_amc_is_completed):
                task.ft_deploy_state = 'to_deploy'
            else:
                task.ft_deploy_state = False

    @api.depends('project_id', 'project_id.user_id', 'project_id.ft_project_type')
    @api.depends_context('uid')
    def _compute_ft_can_deploy(self):
        global_approver = self._pwf_amc_is_global_approver() if self else False
        for task in self:
            project = task.sudo().project_id
            task.ft_can_deploy = bool(
                project
                and project.ft_project_type == 'amc'
                and (global_approver or project.user_id == self.env.user))

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    def _ft_amc_check_deploy_rules(self, action):
        """Raise unless the current user may apply ``action`` ('deploy' /
        'undo') to EVERY task. Checked before anything is written, so a bulk
        call is all-or-nothing; the message names the offending tasks."""
        if self.env.su or not self:
            return
        tasks = self.sudo()
        global_approver = self._pwf_amc_is_global_approver()
        non_amc = tasks.filtered(lambda t: not t.project_id or t.project_id.ft_project_type != 'amc')
        if non_amc:
            raise UserError(_(
                "Billable status is only used on tasks of AMC projects.\n\n"
                "Not on an AMC project:\n%s", _pwf_amc_task_lines(non_amc)))
        if not global_approver:
            foreign = tasks.filtered(lambda t: t.project_id.user_id != self.env.user)
            if foreign:
                raise AccessError(_(
                    "Only the Project Manager of the project, a Project Manager / "
                    "Project Coordinator, a Team Lead or an Administrator can mark "
                    "tasks as Billable.\n\nNot allowed for:\n%s", _pwf_amc_task_lines(foreign)))
        problems = []
        for task in tasks:
            reasons = []
            if action == 'deploy':
                if not task.pwf_amc_is_completed:
                    reasons.append(_("not in a final (Completed) stage"))
                if task.state == '1_canceled':
                    reasons.append(_("cancelled"))
                if task.ft_deployed:
                    reasons.append(_("already marked Billable"))
            elif not task.ft_deployed:
                reasons.append(_("not marked Billable"))
            if reasons:
                problems.append('- %s (#%s): %s' % (task.display_name or task.name or '',
                                                    task.id, ', '.join(reasons)))
        if problems:
            verb = _("marked Billable") if action == 'deploy' else _("reset")
            raise UserError(_(
                "Nothing was changed: the following task(s) cannot be %(verb)s. "
                "Only completed (final stage), not cancelled AMC tasks can be "
                "billable.\n\n%(tasks)s", verb=verb, tasks='\n'.join(problems)))

    @api.model
    def _ft_amc_refuse_deploy_write(self, vals):
        """The deployment fields, and the Deployed status itself, are only
        ever written by the actions (sudo). The Status widget, multi-edit,
        imports and RPC cannot set ``state = 1_deployed`` directly."""
        if self.env.su:
            return
        error = AccessError(_(
            "The billable status is set with the 'Mark Billable' / "
            "'Undo Billable' buttons and cannot be edited directly."))
        if vals.get('state') == FT_DEPLOYED_STATE:
            raise error
        # The task form carries the deployment fields (invisible / read-only)
        # and the web client sends them back with their default (False) on
        # create and on save: only a value that is set, or really changed on
        # an existing task, is a direct edit.
        for fname in _FT_DEPLOY_FIELDS:
            if fname not in vals:
                continue
            new = vals[fname]
            if isinstance(new, models.BaseModel):
                new = new.id
            new = new or False
            if not self:
                if new:
                    raise error
                continue
            field = self._fields[fname]
            for task in self:
                current = task[fname]
                if field.type == 'many2one':
                    current = current.id
                if (current or False) != new:
                    raise error

    def _ft_amc_undo_on_status_change(self, vals):
        """A user moving a deployed task's Status away from Deployed (Done,
        In Progress, Cancelled... through the Status widget) is undoing the
        deployment: apply the Undo rules (rights, AMC project) and clear the
        flag first, the caller's write then sets the status they asked for.
        Refused with the rules' own error when the user may not undo."""
        if self.env.su or 'state' not in vals or vals['state'] == FT_DEPLOYED_STATE:
            return
        deployed = self.filtered('ft_deployed')
        if not deployed:
            return
        deployed._ft_amc_check_deploy_rules('undo')
        labels = dict(self._fields['state']._description_selection(self.env))
        deployed.sudo()._ft_amc_clear_deployed(
            _("the status was changed to %(status)s by %(user)s",
              status=labels.get(vals['state'], vals['state']),
              user=self.env.user.name or ''),
            state=None)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._ft_amc_refuse_deploy_write(vals)
        tasks = super().create(vals_list)
        deployed = tasks.filtered('ft_deployed')
        if deployed:
            deployed.sudo()._ft_amc_link_milestone()
        return tasks

    def write(self, vals):
        self._ft_amc_refuse_deploy_write(vals)
        self._ft_amc_undo_on_status_change(vals)
        # Reopen detection: a task leaving a final stage (only possible through
        # the reopen wizard, which writes under sudo) is no longer deployed.
        track_stage = 'stage_id' in vals
        was_final = {t.id: t.pwf_amc_is_completed for t in self} if track_stage else {}
        res = super().write(vals)
        if 'ft_deployed' in vals:
            if vals['ft_deployed']:
                self.sudo()._ft_amc_link_milestone()
            else:
                self.sudo()._ft_amc_unlink_milestone(_("the billable status was undone"))
        if 'pwf_amc_approval' in vals:
            # Approval arriving after deployment attaches the task; a reset /
            # rejection detaches it (while the milestone is still open).
            deployed = self.filtered('ft_deployed')
            if vals['pwf_amc_approval'] == 'approved':
                deployed.sudo()._ft_amc_link_milestone()
            else:
                deployed.sudo()._ft_amc_unlink_milestone(_("the AMC approval was reset or rejected"))
        if track_stage:
            reopened = self.filtered(
                lambda t: was_final.get(t.id) and not t.pwf_amc_is_completed and t.ft_deployed)
            if reopened:
                # Status back to In Progress (bt_project_customization already
                # did it for 1_done / 1_deployed in its own write; this is the
                # safety net for a task that is still 1_deployed).
                reopened.sudo()._ft_amc_clear_deployed(_("the task was reopened"),
                                                      state='01_in_progress')
        return res

    # ------------------------------------------------------------------
    # milestone link (requirements 42, 48, 49)
    # ------------------------------------------------------------------
    def _ft_amc_approved_hours(self):
        """Sum of the task's timesheet lines approved in the weekly review
        (account.analytic.line.ft_approval_state == 'approved', employee set
        so non-timesheet analytic lines never count). No date filter: the
        whole task is billed in its deployment month."""
        self.ensure_one()
        lines = self.sudo().timesheet_ids.filtered(
            lambda line: line.employee_id and line.ft_approval_state == 'approved')
        return sum(lines.mapped('unit_amount'))

    def _ft_amc_is_billing(self):
        """Billing task: it carries billable hours or approved timesheet
        hours. Only these are listed to the customer (requirement 48)."""
        self.ensure_one()
        return (self.ft_billable_hours or 0.0) > 0 or self._ft_amc_approved_hours() > 0

    def _ft_amc_deployment_day(self):
        """Calendar day of the deployment in the project company's time zone
        (the zone ft_amc_monthly_timesheet reports in), so a deployment at
        23:30 IST on 31 Oct lands in October, not November."""
        self.ensure_one()
        company = self.project_id.company_id or self.env.company
        tzname = self.env['ft.amc.monthly.report']._company_tz(company)
        stamp = self.ft_deployed_date or fields.Datetime.now()
        return pytz.utc.localize(stamp).astimezone(pytz.timezone(tzname)).date()

    def _ft_amc_link_milestone(self):
        """Attach every deployed AND approved task to its project's AMC monthly
        milestone of the deployment month (created on the fly when the project
        is eligible). Meant to be called under sudo."""
        touched = self.env['project.custom.milestone']
        for task in self:
            if not (task.ft_deployed and task.pwf_amc_approval == 'approved'):
                continue
            project = task.project_id
            if not project or project.ft_project_type != 'amc':
                continue
            period_start = month_start(task._ft_amc_deployment_day())
            milestone = project._amc_ensure_monthly_milestone(period_start)
            # A month already sent / invoiced / paid is closed: its content
            # must not change, so the task goes to the next open month.
            moved_from = False
            tries = 0
            while (milestone and milestone.status not in AMC_OPEN_STATUSES
                   and task.custom_milestone_id != milestone and tries < 12):
                moved_from = moved_from or milestone
                tries += 1
                period_start = month_start(milestone.amc_period_end + timedelta(days=1))
                milestone = project._amc_ensure_monthly_milestone(period_start)
            if moved_from and not milestone:
                task.message_post(body=_(
                    "Billable and approved, but NOT attached: payment milestone "
                    "'%s' is already %s and the project has no later open AMC "
                    "milestone. Please check the contract dates.",
                    moved_from.display_name, moved_from._amc_status_label()),
                    subtype_xmlid='mail.mt_note')
                continue
            if not milestone:
                _logger.info("Task %s: no AMC milestone for %s (project %s not eligible).",
                             task.id, period_start.strftime('%Y-%m'), project.id)
                task.message_post(body=_(
                    "Billable and approved, but not attached to a payment milestone: "
                    "project '%(project)s' is not eligible for an AMC milestone in "
                    "%(period)s (closed, on hold, or contract dates not covering it).",
                    project=project.display_name,
                    period=milestone._amc_period_label(period_start)),
                    subtype_xmlid='mail.mt_note')
                continue
            if task.custom_milestone_id == milestone:
                continue
            task.write({'custom_milestone_id': milestone.id})
            touched |= milestone
            if moved_from:
                task.message_post(body=_(
                    "Attached to payment milestone '%(to)s': the billable "
                    "month ('%(month)s') is already %(status)s.",
                    to=milestone.display_name, month=moved_from.display_name,
                    status=moved_from._amc_status_label()), subtype_xmlid='mail.mt_note')
            else:
                task.message_post(body=_(
                    "Attached to payment milestone '%s' (billable month).",
                    milestone.display_name), subtype_xmlid='mail.mt_note')
            if milestone.status not in AMC_OPEN_STATUSES:
                # The customer already received this month's list: say so
                # rather than silently changing the billed hours.
                milestone.message_post(body=_(
                    "Task '%(task)s' was attached after the milestone was %(status)s; "
                    "approved hours are now %(hours)s.",
                    task=task.display_name, status=milestone._amc_status_label(),
                    hours=amc_fmt_hours(milestone.amc_hours)))
        touched._amc_refresh_report(_("task attached"))

    def _ft_amc_unlink_milestone(self, reason):
        """Detach from the AMC monthly milestone unless the month is already
        invoiced / paid: then the link is kept and a note explains why. A
        month that was only sent (Completed / Client Approved) is detached
        too, with a note on the milestone so the list is sent again."""
        touched = self.env['project.custom.milestone']
        for task in self:
            milestone = task.custom_milestone_id
            if not milestone or not milestone.is_amc_monthly:
                continue
            if milestone.status not in AMC_INVOICED_STATUSES:
                task.write({'custom_milestone_id': False})
                touched |= milestone
                task.message_post(body=_(
                    "Detached from payment milestone '%(milestone)s': %(reason)s.",
                    milestone=milestone.display_name, reason=reason),
                    subtype_xmlid='mail.mt_note')
                if milestone.status not in AMC_OPEN_STATUSES:
                    milestone.message_post(body=_(
                        "Task '%(task)s' was detached (%(reason)s) after the milestone "
                        "was %(status)s; approved hours are now %(hours)s. Re-send the "
                        "task list to the customer if it was already shared.",
                        task=task.display_name, reason=reason,
                        status=milestone._amc_status_label(),
                        hours=amc_fmt_hours(milestone.amc_hours)))
            else:
                body = _(
                    "Task '%(task)s' stays attached to payment milestone "
                    "'%(milestone)s' although %(reason)s: the milestone is already "
                    "%(status)s. Review the billing manually if needed.",
                    task=task.display_name, milestone=milestone.display_name,
                    reason=reason, status=milestone._amc_status_label())
                task.message_post(body=body, subtype_xmlid='mail.mt_note')
                milestone.message_post(body=body)
        touched._amc_refresh_report(_("task detached"))

    def _ft_amc_clear_deployed(self, reason, state='1_done'):
        """Clear the deployment (sudo); write() then detaches the milestone.

        ``state`` is the Status the tasks still in Deployed fall back to
        (Done on undo, In Progress on reopen); ``None`` leaves the Status to
        the caller (a user's own Status write is about to set it)."""
        self.write({'ft_deployed': False, 'ft_deployed_date': False, 'ft_deployed_by_id': False})
        if state:
            still_deployed = self.filtered(lambda t: t.state == FT_DEPLOYED_STATE)
            if still_deployed:
                still_deployed.write({'state': state})
        for task in self:
            task.message_post(body=_("Billable status cleared: %s.", reason),
                              subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # actions (bulk-capable)
    # ------------------------------------------------------------------
    @api.model
    def _ft_amc_notification(self, message, kind='success'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Billable Status"),
                'message': message,
                'type': kind,
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_ft_mark_deployed(self):
        tasks = self.exists()
        if not tasks:
            raise UserError(_("Select at least one task."))
        tasks._ft_amc_check_deploy_rules('deploy')
        # env.uid stays the real user under sudo(): the actor is stamped. The
        # Status goes to Deployed in the same write (no stage change, so the
        # task stays in its Completed stage and date_end is untouched).
        tasks.sudo().write({
            'ft_deployed': True,
            'ft_deployed_date': fields.Datetime.now(),
            'ft_deployed_by_id': self.env.uid,
            'state': FT_DEPLOYED_STATE,
        })
        actor = self.env.user.name or ''
        for task in tasks.sudo():
            task.message_post(body=_("Marked Billable by %s.", actor), subtype_xmlid='mail.mt_note')
        return self._ft_amc_notification(_("%s task(s) marked Billable.", len(tasks)))

    def action_ft_reset_deployed(self):
        tasks = self.exists()
        if not tasks:
            raise UserError(_("Select at least one task."))
        tasks._ft_amc_check_deploy_rules('undo')
        actor = self.env.user.name or ''
        tasks.sudo()._ft_amc_clear_deployed(_("undone by %s", actor))
        return self._ft_amc_notification(_("Billable Status undone on %s task(s).", len(tasks)), 'warning')
