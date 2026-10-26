# -*- coding: utf-8 -*-
"""Weekly timesheet approval (all project types: AMC, Implementation, General).

Every timesheet line (account.analytic.line with a project) carries an
approval state - Pending / Approved / Rejected - and the Monday-to-Sunday week
it belongs to, so a reviewer can work through one week at a time.

Who may review a line: superuser, an Administrator (base.group_system), a
"global" approver (Project Manager / Team Lead job position, see
project.task._pwf_amc_is_global_approver) or the Project Manager of the
line's project (project_id.user_id). Nobody but an Administrator may approve
or reject their own lines.

The approval fields are only ever written through the action_ft_timesheet_*
methods (validated as the real user, then written via sudo so the project
lock guard and the other content guards do not block an approval-only write).
Changing the content of a reviewed line (date, hours, description, task,
project, employee) puts it back to Pending.
"""
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

from odoo.addons.ft_sprint_management.models.week_utils import monday_of, week_label

FT_TS_APPROVAL_STATES = [
    ('pending', 'Pending'),
    ('approved', 'Approved'),
    ('rejected', 'Rejected'),
]
# Written only by the approval actions (or under superuser).
_FT_TS_APPROVAL_FIELDS = frozenset((
    'ft_approval_state', 'ft_approved_by_id', 'ft_approved_on', 'ft_rejection_reason',
))
# A change to any of these on a reviewed line sends it back to Pending.
_FT_TS_CONTENT_FIELDS = ('date', 'unit_amount', 'name', 'task_id', 'project_id', 'employee_id')
_FT_TS_CTX = 'ft_timesheet_approval_action'
_FT_TS_LIST_LIMIT = 10


def _ft_ts_lines_text(lines):
    """Bullet list naming up to 10 timesheet lines, plus a count of the rest."""
    rows = ['- %s %s, %s (%s h)' % (
        line.date or '', line.employee_id.name or '',
        line.project_id.display_name or '', round(line.unit_amount or 0.0, 2))
        for line in lines[:_FT_TS_LIST_LIMIT]]
    if len(lines) > _FT_TS_LIST_LIMIT:
        rows.append(_('... and %s more', len(lines) - _FT_TS_LIST_LIMIT))
    return '\n'.join(rows)


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    ft_approval_state = fields.Selection(
        FT_TS_APPROVAL_STATES, string='Approval Status', default='pending',
        required=True, index=True, copy=False,
        help="Weekly review of the timesheet by the Project Manager / Team Lead.")
    ft_approved_by_id = fields.Many2one(
        'res.users', string='Reviewed By', readonly=True, copy=False)
    ft_approved_on = fields.Datetime(string='Reviewed On', readonly=True, copy=False)
    ft_rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    ft_week_start = fields.Date(
        string='Week (Mon–Sun)', compute='_compute_ft_week', store=True, index=True,
        help="Monday of the Monday-to-Sunday week the timesheet date falls in.")
    ft_week_label = fields.Char(
        string='Week', compute='_compute_ft_week', store=True,
        help="Monday-to-Sunday week of the timesheet, e.g. 'W43 · 19 Oct – 25 Oct 2026'.")

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('date')
    def _compute_ft_week(self):
        for line in self:
            if not line.date:
                line.ft_week_start = False
                line.ft_week_label = False
                continue
            # date - weekday(): Saturday and Sunday map to the same Monday.
            monday = monday_of(line.date)
            sunday = monday + timedelta(days=6)
            line.ft_week_start = monday
            line.ft_week_label = '%s · %s – %s' % (
                week_label(monday), monday.strftime('%d %b'), sunday.strftime('%d %b %Y'))

    # ------------------------------------------------------------------
    # rules
    # ------------------------------------------------------------------
    def _ft_check_timesheet_approval_rights(self):
        """Raise unless the current user may review every line of ``self``.

        All lines are validated before anything is written, so a bulk call is
        all-or-nothing. A reviewer may review their own lines: a Project
        Manager logs time on their own project and approves it like any other.
        """
        if self.env.su or not self:
            return
        lines = self.sudo()
        no_project = lines.filtered(lambda l: not l.project_id)
        if no_project:
            raise UserError(_(
                "Only timesheets (lines with a project) can be approved.\n\n"
                "Without a project:\n%s", _ft_ts_lines_text(no_project)))
        user = self.env.user
        if not self.env['project.task']._pwf_amc_is_global_approver():
            foreign = lines.filtered(lambda l: l.project_id.user_id != user)
            if foreign:
                raise AccessError(_(
                    "Only the Project Manager of the project, a Project Manager / "
                    "Project Coordinator, a Team Lead or an Administrator can "
                    "review timesheets.\n\nNot allowed:\n%s", _ft_ts_lines_text(foreign)))

    def _ft_lines_with_content_change(self, vals):
        """Reviewed lines of ``self`` whose content ``vals`` really changes."""
        reviewed = self.filtered(lambda l: l.ft_approval_state in ('approved', 'rejected'))
        if not reviewed:
            return reviewed
        changed = self.browse()
        for line in reviewed:
            for fname in _FT_TS_CONTENT_FIELDS:
                if fname not in vals:
                    continue
                new = vals[fname]
                if fname == 'date':
                    differs = fields.Date.to_date(new) != line.date
                elif fname == 'unit_amount':
                    differs = float_compare(new or 0.0, line.unit_amount or 0.0,
                                            precision_digits=4) != 0
                elif fname == 'name':
                    differs = (new or '') != (line.name or '')
                else:  # many2one
                    differs = (new or False) != (line[fname].id or False)
                if differs:
                    changed |= line
                    break
        return changed

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                for fname in _FT_TS_APPROVAL_FIELDS:
                    vals.pop(fname, None)
                vals['ft_approval_state'] = 'pending'
        return super().create(vals_list)

    def write(self, vals):
        approval_keys = _FT_TS_APPROVAL_FIELDS.intersection(vals)
        # Only superuser may write these: the actions validate the real user
        # and then write via sudo. The context key they set is NOT honoured
        # here on its own - a client can put anything in an RPC context.
        if approval_keys and not self.env.su:
            raise AccessError(_(
                "The timesheet approval can only be changed with the Approve / "
                "Reject / Reset to Pending buttons."))
        to_reset = self.browse()
        if not approval_keys and any(f in vals for f in _FT_TS_CONTENT_FIELDS):
            to_reset = self._ft_lines_with_content_change(vals)
        res = super().write(vals)
        if to_reset:
            to_reset.sudo().with_context(**{_FT_TS_CTX: True}).write({
                'ft_approval_state': 'pending',
                'ft_approved_by_id': False,
                'ft_approved_on': False,
                'ft_rejection_reason': False,
            })
        return res

    # ------------------------------------------------------------------
    # actions (bulk-capable: list header buttons act on the selection)
    # ------------------------------------------------------------------
    def _ft_timesheet_apply_approval(self, state, reason=False):
        lines = self.exists()
        if not lines:
            raise UserError(_("Select at least one timesheet."))
        # Validated as the real user, for every line, before anything is written.
        lines._ft_check_timesheet_approval_rights()
        if state == 'pending':
            vals = {'ft_approval_state': 'pending', 'ft_approved_by_id': False,
                    'ft_approved_on': False, 'ft_rejection_reason': False}
        else:
            vals = {
                'ft_approval_state': state,
                # env.uid stays the real user; the write itself goes via sudo.
                'ft_approved_by_id': self.env.uid,
                'ft_approved_on': fields.Datetime.now(),
                'ft_rejection_reason': reason if state == 'rejected' else False,
            }
        lines.sudo().with_context(**{_FT_TS_CTX: True}).write(vals)
        return lines

    @api.model
    def _ft_timesheet_notification(self, message, notif_type='success', close=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Timesheet Approval"),
                'message': message,
                'type': notif_type,
                'sticky': False,
                'next': ({'type': 'ir.actions.act_window_close'} if close
                         else {'type': 'ir.actions.client', 'tag': 'soft_reload'}),
            },
        }

    def action_ft_timesheet_approve(self):
        lines = self._ft_timesheet_apply_approval('approved')
        return self._ft_timesheet_notification(_(
            "%(count)s timesheet line(s) approved (%(hours)s h).",
            count=len(lines), hours=round(sum(lines.sudo().mapped('unit_amount')), 2)))

    def action_ft_timesheet_reset(self):
        lines = self._ft_timesheet_apply_approval('pending')
        return self._ft_timesheet_notification(_(
            "%s timesheet line(s) reset to Pending.", len(lines)))

    def action_ft_timesheet_reject(self):
        lines = self.exists()
        if not lines:
            raise UserError(_("Select at least one timesheet."))
        # Refuse now rather than after the reason has been typed.
        lines._ft_check_timesheet_approval_rights()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Timesheet(s)"),
            'res_model': 'ft.timesheet.reject.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_line_ids': [(6, 0, lines.ids)]},
        }


class FtTimesheetRejectWizard(models.TransientModel):
    _name = 'ft.timesheet.reject.wizard'
    _description = 'Reject Timesheets'

    line_ids = fields.Many2many('account.analytic.line', string='Timesheets')
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("A rejection reason is required."))
        lines = self.line_ids._ft_timesheet_apply_approval('rejected', reason)
        return self.env['account.analytic.line']._ft_timesheet_notification(
            _("%s timesheet line(s) rejected.", len(lines)), notif_type='warning', close=True)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    ft_approved_hours = fields.Float(
        string='Approved Hours', compute='_compute_ft_timesheet_approval_hours',
        store=True, compute_sudo=True,
        help="Timesheet hours of this task approved in the weekly review.")
    ft_rejected_hours = fields.Float(
        string='Rejected Hours', compute='_compute_ft_timesheet_approval_hours',
        store=True, compute_sudo=True,
        help="Timesheet hours of this task rejected in the weekly review.")
    ft_pending_hours = fields.Float(
        string='Pending Approval Hours', compute='_compute_ft_timesheet_approval_hours',
        store=True, compute_sudo=True,
        help="Timesheet hours of this task not yet reviewed in the weekly review.")

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.ft_approval_state')
    def _compute_ft_timesheet_approval_hours(self):
        for task in self:
            totals = {'approved': 0.0, 'rejected': 0.0, 'pending': 0.0}
            # Each line of the task itself counted once (sub-tasks keep their own).
            for line in task.timesheet_ids:
                totals[line.ft_approval_state or 'pending'] += line.unit_amount or 0.0
            task.ft_approved_hours = totals['approved']
            task.ft_rejected_hours = totals['rejected']
            task.ft_pending_hours = totals['pending']
