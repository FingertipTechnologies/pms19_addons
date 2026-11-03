# -*- coding: utf-8 -*-
"""AMC monthly payment milestones on project.custom.milestone.

One milestone per (AMC project, calendar month), created by
project.project._amc_ensure_monthly_milestone() - never by hand. It is named
"Support Services for <Month YYYY>" (code SS-YYYY-MM) and carries the
AMC-approved, Deployed tasks of that month (project.task.custom_milestone_id,
the link project_date_extension already provides) and the sum of their
APPROVED timesheet hours (ft_pms_planning_workflow's weekly timesheet
approval): a task is billed in the month it was marked Deployed, however many
months it was worked on (requirement 49), but only the hours a PM / TL has
approved count.

Status sequence, enforced here in write() for AMC monthly milestones only -
every other milestone keeps today's free editing:

    not_started -> completed -> customer_approved ("Client Approved")
                -> invoice_raised -> partially_paid ("Part Paid") -> paid

"completed" means "the month's task list has been sent to the customer":
entering it (a) regenerates the milestone's task Excel (one row per deployed
task with its approved and billable hours) and attaches it to the milestone,
then (b) e-mails the month through ft_amc_monthly_timesheet's report, with
that Excel added to the mail, when the milestone's own send switch
(amc_send_email) is on. A failure to send raises, so the status change is
rolled back and the milestone cannot read Completed while nothing was sent.
The day-7 cron (_cron_ft_amc_send_monthly_milestones) completes the Not
Started milestones of the months that are over the same way.
"""
import io
import logging
from datetime import datetime

import xlsxwriter
from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command

from odoo.addons.ft_amc_monthly_timesheet.models.monthly_report import MANAGER_GROUPS, XLSX_MIMETYPE
from odoo.addons.ft_amc_monthly_timesheet.models.periods import month_start

_logger = logging.getLogger(__name__)

AMC_STATUS_SEQUENCE = (
    'not_started',
    'completed',
    'customer_approved',
    'invoice_raised',
    'partially_paid',
    'paid',
)
# Statuses from which a task may still be detached (nothing has been sent to
# the customer yet). From "completed" on, the customer has seen the list, so
# a task that is reset / reopened stays attached and a note is posted instead.
AMC_OPEN_STATUSES = ('not_started',)
# Transitions reserved to the AMC report managers (ft_amc_monthly_timesheet's
# MANAGER_GROUPS) and the project's Project Manager.
AMC_MANAGER_TARGETS = ('completed',)
PARAM_SEND_DAY = 'ft_amc_payment_milestone.send_day'
DEFAULT_SEND_DAY = 7
# Context key the day-7 cron writes under. write() itself behaves the same
# (a send failure raises either way); the cron catches the error in its own
# savepoint and posts it on the chatter. The key marks those writes for any
# later override that needs to tell a cron completion from a manual one.
CRON_CONTEXT_KEY = 'ft_amc_milestone_cron'
# Column order of the task Excel (_amc_task_excel_rows / _amc_build_task_excel).
AMC_EXCEL_COLUMNS = ('task', 'deployed_on', 'billable_hours')
# Statuses after which the month is invoiced: nothing may change any more.
AMC_INVOICED_STATUSES = ('invoice_raised', 'partially_paid', 'paid')


def amc_fmt_hours(hours):
    """Float hours as HH:MM (the one hours format of the AMC documents)."""
    total = int(round((hours or 0.0) * 60))
    return '%02d:%02d' % divmod(total, 60)


class ProjectCustomMilestone(models.Model):
    _inherit = 'project.custom.milestone'

    # The whole selection is re-stated (same keys as project_custom_milestone,
    # plus customer_approved) because selection_add cannot relabel a value:
    # "Partially Paid" becomes "Part Paid" and customer_approved reads "Client
    # Approved". Given as a method rather than a list: a list that differs
    # from the base one makes the ORM log an "overrides existing selection"
    # warning at every registry load; a method is the supported way to take
    # the selection over. Every pre-existing key is kept, so modules that
    # test the status by key (project_date_extension's _DONE_STATUSES,
    # ft_ai_sales_insights' billing tiles) keep working. internal_approved
    # (19.0.1.0.0) is gone: the pre-migration of 19.0.1.1.0 resets it.
    status = fields.Selection(selection='_amc_status_selection', default='not_started')

    @api.model
    def _amc_status_selection(self):
        return [
            ('not_started', _('Not Started')),
            ('completed', _('Completed')),
            ('customer_approved', _('Client Approved')),
            ('invoice_raised', _('Invoice Raised')),
            ('partially_paid', _('Part Paid')),
            ('paid', _('Paid')),
        ]

    is_amc_monthly = fields.Boolean(
        string='AMC Monthly Milestone', readonly=True, copy=False, index=True,
        help="Created automatically for an AMC project and a calendar month. "
             "Its status follows the AMC billing sequence and it carries the "
             "Billable tasks of that month.")
    amc_period_start = fields.Date(string='Billing Period Start', readonly=True, copy=False, index=True)
    amc_period_end = fields.Date(string='Billing Period End', readonly=True, copy=False)
    amc_period_label = fields.Char(string='Billing Period', compute='_compute_amc_period_label')
    amc_send_email = fields.Boolean(
        string='Send e-mail to customer', copy=False,
        help="When the milestone is marked Completed, e-mail the monthly AMC "
             "timesheet (PDF + Excel) and the milestone's task Excel to the "
             "customer. Taken from the project's 'Send monthly AMC timesheet' "
             "switch when the milestone is created; change it per month here.")
    amc_task_ids = fields.One2many(
        'project.task', 'custom_milestone_id', string='AMC Tasks',
        help="AMC-approved tasks marked Billable in this billing period.")
    amc_task_count = fields.Integer(string='Tasks', compute='_compute_amc_task_count')
    amc_billing_task_ids = fields.Many2many(
        'project.task', compute='_compute_amc_billing_task_ids', string='Billing Tasks',
        help="Attached tasks with billable or approved hours: the ones listed "
             "in the customer's task Excel.")
    # compute_sudo: the sum is shown on the project form and the central list
    # to users who may not read every timesheet line.
    amc_hours = fields.Float(
        string='Approved Hours', compute='_compute_amc_hours', store=True, compute_sudo=True,
        help="Sum of the APPROVED timesheet hours (weekly timesheet approval) "
             "of every task attached to this milestone - whatever month they "
             "were logged in: a task is billed in the month it was marked billable. "
             "Pending and rejected timesheets do not count.")
    # The pre-existing manual field. For AMC monthly milestones it mirrors
    # amc_hours so the Milestones tab and the central list (which already show
    # Hours Spent) need no second column; other milestones keep their manual
    # value: an editable stored compute (readonly=False) keeps what the user
    # typed, and the compute hands the old value back for them. Reading a
    # field inside its own compute is supported by the ORM (see
    # Field.compute_value: the field is un-flagged before the method runs so
    # the read fetches the stored value instead of recursing).
    hours_spent = fields.Float(compute='_compute_hours_spent', store=True, readonly=False)
    amc_report_id = fields.Many2one(
        'ft.amc.monthly.report', string='Timesheet Report', readonly=True, copy=False,
        ondelete='set null',
        help="The monthly AMC timesheet report e-mailed when this milestone was completed.")
    amc_sent_on = fields.Datetime(string='E-mail Sent On', readonly=True, copy=False)
    # The generated task Excel. Holding it in a Many2one (rather than flagging
    # ir.attachment or matching on the file name) tells the generated file
    # apart from anything a user drops into Attachments by hand, survives a
    # rename of the milestone and lets a regeneration delete exactly the
    # previous generated file - and it adds nothing to the core
    # ir.attachment table.
    amc_task_excel_id = fields.Many2one(
        'ir.attachment', string='Task Excel', readonly=True, copy=False, ondelete='set null',
        help="Excel of the billable tasks of this month (task, stage, billable "
             "on, approved by, approved hours, billable hours). Regenerated "
             "when the milestone is marked Completed or with 'Generate Task "
             "Excel'; also attached to the customer e-mail.")
    amc_can_manage = fields.Boolean(
        string='Can Complete', compute='_compute_amc_can_manage',
        help="Technical: the current user may complete this AMC milestone / "
             "generate its task Excel (AMC report manager or the project's PM).")

    _amc_project_period_unique = models.Constraint(
        'UNIQUE(project_id, amc_period_start)',
        'An AMC monthly milestone already exists for this project and month.',
    )

    _DONE_STATUSES = ("completed", "customer_approved", "invoice_raised", "partially_paid", "paid")

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('amc_period_start')
    def _compute_amc_period_label(self):
        for milestone in self:
            milestone.amc_period_label = self._amc_period_label(milestone.amc_period_start)

    @api.depends('amc_task_ids', 'amc_task_ids.ft_billable_hours',
                 'amc_task_ids.timesheet_ids.unit_amount',
                 'amc_task_ids.timesheet_ids.ft_approval_state')
    def _compute_amc_billing_task_ids(self):
        for milestone in self:
            milestone.amc_billing_task_ids = milestone.amc_task_ids.filtered(
                lambda t: t._ft_amc_is_billing())

    @api.depends('amc_task_ids')
    def _compute_amc_task_count(self):
        for milestone in self:
            milestone.amc_task_count = len(milestone.amc_task_ids)

    @api.depends('amc_task_ids', 'amc_task_ids.timesheet_ids.unit_amount',
                 'amc_task_ids.timesheet_ids.employee_id',
                 'amc_task_ids.timesheet_ids.ft_approval_state')
    def _compute_amc_hours(self):
        for milestone in self:
            # Whole-task rule: no date filter. Approved lines only (weekly
            # timesheet approval), employee set like the report's
            # _collect_lines so non-timesheet analytic lines never count.
            milestone.amc_hours = sum(
                task._ft_amc_approved_hours() for task in milestone.amc_task_ids)

    @api.depends('amc_hours', 'is_amc_monthly')
    def _compute_hours_spent(self):
        for milestone in self:
            if milestone.is_amc_monthly:
                milestone.hours_spent = milestone.amc_hours
            else:
                # Keep the manual value (old stored value, or 0.0 on a new record).
                milestone.hours_spent = milestone.hours_spent

    @api.depends('project_id.user_id')
    @api.depends_context('uid')
    def _compute_amc_can_manage(self):
        is_manager = self._amc_user_is_manager()
        for milestone in self:
            milestone.amc_can_manage = bool(
                is_manager or milestone.sudo().project_id.user_id == self.env.user)

    # ------------------------------------------------------------------
    # constraints
    # ------------------------------------------------------------------
    @api.constrains('is_amc_monthly', 'amc_period_start', 'amc_period_end')
    def _check_amc_period(self):
        for milestone in self.filtered('is_amc_monthly'):
            start, end = milestone.amc_period_start, milestone.amc_period_end
            if not start or not end or start.day != 1 or end < start:
                raise ValidationError(_(
                    "An AMC monthly milestone needs a billing period that starts on "
                    "the first day of a month (milestone '%s').", milestone.name))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _amc_period_label(self, period_start):
        """'September 2026' for the month starting ``period_start``."""
        return period_start.strftime('%B %Y') if period_start else ''

    @api.model
    def _amc_milestone_name(self, period_start):
        """'Support Services for September 2026'."""
        return _("Support Services for %s", self._amc_period_label(period_start))

    @api.model
    def _amc_milestone_code(self, period_start):
        """'SS-2026-09' in the Milestone ID column."""
        return 'SS-%s' % period_start.strftime('%Y-%m')

    @api.model
    def _amc_send_day(self):
        """Day of the month from which the previous month's milestone e-mail
        goes out (settings, default 7). Clamped to 1..28 so it exists in
        every month."""
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_SEND_DAY)
        try:
            day = int(raw) if raw else DEFAULT_SEND_DAY
        except (TypeError, ValueError):
            day = DEFAULT_SEND_DAY
        return min(max(day, 1), 28)

    @api.model
    def _amc_user_is_manager(self):
        """ft_amc_monthly_timesheet's report managers (AMC Reporting Manager,
        Administrator, Project Manager group)."""
        if self.env.su:
            return True
        user = self.env.user
        return any(user.has_group(group) for group in MANAGER_GROUPS)

    def _amc_check_manager(self):
        """Mark Completed / Generate Task Excel: report managers or the
        project's own Project Manager (the people who send the AMC report)."""
        if self.env.su or self._amc_user_is_manager():
            return
        for milestone in self:
            if milestone.sudo().project_id.user_id != self.env.user:
                raise AccessError(_(
                    "Only an AMC Reporting Manager, a Project Manager or the Project "
                    "Manager of project '%s' can complete an AMC monthly milestone "
                    "or generate its task Excel.", milestone.sudo().project_id.display_name))

    def _amc_check_status_change(self, new_status):
        """AMC monthly milestones move one step at a time along
        AMC_STATUS_SEQUENCE (Paid may also follow Invoice Raised directly: a
        fully paid invoice has no Part Paid step), or back to Not Started.
        Superuser (crons, migrations, tests building fixtures) is exempt."""
        self.ensure_one()
        current = self.status or 'not_started'
        if new_status == current or new_status == 'not_started':
            return
        if new_status == 'paid' and current == 'invoice_raised':
            return
        try:
            expected = AMC_STATUS_SEQUENCE[AMC_STATUS_SEQUENCE.index(current) + 1]
        except (ValueError, IndexError):
            expected = None
        if new_status != expected:
            labels = dict(self._fields['status']._description_selection(self.env))
            raise UserError(_(
                "AMC milestone '%(name)s' is %(current)s: the next status is "
                "%(next)s (or Not Started to restart). %(target)s is not allowed here.",
                name=self.display_name, current=labels.get(current, current),
                next=labels.get(expected, _("none")), target=labels.get(new_status, new_status)))

    def copy(self, default=None):
        if any(m.is_amc_monthly for m in self):
            raise UserError(_(
                "AMC monthly milestones cannot be duplicated: there is exactly "
                "one per project and month, created automatically."))
        return super().copy(default=default)

    def _amc_status_label(self, status=None):
        labels = dict(self._fields['status']._description_selection(self.env))
        return labels.get(status or self.status, status or self.status)

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    def write(self, vals):
        if 'status' in vals and not self.env.su:
            new_status = vals['status']
            for milestone in self.filtered('is_amc_monthly'):
                milestone._amc_check_status_change(new_status)
                if new_status in AMC_MANAGER_TARGETS and new_status != milestone.status:
                    milestone._amc_check_manager()
        before = {m.id: m.status for m in self} if 'status' in vals else {}
        res = super().write(vals)
        if vals.get('status') == 'completed':
            # Completed = sent. Only milestones that were not already
            # completed send (a no-op write must not mail twice).
            just_completed = self.filtered(
                lambda m: m.is_amc_monthly and before.get(m.id) != 'completed')
            for milestone in just_completed:
                milestone._amc_on_completed()
        return res

    # ------------------------------------------------------------------
    # Kick-off sync (project_date_extension) - AMC monthly milestones excluded
    # ------------------------------------------------------------------
    def _sync_project_kickoff(self, projects):
        """Same as project_date_extension's, minus the AMC monthly milestones.

        The base method mirrors the LATEST milestone due date onto the
        project's Kick-off Date. A monthly AMC milestone is due on the last
        day of its month and a new one appears every month, so including them
        would drag every AMC project's Kick-off Date forward month after
        month. Re-stated here (rather than wrapped) because the base method
        searches the milestones itself; the only change is the extra domain
        leaf.
        """
        Project = self.env["project.project"]
        field = self._KICKOFF_FIELD
        if field not in Project._fields:
            return
        Milestone = self.env["project.custom.milestone"].sudo()
        for project in projects:
            if not project:
                continue
            dated = Milestone.search([
                ("project_id", "=", project.id),
                ("due_date", "!=", False),
                ("is_amc_monthly", "=", False),
            ])
            if not dated:
                continue
            latest = max(dated.mapped("due_date"))
            if project[field] != latest:
                project.sudo().with_context(
                    skip_date_sequence_check=True
                ).write({field: latest})

    # ------------------------------------------------------------------
    # task Excel
    # ------------------------------------------------------------------
    def _amc_excel_tasks(self):
        """The milestone's tasks, archived ones included (an archived task
        that was deployed and approved was still delivered)."""
        self.ensure_one()
        return self.env['project.task'].sudo().with_context(active_test=False).search(
            [('custom_milestone_id', '=', self.id)], order='ft_deployed_date, id')

    def _amc_task_excel_rows(self):
        """One dict per deployed task, in AMC_EXCEL_COLUMNS order, plus the
        values the header block shows. Separate from the rendering so the
        figures can be checked without parsing the workbook.

        Requirement 48: only billing tasks (billable or approved hours) are
        listed; a task attached with 0 hours is left out of the workbook sent
        to the customer (it stays on the milestone for the internal list)."""
        self.ensure_one()
        rows = []
        for task in self._amc_excel_tasks():
            if not task._ft_amc_is_billing():
                continue
            approved_hours = task._ft_amc_approved_hours()
            rows.append({
                'task': task.name or '',
                'stage': task.stage_id.name or '',
                'deployed_on': task._ft_amc_deployment_day() if task.ft_deployed_date else False,
                'approved_by': task.pwf_amc_approved_by_id.name or '',
                'approved_hours': approved_hours,
                'billable_hours': task.ft_billable_hours or 0.0,
            })
        return rows

    def _amc_task_excel_name(self):
        self.ensure_one()
        return _("%s - Tasks.xlsx", self.name)

    def _amc_render_task_excel(self):
        """xlsx bytes: a header block (project, customer, period, status) and
        the task table with a total row. xlsxwriter, like the monthly
        report's own Excel (ft_amc_monthly_timesheet); hours are Excel
        durations formatted [h]:mm like that report (one hours format)."""
        self.ensure_one()
        project = self.sudo().project_id
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {
            'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
        border = {'border': 1, 'border_color': '#9AA5B8'}
        title_fmt = workbook.add_format({'bold': True, 'font_size': 16})
        label_fmt = workbook.add_format({'bold': True, 'valign': 'top'})
        value_fmt = workbook.add_format({'valign': 'top', 'align': 'left'})
        header_fmt = workbook.add_format(dict(
            border, bold=True, bg_color='#D9E1F2', valign='top', text_wrap=True))
        header_num_fmt = workbook.add_format(dict(
            border, bold=True, bg_color='#D9E1F2', valign='top', align='right'))
        text_fmt = workbook.add_format(dict(border, text_wrap=True, valign='top'))
        date_fmt = workbook.add_format(dict(
            border, num_format='dd/mm/yyyy', valign='top', align='left'))
        hours_fmt = workbook.add_format(dict(border, num_format='[h]:mm', valign='top'))
        total_label_fmt = workbook.add_format(dict(
            border, bold=True, bg_color='#D9E1F2', align='right', valign='top'))
        total_fmt = workbook.add_format(dict(
            border, bold=True, bg_color='#D9E1F2', num_format='[h]:mm', valign='top'))
        last_col = len(AMC_EXCEL_COLUMNS) - 1

        sheet = workbook.add_worksheet(_('Tasks'))
        for col, width in enumerate((60, 16, 16)):
            sheet.set_column(col, col, width)
        sheet.set_landscape()
        sheet.set_paper(9)  # A4
        sheet.fit_to_pages(1, 0)

        row = 0
        sheet.merge_range(row, 0, row, last_col, self.name or '', title_fmt)
        sheet.set_row(row, 24)
        row += 2
        info_rows = [
            (_('Project'), project.name or ''),
            (_('Customer'), project.partner_id.display_name or ''),
            (_('Billing period'), '%s (%s - %s)' % (
                self.amc_period_label,
                self.amc_period_start.strftime('%d/%m/%Y') if self.amc_period_start else '',
                self.amc_period_end.strftime('%d/%m/%Y') if self.amc_period_end else '')),
            (_('Milestone status'), self._amc_status_label()),
        ]
        for label, value in info_rows:
            sheet.write(row, 0, label, label_fmt)
            sheet.merge_range(row, 1, row, last_col, value or '-', value_fmt)
            row += 1
        row += 1

        rows = self._amc_task_excel_rows()
        sheet.write_row(row, 0, [_('Task'), _('Date')], header_fmt)
        sheet.write(row, 2, _('Billable Hours'), header_num_fmt)
        sheet.freeze_panes(row + 1, 0)
        sheet.repeat_rows(row)
        if not rows:
            row += 1
            sheet.merge_range(row, 0, row, last_col,
                              _('No approved, billable task in this billing period.'), text_fmt)
        for data in rows:
            row += 1
            sheet.write(row, 0, data['task'], text_fmt)
            if data['deployed_on']:
                sheet.write_datetime(
                    row, 1, datetime.combine(data['deployed_on'], datetime.min.time()), date_fmt)
            else:
                sheet.write_blank(row, 1, None, date_fmt)
            sheet.write_number(row, 2, data['billable_hours'] / 24.0, hours_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 1, _('Total'), total_label_fmt)
        sheet.write_number(row, 2, sum(r['billable_hours'] for r in rows) / 24.0, total_fmt)
        workbook.close()
        return output.getvalue()

    def _amc_build_task_excel(self):
        """(Re)generate the task Excel, attach it to the milestone (Attachments
        group / Milestones tab) and drop the previously generated one. Sudo:
        the callers (completion, cron, the manager button) were already
        checked. Returns the attachment."""
        self.ensure_one()
        milestone = self.sudo()
        old = milestone.amc_task_excel_id
        attachment = self.env['ir.attachment'].sudo().create({
            'name': milestone._amc_task_excel_name(),
            'type': 'binary',
            'raw': milestone._amc_render_task_excel(),
            'mimetype': XLSX_MIMETYPE,
            'res_model': self._name,
            'res_id': self.id,
        })
        milestone.write({
            'amc_task_excel_id': attachment.id,
            'attachment_ids': [Command.link(attachment.id)],
        })
        if old:
            old.unlink()  # the relation rows go with it
        return attachment

    def action_amc_generate_task_excel(self):
        non_amc = self.filtered(lambda m: not m.is_amc_monthly)
        if non_amc:
            raise UserError(_("The task Excel is generated for AMC monthly milestones only."))
        self._amc_check_manager()
        for milestone in self:
            attachment = milestone._amc_build_task_excel()
            milestone.message_post(body=_(
                "Task Excel '%(file)s' generated (%(tasks)s task(s), %(hours)s approved hours).",
                file=attachment.name, tasks=len(milestone.amc_billing_task_ids),
                hours=amc_fmt_hours(milestone.amc_hours)))
        return True

    # ------------------------------------------------------------------
    # e-mail (requirements 43 / 44)
    # ------------------------------------------------------------------
    def _amc_on_completed(self):
        self.ensure_one()
        # The task list of the month is frozen in the Excel first, e-mail or
        # not: it is what the milestone carries from now on.
        self._amc_build_task_excel()
        if not self.amc_send_email:
            self.message_post(body=_(
                "Marked Completed. 'Send e-mail to customer' is off on this "
                "milestone, so no e-mail was sent (task Excel attached)."))
            return False
        return self._amc_send_customer_email()

    def _amc_refresh_report(self, reason):
        """Keep the month's timesheet report (ft_amc_monthly_timesheet) in step
        with the milestone: its task lines, totals, PDF and Excel are rebuilt
        from the milestone's current billing tasks. Called when a task is
        attached / detached and when the milestone is completed again. A
        report never generated (draft, no lines, no files) is left alone; an
        e-mail already sent is not sent again - the note says so."""
        Report = self.env['ft.amc.monthly.report'].sudo()
        for milestone in self.filtered('is_amc_monthly'):
            milestone = milestone.sudo()
            report = milestone.amc_report_id or Report.search([
                ('project_id', '=', milestone.project_id.id),
                ('period_start', '=', milestone.amc_period_start)], limit=1)
            if not report or (report.state == 'draft' and not report.line_ids
                              and not report.pdf_attachment_id):
                continue
            has_lines = report._collect_lines()
            errors = report._build_attachments()
            if report.state == 'no_data' and has_lines:
                report.write({'state': 'draft', 'error_message': False})
            elif report.state in ('draft', 'failed') and not has_lines:
                report.write({'state': 'no_data', 'error_message': False})
            if not milestone.amc_report_id:
                milestone.write({'amc_report_id': report.id})
            body = _(
                "Timesheet report '%(report)s' refreshed (%(reason)s): %(tasks)s task(s), "
                "%(hours)s hours.",
                report=report.display_name, reason=reason, tasks=report.task_count,
                hours=amc_fmt_hours(report.total_hours))
            if report.state in ('queued', 'sent'):
                body += _(" The e-mail already sent to the customer is unchanged.")
            if errors:
                body += ' ' + ' | '.join(errors)
            milestone.message_post(body=body)

    def _amc_send_customer_email(self):
        """E-mail the month's timesheet (ft_amc_monthly_timesheet report) for
        this milestone's tasks, with the milestone's task Excel added to the
        mail (see models/monthly_report.py). Raises UserError when it cannot
        be sent (customer without e-mail, contract not covering the month,
        PDF failure...), so a manual status change is refused and rolled back.

        The report is the existing ft.amc.monthly.report of (project, month):
        with a milestone present its task selection and hours come from the
        milestone (see models/monthly_report.py). A report already queued /
        sent for that month (someone pressed Send Now on it) is not sent
        again; the milestone just records it.
        """
        self.ensure_one()
        project = self.sudo().project_id
        company = project.company_id or self.env.company
        Report = self.env['ft.amc.monthly.report'].sudo().with_company(company)
        report = Report._get_or_create(project, self.amc_period_start)
        now = fields.Datetime.now()
        if report.state in ('queued', 'sent'):
            self.sudo().write({'amc_report_id': report.id,
                               'amc_sent_on': report.sent_on or now})
            self.message_post(body=_(
                "Marked Completed. The timesheet e-mail of %s had already been sent "
                "(report %s); it was not sent again.",
                self.amc_period_label, report.display_name))
            # The report shows the milestone's current tasks all the same.
            self._amc_refresh_report(_("milestone completed again"))
            return report
        error = report._process(send=True)
        if error:
            raise UserError(_(
                "The AMC timesheet e-mail of %(period)s could not be prepared: "
                "%(error)s", period=self.amc_period_label, error=error))
        if report.state == 'no_data':
            # A month with no deployed task: nothing to list, nothing to mail.
            # The milestone still completes (requirement 37: it exists for
            # every month) and says so.
            self.sudo().write({'amc_report_id': report.id})
            self.message_post(body=_(
                "Marked Completed. No approved, billable task is attached for %s, "
                "so there was no timesheet to e-mail.", self.amc_period_label))
            return report
        self.sudo().write({'amc_report_id': report.id, 'amc_sent_on': now})
        self.message_post(body=_(
            "Timesheet e-mail of %(period)s queued to %(to)s (%(tasks)s task(s), "
            "%(hours)s hours, task Excel attached).",
            period=self.amc_period_label, to=report.recipient_emails or '',
            tasks=report.task_count, hours=amc_fmt_hours(report.total_hours)))
        return report

    # ------------------------------------------------------------------
    # buttons
    # ------------------------------------------------------------------
    def _amc_set_status(self, target):
        non_amc = self.filtered(lambda m: not m.is_amc_monthly)
        if non_amc:
            raise UserError(_(
                "These buttons drive AMC monthly milestones only. Other milestones "
                "are edited directly through their Status field."))
        # Written as the real user: write() enforces the sequence and the
        # manager right for Mark Completed.
        self.write({'status': target})
        return True

    def action_amc_mark_completed(self):
        return self._amc_set_status('completed')

    def action_amc_customer_approved(self):
        return self._amc_set_status('customer_approved')

    def action_amc_invoice_raised(self):
        return self._amc_set_status('invoice_raised')

    def action_amc_partially_paid(self):
        return self._amc_set_status('partially_paid')

    def action_amc_paid(self):
        return self._amc_set_status('paid')

    def action_amc_reset_not_started(self):
        self._amc_check_manager()
        invoiced = self.filtered(lambda m: m.status in AMC_INVOICED_STATUSES)
        if invoiced:
            raise UserError(_(
                "%s cannot be reset: the invoice has been raised for this month "
                "(Invoice Raised / Part Paid / Paid). Its content is final.",
                ', '.join(invoiced.mapped('display_name'))))
        return self._amc_set_status('not_started')

    def action_amc_open_report(self):
        self.ensure_one()
        if not self.amc_report_id:
            raise UserError(_("No timesheet report has been sent for this milestone yet."))
        self.env['ft.amc.monthly.report']._check_manager()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'ft.amc.monthly.report',
            'res_id': self.amc_report_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # cron: send on the 7th (configurable) for the previous month(s)
    # ------------------------------------------------------------------
    @api.model
    def _cron_ft_amc_send_monthly_milestones(self):
        """Daily. From the send day of the month (settings, default 7), every
        AMC monthly milestone whose period is over and that is still Not
        Started with its send switch on is marked Completed, which builds the
        task Excel and e-mails the month. A failure is posted on the chatter
        and the status stays Not Started (Completed always means "sent").
        Milestones with the send switch off are left alone (manual flow)."""
        Milestone = self.sudo()
        Report = self.env['ft.amc.monthly.report'].sudo()
        send_day = self._amc_send_day()
        candidates = Milestone.search([
            ('is_amc_monthly', '=', True),
            ('status', '=', 'not_started'),
            ('amc_send_email', '=', True),
            ('project_id.active', '=', True),
        ], order='amc_period_start, id')
        for milestone in candidates:
            company = milestone.project_id.company_id or self.env.company
            today = Report._local_today(company)
            if today.day < send_day:
                continue
            if not milestone.amc_period_end or milestone.amc_period_end >= month_start(today):
                continue  # the month is not over yet
            try:
                with self.env.cr.savepoint():
                    milestone.with_context(**{CRON_CONTEXT_KEY: True}).write(
                        {'status': 'completed'})
            except Exception as exc:  # noqa: BLE001 - one milestone must not block the others
                _logger.warning("AMC milestone %s (%s): automatic sending failed: %s",
                                milestone.id, milestone.display_name, exc)
                milestone.message_post(body=Markup('%s<br/>%s') % (
                    _("Automatic sending of the month's e-mail failed; the "
                      "milestone stays Not Started. Fix the problem and use "
                      "'Mark Completed & Send'."),
                    _("Error: %s", str(exc) or exc.__class__.__name__)))
