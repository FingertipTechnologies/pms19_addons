"""Monthly AMC timesheet report.

One record per (AMC project, month). It collects the timesheets dated in the
month of the tasks that are completed and approved (project.task.pwf_amc_approval,
from ft_pms_planning_workflow) when it runs, freezes them as report lines,
renders a PDF (pure Python ReportLab, see pdf_report.py - no wkhtmltopdf) and an
Excel file and emails both to the customer through the
``mail_template_amc_monthly_timesheet`` template. The daily cron sends the
previous month on/after the 5th.
"""
import base64
import io
import logging
import re
from datetime import datetime

import pytz
import xlsxwriter
from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tools import email_normalize

from .pdf_report import (
    _company_address_lines, render_monthly_report_pdf, report_total_minutes, task_summary_rows,
)
from .periods import month_end, previous_month

_logger = logging.getLogger(__name__)

DEFAULT_TZ = 'Asia/Kolkata'
SEND_FROM_DAY = 5
MANAGER_GROUPS = (
    'ft_amc_monthly_timesheet.group_amc_manager',
    'base.group_system',
    'project.group_project_manager',
)
XLSX_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


class AmcMonthlyReport(models.Model):
    _name = 'ft.amc.monthly.report'
    _description = 'AMC Monthly Timesheet Report'
    _inherit = ['mail.thread']
    _order = 'period_start desc, project_id, id desc'

    _project_period_unique = models.Constraint(
        'UNIQUE(project_id, period_start)',
        'A monthly AMC report already exists for this project and month.',
    )

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company)
    project_id = fields.Many2one(
        'project.project', required=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one(
        related='project_id.partner_id', store=True, string='Customer')
    period_start = fields.Date(required=True, index=True)
    period_end = fields.Date(required=True)
    period_label = fields.Char(compute='_compute_period_label', string='Period')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('no_data', 'No Data'),
        ('failed', 'Failed'),
    ], default='draft', required=True, index=True, tracking=True, copy=False)
    line_ids = fields.One2many(
        'ft.amc.monthly.report.line', 'report_id', string='Timesheet Lines')
    task_ids = fields.Many2many(
        'project.task', 'ft_amc_report_task_rel', 'report_id', 'task_id',
        string='Approved Tasks')
    task_count = fields.Integer(compute='_compute_task_count', string='Tasks')
    total_hours = fields.Float(string='Total Hours')
    recipient_emails = fields.Char(string='To')
    cc_emails = fields.Char(string='CC')
    email_from = fields.Char(string='From')
    pdf_attachment_id = fields.Many2one(
        'ir.attachment', string='PDF', ondelete='set null', copy=False)
    xlsx_attachment_id = fields.Many2one(
        'ir.attachment', string='Excel', ondelete='set null', copy=False)
    mail_id = fields.Many2one('mail.mail', string='Email', ondelete='set null', copy=False)
    sent_on = fields.Datetime(copy=False)
    error_message = fields.Text(copy=False)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('period_start')
    def _compute_period_label(self):
        for report in self:
            report.period_label = report.period_start.strftime('%B %Y') if report.period_start else ''

    @api.depends('task_ids')
    def _compute_task_count(self):
        for report in self:
            report.task_count = len(report.task_ids)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _check_manager(self):
        if self.env.su:
            return
        user = self.env.user
        if not any(user.has_group(group) for group in MANAGER_GROUPS):
            raise AccessError(_("Only AMC Reporting Managers can manage monthly AMC reports."))

    @api.model
    def _company_tz(self, company):
        return company.partner_id.tz or DEFAULT_TZ

    @api.model
    def _local_today(self, company):
        return datetime.now(pytz.timezone(self._company_tz(company))).date()

    @api.model
    def _get_or_create(self, project, period_start):
        """The report of ``project`` for the month starting ``period_start``."""
        domain = [('project_id', '=', project.id), ('period_start', '=', period_start)]
        report = self.search(domain, limit=1)
        if report:
            return report
        try:
            with self.env.cr.savepoint():
                return self.create({
                    'name': _('AMC Timesheet - %(period)s - %(project)s',
                              period=period_start.strftime('%B %Y'), project=project.name),
                    'company_id': (project.company_id or self.env.company).id,
                    'project_id': project.id,
                    'period_start': period_start,
                    'period_end': month_end(period_start),
                })
        except IntegrityError:
            # Created concurrently (another cron worker / user click).
            return self.search(domain, limit=1)

    def _check_contract(self):
        """Raise unless the project is an active AMC contract covering the month."""
        self.ensure_one()
        project = self.project_id
        if not project.active or project.ft_project_type != 'amc':
            raise UserError(_("Project '%s' is not an active AMC project.", project.display_name))
        if not project.amc_report_enabled:
            raise UserError(_(
                "Monthly AMC timesheet reporting is disabled on project '%s'.",
                project.display_name))
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

    def _get_recipients(self):
        """(to, cc) as comma separated normalized emails."""
        self.ensure_one()
        project = self.project_id.sudo()
        customer_email = email_normalize(project.partner_id.email or '')
        if not customer_email:
            raise UserError(_(
                "The customer of project '%s' has no valid email address.",
                project.display_name))
        to_emails = [customer_email]
        candidates = [partner.email for partner in project.amc_recipient_ids]
        candidates.append(project.poc_email)
        for raw in candidates:
            email = email_normalize(raw or '')
            if email and email not in to_emails:
                to_emails.append(email)
        cc_emails = []
        manager_email = email_normalize(project.user_id.partner_id.email or '')
        if manager_email and manager_email not in to_emails:
            cc_emails.append(manager_email)
        return ','.join(to_emails), ','.join(cc_emails)

    def _find_tasks(self):
        """Tasks completed and approved (PM/TL) at the time the report runs."""
        self.ensure_one()
        Task = self.env['project.task'].sudo().with_context(active_test=False)
        return Task.search([
            ('project_id', '=', self.project_id.id),
            ('pwf_amc_approval', '=', 'approved'),
            ('stage_id', 'in', Task._ft_final_stage_ids()),
        ])

    def _collect_lines(self):
        """Snapshot the month's timesheets of the approved tasks. True if any.

        Only entries dated within the period are taken, so each entry belongs to
        exactly one monthly report.
        """
        self.ensure_one()
        timesheets = self.env['account.analytic.line'].sudo().search([
            ('task_id', 'in', self._find_tasks().ids),
            ('project_id', '=', self.project_id.id),
            ('employee_id', '!=', False),
            ('date', '>=', self.period_start),
            ('date', '<=', self.period_end),
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

    def _file_stem(self):
        self.ensure_one()
        project_name = re.sub(r'[^A-Za-z0-9]+', '_', self.project_id.name or '').strip('_')
        return 'AMC_Timesheet_%s_%s' % (project_name or self.project_id.id,
                                        self.period_start.strftime('%Y-%m'))

    def _render_pdf(self):
        """PDF bytes, rendered in pure Python with ReportLab (no wkhtmltopdf)."""
        self.ensure_one()
        return render_monthly_report_pdf(self)

    def _render_xlsx(self):
        """Excel copy of the PDF: one sheet with the same header, info block,
        task table (Date, Task, Hours - same order as the PDF) and total hours.

        Hours are Excel durations (days = minutes / 1440, format ``[h]:mm``)
        with the same balanced minutes as the PDF, so they show as HH:MM and
        still add up; the total is written as a value, like the PDF."""
        self.ensure_one()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {
            'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
        border = {'border': 1, 'border_color': '#9AA5B8'}
        title_fmt = workbook.add_format({'bold': True, 'font_size': 16})
        company_fmt = workbook.add_format({'bold': True, 'font_size': 11})
        address_fmt = workbook.add_format({'font_size': 8, 'font_color': '#555555'})
        label_fmt = workbook.add_format({'bold': True, 'valign': 'top'})
        value_fmt = workbook.add_format({'valign': 'top', 'align': 'left'})
        section_fmt = workbook.add_format({'bold': True, 'font_size': 11})
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
        total_minutes = report_total_minutes(self)
        last_col = 2

        sheet = workbook.add_worksheet(_('Timesheet'))
        for col, width in enumerate((17, 70, 12)):  # Date, Task, Hours
            sheet.set_column(col, col, width)
        sheet.set_landscape()
        sheet.set_paper(9)  # A4, like the PDF
        sheet.fit_to_pages(1, 0)
        sheet.set_margins(left=0.6, right=0.6, top=0.7, bottom=0.7)

        # Header: same title and company block as the PDF
        row = 0
        sheet.merge_range(row, 0, row, last_col,
                          '%s - %s' % (_('AMC Timesheet'), self.period_label or ''), title_fmt)
        sheet.set_row(row, 24)
        company = self.company_id
        if company.name:
            row += 1
            sheet.merge_range(row, 0, row, last_col, company.name, company_fmt)
        address = ', '.join(_company_address_lines(company))
        if address:
            row += 1
            sheet.merge_range(row, 0, row, last_col, address, address_fmt)

        # Info block, same rows as the PDF
        row += 2
        info_rows = [
            (_('Customer'), self.partner_id.display_name or ''),
            (_('Project'), self.project_id.name or ''),
            (_('Reporting month'), self.period_label or ''),
            (_('Period'), '%s - %s' % (self.period_start.strftime('%d/%m/%Y'),
                                       self.period_end.strftime('%d/%m/%Y'))),
        ]
        for label, value in info_rows:
            sheet.write(row, 0, label, label_fmt)
            sheet.merge_range(row, 1, row, last_col, value or '-', value_fmt)
            row += 1
        sheet.write(row, 0, _('Total hours'), label_fmt)
        sheet.write_number(row, 1, total_minutes / 1440.0, workbook.add_format(
            {'num_format': '[h]:mm', 'align': 'left', 'valign': 'top'}))
        row += 2

        lines = list(self.line_ids)
        if not lines:
            sheet.merge_range(row, 0, row, last_col, _('No approved tasks for this period.'),
                              value_fmt)
            workbook.close()
            return output.getvalue()

        # Tasks: same columns, headers and row order as the PDF
        sheet.write(row, 0, _('Tasks'), section_fmt)
        row += 1
        sheet.write_row(row, 0, [_('Date'), _('Task')], header_fmt)
        sheet.write(row, 2, _('Hours'), header_num_fmt)
        sheet.freeze_panes(row + 1, 0)
        sheet.repeat_rows(row)
        for task_row in task_summary_rows(self):
            row += 1
            if task_row['approved_on']:
                sheet.write_datetime(
                    row, 0, datetime.combine(task_row['approved_on'], datetime.min.time()),
                    date_fmt)
            else:
                sheet.write_blank(row, 0, None, date_fmt)
            sheet.write(row, 1, task_row['name'], text_fmt)
            sheet.write_number(row, 2, task_row['minutes'] / 1440.0, hours_fmt)
        row += 1
        sheet.merge_range(row, 0, row, 1, _('Total hours'), total_label_fmt)
        sheet.write_number(row, 2, total_minutes / 1440.0, total_fmt)

        workbook.close()
        return output.getvalue()

    def _build_attachments(self):
        """(Re)generate the PDF and Excel attachments of the report.

        Each file is built independently: a failure of one does not prevent the
        other from being generated and attached for download. Returns the list
        of error messages (empty when both files were produced).
        """
        self.ensure_one()
        stem = self._file_stem()
        Attachment = self.env['ir.attachment']
        files = (
            ('pdf_attachment_id', '.pdf', 'application/pdf', self._render_pdf, _("PDF")),
            ('xlsx_attachment_id', '.xlsx', XLSX_MIMETYPE, self._render_xlsx, _("Excel")),
        )
        values, errors = {}, []
        old = Attachment
        for field_name, extension, mimetype, render, label in files:
            old |= self[field_name]
            try:
                # Own savepoint: a database error while rendering must not
                # abort the transaction (and with it the other file).
                with self.env.cr.savepoint():
                    attachment = Attachment.create({
                        'name': stem + extension,
                        'type': 'binary',
                        'raw': render(),
                        'mimetype': mimetype,
                        'res_model': self._name,
                        'res_id': self.id,
                    })
                values[field_name] = attachment.id
            except Exception as exc:  # noqa: BLE001 - keep the other file
                _logger.exception(
                    "AMC monthly report %s (project %s, %s): %s generation failed",
                    self.id, self.project_id.display_name, self.period_label, label)
                # A stale file of a previous run must not look current.
                values[field_name] = False
                errors.append(_("%(file)s generation failed: %(error)s",
                                file=label, error=str(exc) or exc.__class__.__name__))
        self.write(values)
        (old - self.pdf_attachment_id - self.xlsx_attachment_id).unlink()
        return errors

    def _send_email(self, to_emails, cc_emails):
        self.ensure_one()
        template = self.env.ref('ft_amc_monthly_timesheet.mail_template_amc_monthly_timesheet')
        email_from = self.company_id._amc_report_email_from()
        # A previous failed attempt must not be retried from the mail queue as well.
        old_mail = self.mail_id.sudo()
        if old_mail and old_mail.state == 'exception':
            old_mail.cancel()
        self.write({
            'recipient_emails': to_emails,
            'cc_emails': cc_emails,
            'email_from': email_from,
        })
        attachments = self.pdf_attachment_id | self.xlsx_attachment_id
        # sudo: managers may lack access to mail.template; access was checked by
        # the caller. Queued (no force_send): a rollback discards the email.
        mail_id = template.sudo().send_mail(self.id, force_send=False, email_values={
            'email_to': to_emails,
            'email_cc': cc_emails or False,
            'email_from': email_from,
            'reply_to': email_from,
            'recipient_ids': [],
            'attachment_ids': [Command.set(attachments.ids)],
            # Kept so its delivery status can be synchronized on the report.
            'auto_delete': False,
        })
        self.write({
            'mail_id': mail_id,
            'state': 'queued',
            'sent_on': False,
            'error_message': False,
        })
        self.message_post(body=_(
            "Monthly timesheet queued for %(to)s (%(tasks)s tasks, %(hours).2f hours).",
            to=to_emails, tasks=self.task_count, hours=self.total_hours))

    def _process(self, send=True):
        """Collect, render and (with ``send``) email the report.

        Returns False on success (or no data), else the error message. When the
        PDF or the Excel file could not be generated, the report is set to
        *failed* (keeping the file that was produced, for download) and no email
        is sent. Nothing is raised in that case, so the failed state persists
        even inside the caller's savepoint / transaction.
        """
        self.ensure_one()
        self._check_contract()
        if send:
            to_emails, cc_emails = self._get_recipients()
        if not self._collect_lines():
            self.write({'state': 'no_data', 'error_message': False})
            return False
        errors = self._build_attachments()
        if errors:
            message = '\n'.join(errors)
            self.write({'state': 'failed', 'error_message': message})
            return message
        if send:
            self._send_email(to_emails, cc_emails)
        else:
            self.write({'state': 'draft', 'error_message': False})
        return False

    def _sync_mail_state(self):
        """Update queued reports from the state of their outgoing email."""
        for report in self.filtered(lambda r: r.state == 'queued'):
            mail = report.mail_id.sudo()
            if not mail:
                # Deleted after sending (auto_delete): delivered.
                report.write({'state': 'sent', 'sent_on': report.sent_on or fields.Datetime.now()})
            elif mail.state in ('sent', 'received'):
                report.write({'state': 'sent', 'sent_on': mail.write_date, 'error_message': False})
            elif mail.state == 'exception':
                report.write({
                    'state': 'failed',
                    'error_message': mail.failure_reason or _("The email could not be sent."),
                })
            elif mail.state == 'cancel':
                report.write({
                    'state': 'failed',
                    'error_message': _("The email was cancelled before being sent."),
                })

    def _check_state(self, allowed, action_name):
        for report in self:
            if report.state not in allowed:
                raise UserError(_(
                    "%(action)s is not possible on report '%(report)s' in state %(state)s.",
                    action=action_name, report=report.name,
                    state=dict(self._fields['state']._description_selection(self.env))[report.state]))

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def _failure_notification(self, failures):
        """Client action reporting generation failures to the user.

        Used instead of raising a UserError, which would roll back the
        transaction: the failed state, its message and the file that could be
        produced (e.g. the Excel file when only the PDF failed) are kept.
        """
        message = ' | '.join(
            '%s: %s' % (report.name, error.replace('\n', '; ')) for report, error in failures)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Report generation failed"),
                'message': message,
                'type': 'danger',
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def action_generate(self):
        """Build lines and attachments for preview, without emailing."""
        self._check_manager()
        self._check_state(('draft', 'failed', 'no_data'), _("Generate / Refresh"))
        failures = []
        for report in self:
            error = report._process(send=False)
            if error:
                failures.append((report, error))
        return self._failure_notification(failures) if failures else True

    def action_send(self):
        self._check_manager()
        self._check_state(('draft', 'failed', 'no_data'), _("Send Now"))
        failures = []
        for report in self:
            if report.period_end >= self._local_today(report.company_id):
                raise UserError(_(
                    "%s is not over yet: only completed months can be sent.",
                    report.period_label))
            error = report._process(send=True)
            if error:
                failures.append((report, error))
        return self._failure_notification(failures) if failures else True

    def action_refresh_status(self):
        self._check_manager()
        self._sync_mail_state()
        return True

    def action_reset_to_draft(self):
        self._check_manager()
        self._check_state(('failed', 'no_data'), _("Reset to Draft"))
        self.write({'state': 'draft', 'error_message': False})
        return True

    def _download(self, attachment):
        self.ensure_one()
        if not attachment:
            raise UserError(_("Generate the report first."))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }

    def action_download_pdf(self):
        return self._download(self.pdf_attachment_id)

    def action_download_xlsx(self):
        return self._download(self.xlsx_attachment_id)

    # ------------------------------------------------------------------
    # cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_monthly_reports(self):
        """Daily: on/after the 5th, email the previous month of every AMC project."""
        Report = self.sudo()
        Report.search([('state', '=', 'queued')])._sync_mail_state()
        Project = self.env['project.project'].sudo()
        default_company = self.env.ref('base.main_company', raise_if_not_found=False)
        for company in self.env['res.company'].sudo().search([]):
            today = Report._local_today(company)
            if today.day < SEND_FROM_DAY:
                continue
            period_start, period_end = previous_month(today)
            start_month = company._amc_report_start_month()
            if start_month and period_start < start_month:
                continue
            company_domain = [('company_id', '=', company.id)]
            if company == default_company:
                # Projects without a company are reported by the main company.
                company_domain = ['|', ('company_id', '=', company.id), ('company_id', '=', False)]
            projects = Project.search([
                ('active', '=', True),
                ('ft_project_type', '=', 'amc'),
                ('amc_report_enabled', '=', True),
            ] + company_domain, order='id')
            for project in projects:
                if not project.date_start:
                    _logger.warning(
                        "AMC project %s (%s) has no contract start date: monthly report skipped.",
                        project.id, project.name)
                    continue
                if project.date_start > period_end or (project.date and project.date < period_start):
                    continue
                report = Report.with_company(company)._get_or_create(project, period_start)
                # no_data is re-checked daily: tasks approved after the 5th
                # still get their month's entries sent (nothing is emailed
                # while there is no data).
                if report.state in ('queued', 'sent'):
                    continue
                try:
                    # A PDF / Excel failure is not raised: _process() sets the
                    # report to failed itself (kept by the savepoint) and
                    # returns the message, so the produced file is not lost.
                    with self.env.cr.savepoint():
                        report._process(send=True)
                except UserError as exc:
                    # Configuration problem (e.g. customer without email): no traceback.
                    _logger.warning("AMC monthly report %s (%s) failed: %s",
                                    report.id, report.name, exc)
                    report.write({'state': 'failed', 'error_message': str(exc)})
                except Exception as exc:  # noqa: BLE001 - one project must not block the others
                    _logger.exception("AMC monthly report %s (%s) failed", report.id, report.name)
                    report.write({'state': 'failed', 'error_message': str(exc)})


class AmcMonthlyReportLine(models.Model):
    _name = 'ft.amc.monthly.report.line'
    _description = 'AMC Monthly Timesheet Report Line'
    _order = 'task_name, date, id'

    report_id = fields.Many2one(
        'ft.amc.monthly.report', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='report_id.company_id', store=True, index=True)
    task_id = fields.Many2one('project.task', string='Task', ondelete='set null')
    timesheet_id = fields.Many2one(
        'account.analytic.line', string='Timesheet', ondelete='set null', index=True)
    date = fields.Date()
    employee_name = fields.Char(string='Employee')
    task_name = fields.Char(string='Task Name')
    task_stage = fields.Char(string='Stage')
    approved_by = fields.Char(string='Approved By')
    approved_on = fields.Datetime(string='Approved On')
    description = fields.Text()
    hours = fields.Float()
