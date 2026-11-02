# -*- coding: utf-8 -*-
"""ft.amc.monthly.report driven by the AMC monthly milestone.

When a (project, month) has an AMC monthly milestone, the report of that
month lists the MILESTONE's tasks (approved, completed, deployed in that
month) with their APPROVED timesheet hours (weekly timesheet approval),
whatever their dates - the whole-task rule of requirement 49 - instead of
"every approved completed task, entries dated in the month", so the PDF /
Excel totals equal the milestone's Approved Hours. Months without a
milestone (history before this module, projects that are not eligible) keep
the original behaviour, so nothing already sent changes.

The milestone's own task Excel (project_custom_milestone._amc_build_task_excel)
rides along: _build_attachments makes sure it exists, _send_email adds it
to the outgoing mail next to the report's PDF and Excel, which stay as
they are.

The day-5 cron of ft_amc_monthly_timesheet no longer mails such months:
sending is driven by the milestone status (Completed) and its own send
switch, on the 7th (see project_custom_milestone._cron_ft_amc_send_monthly_milestones).
"""
import logging

from odoo import _, api, models
from odoo.exceptions import UserError
from odoo.fields import Command

_logger = logging.getLogger(__name__)

# Context key the day-5 cron runs under; _process() uses it to leave
# milestone-driven months alone.
REPORT_CRON_CONTEXT_KEY = 'ft_amc_report_cron'


class AmcMonthlyReport(models.Model):
    _inherit = 'ft.amc.monthly.report'

    def _amc_monthly_milestone(self):
        """The AMC monthly milestone of this report's (project, month), if any."""
        self.ensure_one()
        return self.env['project.custom.milestone'].sudo().search([
            ('project_id', '=', self.project_id.id),
            ('is_amc_monthly', '=', True),
            ('amc_period_start', '=', self.period_start),
        ], limit=1)

    def _amc_milestone_tasks(self, milestone):
        """The milestone's billing tasks (requirement 48: the same list as the
        milestone's Tasks tab and task Excel), archived ones included (an
        archived task that was deployed and approved was still delivered)."""
        tasks = self.env['project.task'].sudo().with_context(active_test=False).search(
            [('custom_milestone_id', '=', milestone.id)], order='id')
        return tasks.filtered(lambda t: t._ft_amc_is_billing())

    def _check_contract(self):
        """With a milestone, the milestone's own send switch replaces the
        project's 'Send monthly AMC timesheet' (requirement 44): on -> the
        e-mail may go even if the project switch is off; off -> refused.
        The other checks (active AMC project, contract dates covering the
        month) are the base ones, re-stated because the base method tests
        the project switch in the middle of them."""
        self.ensure_one()
        milestone = self._amc_monthly_milestone()
        if not milestone:
            return super()._check_contract()
        project = self.project_id
        if not project.active or project.ft_project_type != 'amc':
            raise UserError(_("Project '%s' is not an active AMC project.", project.display_name))
        if not milestone.amc_send_email:
            raise UserError(_(
                "'Send e-mail to customer' is off on milestone '%s'.", milestone.display_name))
        if not project.date_start:
            raise UserError(_(
                "Project '%s' has no start date: set the AMC contract start (and end) "
                "dates on the project.", project.display_name))
        if project.date_start > self.period_end or (
                project.date and project.date < self.period_start):
            raise UserError(_(
                "The AMC contract of project '%(project)s' (%(start)s - %(end)s) does not "
                "cover %(period)s.",
                project=project.display_name, start=project.date_start,
                end=project.date or _('open'), period=self.period_label))

    def _find_tasks(self):
        self.ensure_one()
        milestone = self._amc_monthly_milestone()
        if not milestone:
            return super()._find_tasks()
        return self._amc_milestone_tasks(milestone)

    def _collect_lines(self):
        """Milestone months: the APPROVED timesheets (employee set) of the
        milestone's tasks regardless of their date - the lines the
        milestone's Approved Hours are made of. Same snapshot lines as the
        base."""
        self.ensure_one()
        milestone = self._amc_monthly_milestone()
        if not milestone:
            return super()._collect_lines()
        tasks = self._amc_milestone_tasks(milestone)
        timesheets = self.env['account.analytic.line'].sudo().search([
            ('task_id', 'in', tasks.ids),
            ('employee_id', '!=', False),
            ('ft_approval_state', '=', 'approved'),
        ], order='task_id, date, id')
        self.line_ids.unlink()
        self.env['ft.amc.monthly.report.line'].create([{
            'report_id': self.id,
            'task_id': line.task_id.id,
            'timesheet_id': line.id,
            'date': line.date,
            'employee_name': line.employee_id.name,
            'task_name': line.task_id.name,
            'task_stage': line.task_id.stage_id.name,
            'approved_by': line.task_id.pwf_amc_approved_by_id.name,
            'approved_on': line.task_id.pwf_amc_approved_on,
            'description': line.name if line.name and line.name != '/' else False,
            'hours': line.unit_amount,
        } for line in timesheets])
        self.write({
            'task_ids': [Command.set(timesheets.task_id.ids)],
            'total_hours': sum(timesheets.mapped('unit_amount')),
        })
        return bool(timesheets)

    def _build_attachments(self):
        """The report's own PDF / Excel as before, plus: a month with a
        milestone always has the milestone's task Excel ready to ride along
        (built here when missing - e.g. "Send Now" pressed on the report
        before the milestone was ever completed). Completion rebuilds it
        just before, so it is not rebuilt twice."""
        errors = super()._build_attachments()
        milestone = self._amc_monthly_milestone()
        if milestone and not milestone.amc_task_excel_id:
            try:
                with self.env.cr.savepoint():
                    milestone._amc_build_task_excel()
            except Exception as exc:  # noqa: BLE001 - same contract as the report files
                _logger.exception("AMC monthly report %s: milestone task Excel generation failed",
                                  self.id)
                errors.append(_("Milestone task Excel generation failed: %s",
                                str(exc) or exc.__class__.__name__))
        return errors

    def _send_email(self, to_emails, cc_emails):
        """Queue the mail as the base does, then replace the report's own
        Excel by the milestone's task Excel: the customer gets the PDF and
        ONE Excel (the report Excel stays downloadable on the report)."""
        res = super()._send_email(to_emails, cc_emails)
        milestone = self._amc_monthly_milestone()
        excel = milestone.amc_task_excel_id if milestone else False
        if excel and self.mail_id:
            commands = [Command.link(excel.id)]
            if self.xlsx_attachment_id:
                commands.append(Command.unlink(self.xlsx_attachment_id.id))
            self.mail_id.sudo().write({'attachment_ids': commands})
        return res

    def _process(self, send=True):
        """The day-5 cron skips months that have a milestone: their e-mail is
        sent when the milestone is completed (manually or by the day-7
        cron). The report record the cron created stays in draft and is
        reused by the milestone."""
        self.ensure_one()
        if self.env.context.get(REPORT_CRON_CONTEXT_KEY) and self._amc_monthly_milestone():
            _logger.info("AMC monthly report %s (%s): skipped by the day-5 cron, the month "
                         "has an AMC milestone.", self.id, self.name)
            return False
        return super()._process(send=send)

    @api.model
    def _cron_send_monthly_reports(self):
        return super(AmcMonthlyReport, self.with_context(
            **{REPORT_CRON_CONTEXT_KEY: True}))._cron_send_monthly_reports()
