# -*- coding: utf-8 -*-
"""AMC monthly timesheet report: selection, cron, email.

Selection rule: tasks approved and in a completed stage when the report runs
(the approval date does not matter); only their timesheet entries dated within
the report month are included, so each entry belongs to exactly one month.

Fixtures are created as superuser (TransactionCase env is su), the same way the
ft_pms_planning_workflow approval tests do, so:
- the approval stamps (``pwf_amc_approved_on`` / ``pwf_amc_approved_by_id``),
  which are readonly for normal users, can be set deterministically;
- timesheets can be logged on tasks already sitting in the Completed stage
  (ft_task_hours_tracker's completed-task / task-required guards skip su).

PDF rendering (ReportLab, models/pdf_report.py) is patched to fake bytes. Time is frozen with freezegun
(Odoo wraps ``freezegun.freeze_time``). Company timezone is Asia/Kolkata.
"""
from datetime import date, datetime
from unittest.mock import patch

from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

FAKE_PDF = b'%PDF-fake'
REPORT_LOGGER = 'odoo.addons.ft_amc_monthly_timesheet.models.monthly_report'

OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)
# 6 Nov 2026 11:30 IST -> cron processes October 2026.
CRON_NOW = '2026-11-06 06:00:00'


@tagged('post_install', '-at_install')
class TestAmcMonthlyReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True,
                                       tracking_disable=True))
        cls.company = cls.env.company
        cls.company.partner_id.tz = 'Asia/Kolkata'
        cls.params = cls.env['ir.config_parameter'].sudo()
        cls.params.set_param('ft_amc_monthly_timesheet.email_from', 'Support Test <support@example.com>')
        cls.params.set_param('ft_amc_monthly_timesheet.start_month', False)

        cls.pm = new_test_user(
            cls.env, 'amc_report_pm', email='pm@example.com',
            groups='base.group_user,project.group_project_user')
        cls.approver = new_test_user(
            cls.env, 'amc_report_approver', email='approver@example.com',
            groups='base.group_user,project.group_project_user')

        Partner = cls.env['res.partner']
        cls.customer = Partner.create({'name': 'AMC Customer', 'email': 'customer@example.com'})
        cls.extra = Partner.create({'name': 'AMC Extra Contact', 'email': 'extra@example.com'})

        cls.employee = cls.env['hr.employee'].create({
            'name': 'AMC Report Employee', 'company_id': cls.company.id})

        cls.project = cls._make_project('AMC Report Contract', 'amc')
        cls.general = cls._make_project('AMC Report General Project', 'general')
        # Isolate the cron from AMC projects already in the database (rolled
        # back with the test transaction).
        cls.env['project.project'].with_context(active_test=False).search([
            ('ft_project_type', '=', 'amc'), ('id', '!=', cls.project.id),
        ]).write({'amc_report_enabled': False})

        Stage = cls.env['project.task.type']
        projects = cls.project | cls.general
        cls.working = Stage.create({
            'name': 'AMC Report Working', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})
        # Final by name (COMPLETED_STAGE_NAMES), not by fold.
        cls.completed = Stage.create({
            'name': 'Completed', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})

        cls.Report = cls.env['ft.amc.monthly.report']

    @classmethod
    def _make_project(cls, name, project_type, **vals):
        return cls.env['project.project'].create(dict({
            'name': name,
            'ft_project_type': project_type,
            'company_id': cls.company.id,
            'partner_id': cls.customer.id,
            'user_id': cls.pm.id,
            'allow_timesheets': True,
            'privacy_visibility': 'employees',
            'date_start': date(2026, 1, 1),
            'date': date(2027, 12, 31),
        }, **vals))

    def setUp(self):
        super().setUp()
        self.patch(type(self.Report), '_render_pdf', lambda self: FAKE_PDF)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _task(self, name='AMC report test task (approved)', project=None, stage=None,
              approval='approved', approved_on=datetime(2026, 10, 15, 6, 0), hours=(2.0, 1.5),
              dates=None):
        project = project or self.project
        vals = {
            'name': name,
            'project_id': project.id,
            'stage_id': (stage or self.completed).id,
            'task_type': 'internal_call',
            'estimated': 10.0,
            'date_deadline': datetime(2026, 10, 30, 12, 0),
        }
        if approval:
            vals.update({
                'pwf_amc_approval': approval,
                'pwf_amc_approved_on': approved_on,
                'pwf_amc_approved_by_id': self.approver.id,
            })
            if approval == 'rejected':
                vals['pwf_amc_rejection_reason'] = 'Not acceptable yet'
        task = self.env['project.task'].create(vals)
        dates = dates or [date(2026, 10, 10 + index) for index in range(len(hours))]
        for index, (amount, day) in enumerate(zip(hours, dates)):
            self._log(task, day, amount, 'AMC work %s on %s' % (index + 1, name))
        return task

    def _log(self, task, day, amount, name='AMC extra work'):
        return self.env['account.analytic.line'].create({
            'name': name,
            'project_id': task.project_id.id,
            'task_id': task.id,
            'employee_id': self.employee.id,
            'date': day,
            'unit_amount': amount,
        })

    def _report(self, period_start=OCT, project=None):
        return self.Report._get_or_create(project or self.project, period_start)

    def _project_reports(self, project=None):
        return self.Report.search([('project_id', '=', (project or self.project).id)])

    def _run_cron(self, when=CRON_NOW):
        # Muted: a failing project is logged with _logger.exception by design.
        with freeze_time(when), mute_logger(REPORT_LOGGER):
            self.Report._cron_send_monthly_reports()

    # ------------------------------------------------------------------
    # task selection
    # ------------------------------------------------------------------
    def test_approved_completed_task_included(self):
        task = self._task()
        report = self._report()
        self.assertEqual(report.period_start, OCT)
        self.assertEqual(report.period_end, date(2026, 10, 31))
        self.assertEqual(report._find_tasks(), task)
        self.assertTrue(report._collect_lines())
        self.assertEqual(report.task_ids, task)
        self.assertEqual(report.task_count, 1)
        self.assertEqual(len(report.line_ids), 2)
        self.assertAlmostEqual(report.total_hours, 3.5)
        self.assertEqual(set(report.line_ids.timesheet_id.ids),
                         set(task.timesheet_ids.ids))
        line = report.line_ids[0]
        self.assertEqual(line.task_id, task)
        self.assertEqual(line.task_name, task.name)
        self.assertEqual(line.employee_name, self.employee.name)
        self.assertEqual(line.approved_by, self.approver.name)
        self.assertTrue(line.approved_on)
        # Refresh does not duplicate snapshot lines.
        self.assertTrue(report._collect_lines())
        self.assertEqual(len(report.line_ids), 2)

    def test_unapproved_rejected_and_open_tasks_excluded(self):
        approved = self._task()
        self._task(name='AMC report test task (not approved)', approval=False)
        self._task(name='AMC report test task (rejected)', approval='rejected')
        self._task(name='AMC report test task (approved, open)', stage=self.working)
        report = self._report()
        self.assertEqual(report._find_tasks(), approved)
        report._collect_lines()
        self.assertEqual(report.task_ids, approved)
        self.assertAlmostEqual(report.total_hours, 3.5)

    def test_timesheet_outside_month_excluded(self):
        """Approved task: only its entries dated within the month are taken."""
        task = self._task(hours=(2.0, 1.5))
        sept = self._log(task, date(2026, 9, 30), 4.0, 'AMC work 30 Sep')
        nov = self._log(task, date(2026, 11, 1), 5.0, 'AMC work 1 Nov')
        first_day = self._log(task, date(2026, 10, 1), 0.5, 'AMC work 1 Oct')
        last_day = self._log(task, date(2026, 10, 31), 0.25, 'AMC work 31 Oct')
        report = self._report()
        self.assertTrue(report._collect_lines())
        self.assertEqual(report.task_ids, task)
        timesheets = report.line_ids.timesheet_id
        self.assertIn(first_day, timesheets)
        self.assertIn(last_day, timesheets)
        self.assertFalse(timesheets & (sept | nov))
        self.assertEqual(len(report.line_ids), 4)
        self.assertAlmostEqual(report.total_hours, 4.25)

    def test_approval_date_does_not_decide_month(self):
        """Approved after the month ended but before the report runs: its
        in-month entries are reported; approval long before also counts."""
        late = self._task(name='AMC report task approved in November',
                          approved_on=datetime(2026, 11, 3, 6, 0))
        early = self._task(name='AMC report task approved in September',
                           approved_on=datetime(2026, 9, 20, 6, 0), hours=(1.0,))
        report = self._report()
        self.assertEqual(report._find_tasks(), late | early)
        self.assertTrue(report._collect_lines())
        self.assertEqual(report.task_ids, late | early)
        self.assertAlmostEqual(report.total_hours, 4.5)
        # Same through the cron (6 Nov), after the late approval.
        report.unlink()
        self._run_cron()
        report = self._project_reports()
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.task_ids, late | early)
        self.assertAlmostEqual(report.total_hours, 4.5)

    def test_task_split_across_months(self):
        """A task with entries in two months: each report gets only its own."""
        task = self._task(hours=(2.0, 3.0), dates=[date(2026, 10, 20), date(2026, 11, 5)])
        oct_line, nov_line = task.timesheet_ids.sorted('date')
        october = self._report()
        november = self._report(NOV)
        self.assertTrue(october._collect_lines())
        self.assertTrue(november._collect_lines())
        self.assertEqual(october.task_ids, task)
        self.assertEqual(november.task_ids, task)
        self.assertEqual(october.line_ids.timesheet_id, oct_line)
        self.assertEqual(november.line_ids.timesheet_id, nov_line)
        self.assertAlmostEqual(october.total_hours, 2.0)
        self.assertAlmostEqual(november.total_hours, 3.0)
        # A sent October report does not block the task from November.
        october.state = 'sent'
        self.assertTrue(november._collect_lines())
        self.assertEqual(november.line_ids.timesheet_id, nov_line)

    def test_task_without_entries_in_month_not_listed(self):
        """Approved/completed task with entries only in another month is not
        in the report's task list."""
        in_month = self._task()
        self._task(name='AMC report task with September entries only',
                   dates=[date(2026, 9, 10), date(2026, 9, 11)])
        report = self._report()
        report._collect_lines()
        self.assertEqual(report.task_ids, in_month)
        self.assertEqual(report.task_count, 1)
        self.assertAlmostEqual(report.total_hours, 3.5)

    def test_unapproved_rejected_open_excluded_even_with_month_entries(self):
        """Entries in the month never qualify a task that is not approved and
        completed when the report runs."""
        self._task(name='AMC report task (not approved)', approval=False)
        self._task(name='AMC report task (rejected)', approval='rejected')
        self._task(name='AMC report task (approved, open)', stage=self.working)
        report = self._report()
        self.assertFalse(report._find_tasks())
        self.assertFalse(report._collect_lines())
        self.assertFalse(report.task_ids)
        self.assertFalse(report.line_ids)

    # ------------------------------------------------------------------
    # contract / project checks
    # ------------------------------------------------------------------
    def test_non_amc_project_ignored(self):
        self._task(name='AMC report task on General project', project=self.general)
        self._run_cron()
        self.assertFalse(self._project_reports(self.general))
        report = self._report(project=self.general)
        with self.assertRaises(UserError):
            report._check_contract()

    def test_contract_must_overlap_period(self):
        # Moving the Closed Date back before the other lifecycle dates trips
        # project_date_extension's step-order rule, which is not under test.
        self.project.with_context(skip_date_sequence_check=True).write(
            {'date': date(2026, 9, 30)})
        self._task()
        with self.assertRaises(UserError):
            self._report()._check_contract()

    def test_reporting_disabled(self):
        self.project.amc_report_enabled = False
        self._task()
        self._run_cron()
        self.assertFalse(self._project_reports())

    # ------------------------------------------------------------------
    # recipients
    # ------------------------------------------------------------------
    def test_recipients_partner_extra_and_poc(self):
        self.project.write({
            'amc_recipient_ids': [Command.set((self.extra | self.customer).ids)],
            'poc_email': 'poc@example.com',
        })
        to, cc = self._report()._get_recipients()
        self.assertIn('customer@example.com', to)
        self.assertIn('extra@example.com', to)
        self.assertIn('poc@example.com', to)
        self.assertEqual(to.count('customer@example.com'), 1, 'deduplicated')
        self.assertIn('pm@example.com', cc or '')

    def test_recipients_invalid_poc_ignored(self):
        self.project.poc_email = 'not-an-email'
        to, _cc = self._report()._get_recipients()
        self.assertIn('customer@example.com', to)
        self.assertNotIn('not-an-email', to)

    def test_recipients_customer_email_required(self):
        self.customer.email = False
        with self.assertRaises(UserError):
            self._report()._get_recipients()

    # ------------------------------------------------------------------
    # cron / scheduling
    # ------------------------------------------------------------------
    def test_before_fifth_no_send(self):
        self._task()
        # 4 Nov 15:30 IST.
        self._run_cron('2026-11-04 10:00:00')
        self.assertFalse(self._project_reports())

    def test_fifth_uses_company_timezone(self):
        self._task()
        # 4 Nov 19:00 UTC is already 5 Nov 00:30 in Asia/Kolkata.
        self._run_cron('2026-11-04 19:00:00')
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.period_start, OCT)

    def test_start_month_guard(self):
        self._task()
        self.params.set_param('ft_amc_monthly_timesheet.start_month', str(NOV))
        self._run_cron()
        self.assertFalse(self._project_reports())

    def test_no_data(self):
        self._task(approval=False)
        self._run_cron()
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.state, 'no_data')
        self.assertFalse(report.mail_id)

    def test_no_data_rechecked_after_late_approval(self):
        self._task(approval=False)
        self._run_cron()
        report = self._project_reports()
        self.assertEqual(report.state, 'no_data')
        # A task approved after the 5th is picked up by the next daily run.
        self._task()
        self._run_cron()
        self.assertEqual(report.state, 'queued')
        self.assertTrue(report.mail_id)

    def test_cron_queues_email_with_attachments(self):
        self.project.amc_recipient_ids = [Command.set(self.extra.ids)]
        task = self._task()
        self._run_cron()
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.period_start, OCT)
        self.assertEqual(report.task_ids, task)
        self.assertAlmostEqual(report.total_hours, 3.5)
        self.assertTrue(report.pdf_attachment_id)
        self.assertTrue(report.xlsx_attachment_id)
        self.assertTrue(report.pdf_attachment_id.name.endswith('_2026-10.pdf'))
        self.assertTrue(report.xlsx_attachment_id.name.endswith('_2026-10.xlsx'))
        self.assertTrue(report.pdf_attachment_id.name.startswith('AMC_Timesheet_'))
        mail = report.mail_id
        self.assertTrue(mail)
        self.assertIn('customer@example.com', mail.email_to)
        self.assertIn('extra@example.com', mail.email_to)
        self.assertIn('pm@example.com', mail.email_cc or '')
        self.assertIn('support@example.com', mail.email_from)
        self.assertEqual(set(mail.attachment_ids.ids),
                         {report.pdf_attachment_id.id, report.xlsx_attachment_id.id})
        self.assertIn('October 2026', mail.subject)
        self.assertIn(self.project.name, mail.subject)

    def test_cron_idempotent(self):
        self._task()
        self._run_cron()
        report = self._project_reports()
        mail = report.mail_id
        self.assertEqual(report.state, 'queued')
        self._run_cron('2026-11-07 06:00:00')
        self.assertEqual(self._project_reports(), report)
        self.assertEqual(report.mail_id, mail)
        self.assertEqual(self.env['mail.mail'].search_count([
            ('model', '=', 'ft.amc.monthly.report'), ('res_id', '=', report.id)]), 1)

    def test_failed_report_retried_next_run(self):
        self._task()
        with patch.object(type(self.Report), '_render_pdf',
                          side_effect=Exception('PDF renderer exploded')):
            self._run_cron()
        report = self._project_reports()
        self.assertEqual(report.state, 'failed')
        self.assertTrue(report.error_message)
        self.assertFalse(report.mail_id)
        self._run_cron('2026-11-07 06:00:00')
        self.assertEqual(report.state, 'queued')
        self.assertTrue(report.mail_id)

    def _mails(self, report):
        return self.env['mail.mail'].search([
            ('model', '=', 'ft.amc.monthly.report'), ('res_id', '=', report.id)])

    def test_cron_pdf_failure_keeps_excel_no_mail(self):
        self._task()
        with patch.object(type(self.Report), '_render_pdf',
                          side_effect=Exception('PDF renderer exploded')):
            self._run_cron()
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.state, 'failed')
        self.assertIn('PDF', report.error_message or '')
        self.assertIn('PDF renderer exploded', report.error_message or '')
        self.assertFalse(report.pdf_attachment_id)
        self.assertTrue(report.xlsx_attachment_id)
        self.assertTrue(report.xlsx_attachment_id.name.endswith('_2026-10.xlsx'))
        self.assertTrue(report.xlsx_attachment_id.raw)
        self.assertFalse(report.mail_id)
        self.assertFalse(self._mails(report))

    def test_cron_xlsx_failure_keeps_pdf_no_mail(self):
        self._task()
        with patch.object(type(self.Report), '_render_xlsx',
                          side_effect=Exception('xlsx writer exploded')):
            self._run_cron()
        report = self._project_reports()
        self.assertEqual(report.state, 'failed')
        self.assertIn('Excel', report.error_message or '')
        self.assertIn('xlsx writer exploded', report.error_message or '')
        self.assertTrue(report.pdf_attachment_id)
        self.assertEqual(report.pdf_attachment_id.raw, FAKE_PDF)
        self.assertFalse(report.xlsx_attachment_id)
        self.assertFalse(report.mail_id)
        self.assertFalse(self._mails(report))

    def test_manual_send_pdf_failure(self):
        """Send Now: no email, failed state and the Excel file are kept (no
        UserError rollback); the user gets a danger notification."""
        self._task()
        report = self._report()
        with freeze_time(CRON_NOW), mute_logger(REPORT_LOGGER), \
                patch.object(type(self.Report), '_render_pdf',
                             side_effect=Exception('PDF renderer exploded')):
            action = report.action_send()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertEqual(action['params']['type'], 'danger')
        self.assertIn('PDF generation failed', action['params']['message'])
        self.assertEqual(report.state, 'failed')
        self.assertIn('PDF', report.error_message)
        self.assertTrue(report.xlsx_attachment_id)
        self.assertFalse(report.pdf_attachment_id)
        self.assertFalse(self._mails(report))

    def test_regenerate_after_failure_replaces_stale_file(self):
        """A file of a previous successful run is dropped when it fails now."""
        self._task()
        report = self._report()
        report.action_generate()
        self.assertEqual(report.state, 'draft')
        old_pdf = report.pdf_attachment_id
        self.assertTrue(old_pdf)
        with mute_logger(REPORT_LOGGER), patch.object(
                type(self.Report), '_render_pdf', side_effect=Exception('boom')):
            report.action_generate()
        self.assertEqual(report.state, 'failed')
        self.assertFalse(report.pdf_attachment_id)
        self.assertFalse(old_pdf.exists())
        self.assertTrue(report.xlsx_attachment_id)
        # Fixed renderer: back to a complete draft.
        report.action_generate()
        self.assertEqual(report.state, 'draft')
        self.assertFalse(report.error_message)
        self.assertTrue(report.pdf_attachment_id)
        self.assertTrue(report.xlsx_attachment_id)

    def test_get_or_create_unique(self):
        first = self._report()
        self.assertEqual(self._report(), first)
        self.assertEqual(len(self._project_reports()), 1)

    # ------------------------------------------------------------------
    # mail state sync
    # ------------------------------------------------------------------
    def test_sync_mail_state_sent(self):
        self._task()
        self._run_cron()
        report = self._project_reports()
        report.mail_id.write({'state': 'sent'})
        report.action_refresh_status()
        self.assertEqual(report.state, 'sent')
        self.assertTrue(report.sent_on)

    def test_sync_mail_state_failed(self):
        self._task()
        self._run_cron()
        report = self._project_reports()
        report.mail_id.write({'state': 'exception', 'failure_reason': 'SMTP down'})
        report.action_refresh_status()
        self.assertEqual(report.state, 'failed')
        self.assertIn('SMTP down', report.error_message or '')

    # ------------------------------------------------------------------
    # manual actions
    # ------------------------------------------------------------------
    def test_send_requires_completed_month(self):
        self._task()
        report = self._report()
        with freeze_time('2026-10-20 06:00:00'), self.assertRaises(UserError):
            report.action_send()
        self.assertFalse(report.mail_id)

    def test_generate_preview_does_not_send(self):
        task = self._task()
        with freeze_time(CRON_NOW):
            self.project.action_amc_generate_previous_month()
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(report.period_start, OCT)
        self.assertEqual(report.state, 'draft')
        self.assertEqual(report.task_ids, task)
        self.assertTrue(report.pdf_attachment_id)
        self.assertTrue(report.xlsx_attachment_id)
        self.assertFalse(report.mail_id)
        self.assertEqual(self.project.amc_report_count, 1)
        action = self.project.action_view_amc_reports()
        self.assertEqual(action['res_model'], 'ft.amc.monthly.report')

    def test_generate_wizard_proposes_previous_month(self):
        task = self._task()
        with freeze_time(CRON_NOW):
            action = self.project.action_amc_open_generate_wizard()
            self.assertEqual(action['res_model'], 'ft.amc.report.generate.wizard')
            wizard = self.env['ft.amc.report.generate.wizard'].with_context(
                **action['context']).create({})
            self.assertEqual(wizard.month, OCT)
            self.assertEqual(wizard.period_label, 'October 2026')
            # Any day of the month means that month.
            wizard.month = date(2026, 10, 23)
            result = wizard.action_confirm()
        report = self._project_reports()
        self.assertEqual(len(report), 1)
        self.assertEqual(result['res_id'], report.id)
        self.assertEqual(report.period_start, OCT)
        self.assertEqual(report.state, 'draft')
        self.assertEqual(report.task_ids, task)
        self.assertFalse(report.mail_id)

    def test_generate_wizard_contract_started_this_month(self):
        # Contract started on 22 Oct: September is not covered, so the current
        # month is proposed and its (approved, completed) work is found.
        self.project.date_start = date(2026, 10, 22)
        task = self._task(dates=[date(2026, 10, 23), date(2026, 10, 23)])
        with freeze_time('2026-10-23 10:00:00'):
            wizard = self.env['ft.amc.report.generate.wizard'].with_context(
                default_project_id=self.project.id).create({})
            self.assertEqual(wizard.month, OCT)
            wizard.action_confirm()
            report = self._project_reports()
            self.assertEqual(report.task_ids, task)
            self.assertEqual(report.total_hours, 3.5)
            # A month before the contract is refused before anything is created.
            refused = self.env['ft.amc.report.generate.wizard'].create({
                'project_id': self.project.id, 'month': date(2026, 9, 15)})
            with self.assertRaises(UserError):
                refused.action_confirm()
        self.assertEqual(len(self._project_reports()), 1)

    def test_manual_send(self):
        self._task()
        report = self._report()
        with freeze_time(CRON_NOW):
            report.action_send()
        self.assertEqual(report.state, 'queued')
        self.assertTrue(report.mail_id)

    def test_reset_to_draft(self):
        self._task(approval=False)
        self._run_cron()
        report = self._project_reports()
        self.assertEqual(report.state, 'no_data')
        report.action_reset_to_draft()
        self.assertEqual(report.state, 'draft')
