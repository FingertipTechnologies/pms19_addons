# -*- coding: utf-8 -*-
"""AMC payment milestones: monthly creation, status sequence, Deployed
status, deployment-month approved hours, task Excel, milestone-driven e-mail
and the crons.

Fixtures are created as superuser (TransactionCase env is su), the same way
the ft_amc_monthly_timesheet / ft_pms_planning_workflow suites do: the task
rules of bt_project_customization (deadline, estimate, module), the approval
stamps (readonly for users), the timesheet approval stamps and the
completed-task timesheet guard all exempt su, so approved, completed tasks
with back-dated, approved timesheets can be built deterministically. The
actions under test run as a Project Manager (project.user_id, no PM job), a
Project Coordinator (approver by job) and a QA tester (no rights), so the
rights apply.

Time is frozen with freezegun; the company time zone is Asia/Kolkata. PDF
rendering is patched to fake bytes like the report suite does; the Excel
files are rendered for real (xlsxwriter) and read back with openpyxl when it
is installed, else through the workbook's XML (zipfile).
"""
import io
import zipfile
from datetime import date, datetime
from unittest.mock import patch
from xml.etree import ElementTree

from freezegun import freeze_time

from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

from odoo.addons.project.models.project_task import CLOSED_STATES
from odoo.addons.ft_amc_payment_milestone.hooks import ensure_recent_milestones
from odoo.addons.ft_amc_payment_milestone.models.project_custom_milestone import (
    AMC_EXCEL_COLUMNS, AMC_STATUS_SEQUENCE,
)

try:
    import openpyxl
except ImportError:  # pragma: no cover - depends on the environment
    openpyxl = None

FAKE_PDF = b'%PDF-fake'
REPORT_LOGGER = 'odoo.addons.ft_amc_monthly_timesheet.models.monthly_report'
MILESTONE_LOGGER = 'odoo.addons.ft_amc_payment_milestone.models.project_custom_milestone'

OCT = date(2026, 10, 1)
NOV = date(2026, 11, 1)
DEC = date(2026, 12, 1)
OCT_DEPLOY = '2026-10-20 06:00:00'  # 11:30 IST, 20 Oct
XLSX_MIMETYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def xlsx_rows(data):
    """The first sheet of an xlsx as a list of rows (list of cell values,
    None for empty cells; numbers as float, dates as serial floats)."""
    if openpyxl is not None:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        return [[cell for cell in row] for row in sheet.iter_rows(values_only=True)]
    # Fallback: xlsxwriter stores text in sharedStrings.xml and cells as
    # <c r="B3" t="s"><v>index</v></c> / <c r="E3"><v>3.5</v></c>.
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            root = ElementTree.fromstring(archive.read('xl/sharedStrings.xml'))
            for item in root.findall('m:si', _NS):
                strings.append(''.join(t.text or '' for t in item.iter(
                    '{%s}t' % _NS['m'])))
        root = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
        for row in root.find('m:sheetData', _NS).findall('m:row', _NS):
            values = {}
            for cell in row.findall('m:c', _NS):
                ref = cell.get('r')
                col = 0
                for char in ref:
                    if char.isalpha():
                        col = col * 26 + (ord(char.upper()) - ord('A') + 1)
                value_node = cell.find('m:v', _NS)
                if value_node is None:
                    values[col - 1] = None
                elif cell.get('t') == 's':
                    values[col - 1] = strings[int(value_node.text)]
                else:
                    values[col - 1] = float(value_node.text)
            width = max(values) + 1 if values else 0
            rows.append([values.get(i) for i in range(width)])
    return rows


@tagged('post_install', '-at_install')
class TestAmcPaymentMilestone(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True,
                                       tracking_disable=True))
        cls.company = cls.env.company
        cls.company.partner_id.tz = 'Asia/Kolkata'
        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('ft_amc_monthly_timesheet.email_from', 'Support Test <support@example.com>')
        params.set_param('ft_amc_monthly_timesheet.start_month', False)
        params.set_param('ft_amc_payment_milestone.send_day', False)  # default: 7

        Job = cls.env['hr.job']

        def job(name):
            return Job.search([('name', '=ilike', name)], limit=1) or Job.create({'name': name})

        user_groups = 'base.group_user,project.group_project_user'
        # Project Manager of the projects (project.user_id); job is NOT a PM job.
        cls.pm = new_test_user(cls.env, 'apm_pm', email='apm_pm@example.com', groups=user_groups)
        # Approver by job position, on any project.
        cls.coord = new_test_user(cls.env, 'apm_coord', email='apm_coord@example.com',
                                  groups=user_groups)
        # QA: no deployment / approval rights.
        cls.qa = new_test_user(cls.env, 'apm_qa', email='apm_qa@example.com', groups=user_groups)
        Employee = cls.env['hr.employee']
        for user, job_name in ((cls.pm, 'Software Developer'),
                               (cls.coord, 'Project Coordinator'),
                               (cls.qa, 'Software Tester')):
            Employee.create({'name': user.name, 'user_id': user.id, 'job_id': job(job_name).id})
        cls.employee = Employee.create({'name': 'APM Timesheet Employee', 'company_id': cls.company.id})

        cls.customer = cls.env['res.partner'].create(
            {'name': 'APM Customer', 'email': 'apm.customer@example.com'})
        cls.module = cls.env['cus.module'].search([], limit=1) or cls.env['cus.module'].create(
            {'name': 'APM Test Module'})

        cls.amc = cls._make_project('APM AMC Contract', 'amc')
        cls.amc_other = cls._make_project('APM AMC Other Contract', 'amc')
        cls.implementation = cls.env['project.project'].create({
            'name': 'APM Implementation Project', 'ft_project_type': 'implementation',
            'user_id': cls.pm.id, 'privacy_visibility': 'employees',
        })
        # Keep the day-5 report cron away from AMC projects already in the database.
        cls.env['project.project'].with_context(active_test=False).search([
            ('ft_project_type', '=', 'amc'), ('id', 'not in', (cls.amc | cls.amc_other).ids),
        ]).write({'amc_report_enabled': False})

        Stage = cls.env['project.task.type']
        projects = cls.amc | cls.amc_other | cls.implementation
        cls.working = Stage.create({
            'name': 'APM Working', 'fold': False, 'project_ids': [Command.set(projects.ids)]})
        # Final by name (COMPLETED_STAGE_NAMES), not by fold.
        cls.completed = Stage.create({
            'name': 'Completed', 'fold': False, 'project_ids': [Command.set(projects.ids)]})

        cls.Milestone = cls.env['project.custom.milestone']
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
    def _task(self, name, project=None, stage=None, approval='approved',
              hours=((date(2026, 10, 10), 2.0), (date(2026, 10, 11), 1.5))):
        """Task (title >= 20 chars, module, estimate, deadline) in Completed
        by default, AMC-approved, with APPROVED timesheets on the given days."""
        vals = {
            'name': name,
            'project_id': (project or self.amc).id,
            'stage_id': (stage or self.completed).id,
            'task_type': 'internal_call',
            'estimated': 2.0,
            'module_id': self.module.id,
            'date_deadline': datetime(2027, 6, 30, 12, 0),
        }
        if approval:
            vals.update({
                'pwf_amc_approval': approval,
                'pwf_amc_approved_on': datetime(2026, 10, 15, 6, 0),
                'pwf_amc_approved_by_id': self.coord.id,
            })
        task = self.env['project.task'].create(vals)
        for day, amount in hours:
            self._log(task, day, amount)
        return task

    def _log(self, task, day, amount, state='approved'):
        """A timesheet line in the weekly-approval ``state`` (su may write it)."""
        return self.env['account.analytic.line'].create({
            'name': 'APM work on %s' % day,
            'project_id': task.project_id.id,
            'task_id': task.id,
            'employee_id': self.employee.id,
            'date': day,
            'unit_amount': amount,
            'ft_approval_state': state,
        })

    def _deploy(self, task, when=OCT_DEPLOY, user=None):
        with freeze_time(when):
            task.with_user(user or self.coord).action_ft_mark_deployed()
        return task

    def _milestone(self, project=None, period=OCT):
        return (project or self.amc)._amc_find_monthly_milestone(period)

    def _run_milestone_cron(self, when):
        with freeze_time(when), mute_logger(MILESTONE_LOGGER, REPORT_LOGGER):
            self.Milestone._cron_ft_amc_send_monthly_milestones()

    def _run_report_cron(self, when='2026-11-06 06:00:00'):
        with freeze_time(when), mute_logger(REPORT_LOGGER):
            self.Report._cron_send_monthly_reports()

    def _reports(self, project=None, period=OCT):
        return self.Report.search([
            ('project_id', '=', (project or self.amc).id), ('period_start', '=', period)])

    def _generated_excels(self, milestone):
        return milestone.attachment_ids.filtered(lambda a: a.name.endswith('- Tasks.xlsx'))

    # ------------------------------------------------------------------
    # creation (36-39, 50)
    # ------------------------------------------------------------------
    def test_ensure_creates_once_with_naming(self):
        kickoff_before = self.amc.kick_start_meeting_date
        milestone = self.amc._amc_ensure_monthly_milestone(OCT)
        self.assertTrue(milestone)
        self.assertTrue(milestone.is_amc_monthly)
        self.assertEqual(milestone.name, 'Support Services for October 2026')
        self.assertEqual(milestone.milestone_id, 'SS-2026-10')
        self.assertEqual(milestone.amc_period_start, OCT)
        self.assertEqual(milestone.amc_period_end, date(2026, 10, 31))
        self.assertEqual(milestone.due_date, date(2026, 10, 31))
        self.assertEqual(milestone.status, 'not_started')
        self.assertTrue(milestone.amc_send_email)  # project switch is on by default
        # Created with no task / timesheet at all (37).
        self.assertFalse(milestone.amc_task_ids)
        self.assertEqual(milestone.amc_hours, 0.0)
        self.assertEqual(milestone.hours_spent, 0.0)
        self.assertFalse(milestone.amc_task_excel_id)
        # Idempotent: any day of the month resolves to the same record.
        self.assertEqual(self.amc._amc_ensure_monthly_milestone(date(2026, 10, 20)), milestone)
        self.assertEqual(self.Milestone.search_count([
            ('project_id', '=', self.amc.id), ('is_amc_monthly', '=', True),
            ('amc_period_start', '=', OCT)]), 1)
        # Visible in the project's Milestones tab; kick-off date untouched.
        self.assertIn(milestone, self.amc.custom_milestone_ids)
        self.assertEqual(self.amc.kick_start_meeting_date, kickoff_before)
        # September naming, as in the requirement.
        self.assertEqual(self.Milestone._amc_milestone_name(date(2026, 9, 1)),
                         'Support Services for September 2026')
        self.assertEqual(self.Milestone._amc_milestone_code(date(2026, 9, 1)), 'SS-2026-09')

    def test_send_flag_defaults_from_project_switch(self):
        self.amc_other.amc_report_enabled = False
        milestone = self.amc_other._amc_ensure_monthly_milestone(OCT)
        self.assertTrue(milestone)
        self.assertFalse(milestone.amc_send_email)

    def test_ineligible_projects_get_no_milestone(self):
        self.assertFalse(self.implementation._amc_ensure_monthly_milestone(OCT))
        template = self._make_project('APM AMC Template Project', 'amc', is_template=True)
        self.assertFalse(template._amc_ensure_monthly_milestone(OCT))
        # Contract not covering the month. The Closed Date is moved back
        # before the other lifecycle dates, which project_date_extension's
        # step-order rule refuses: that rule is not under test here.
        other = self.amc_other.with_context(skip_date_sequence_check=True)
        other.write({'date': date(2026, 9, 30)})
        self.assertFalse(self.amc_other._amc_ensure_monthly_milestone(OCT))
        other.write({'date': date(2027, 12, 31), 'pl_on_hold': True})
        self.assertFalse(self.amc_other._amc_ensure_monthly_milestone(OCT))
        self.amc_other.write({'pl_on_hold': False})
        # CLOSED stage: the stage key is what the rule reads.
        Stage = type(self.env['project.project.stage'])
        with patch.object(Stage, '_ft_stage_key', return_value='closed'):
            self.assertFalse(self.amc_other._amc_ensure_monthly_milestone(OCT))
        self.assertTrue(self.amc_other._amc_ensure_monthly_milestone(OCT))

    def test_hook_ensures_previous_and_current_month(self):
        with freeze_time('2026-11-10 06:00:00'):
            ensure_recent_milestones(self.env)
        self.assertTrue(self._milestone(self.amc, OCT))
        self.assertTrue(self._milestone(self.amc, NOV))
        self.assertFalse(self._milestone(self.amc, DEC))
        self.assertTrue(self._milestone(self.amc_other, OCT))

    def test_cron_creates_current_month_once(self):
        with freeze_time('2026-10-01 06:00:00'):
            self.env['project.project']._cron_ft_amc_create_monthly_milestones()
        milestone = self._milestone(self.amc, OCT)
        self.assertTrue(milestone)
        with freeze_time('2026-10-15 06:00:00'):
            self.env['project.project']._cron_ft_amc_create_monthly_milestones()
        self.assertEqual(self._milestone(self.amc, OCT), milestone)
        self.assertFalse(self._milestone(self.amc, NOV))

    # ------------------------------------------------------------------
    # statuses and sequence (41)
    # ------------------------------------------------------------------
    def test_status_set_and_labels(self):
        keys = [key for key, _label in self.Milestone._fields['status']._description_selection(self.env)]
        self.assertEqual(keys, list(AMC_STATUS_SEQUENCE))
        self.assertEqual(keys, ['not_started', 'completed', 'customer_approved',
                                'invoice_raised', 'partially_paid', 'paid'])
        self.assertNotIn('internal_approved', keys)
        milestone = self.Milestone.new({'project_id': self.amc.id, 'name': 'labels'})
        self.assertEqual(milestone._amc_status_label('customer_approved'), 'Client Approved')
        self.assertEqual(milestone._amc_status_label('invoice_raised'), 'Invoice Raised')
        self.assertEqual(milestone._amc_status_label('partially_paid'), 'Part Paid')
        self.assertEqual(milestone._amc_status_label('not_started'), 'Not Started')
        self.assertFalse(hasattr(self.Milestone, 'action_amc_approve_internally'))

    def test_status_sequence_enforced_for_amc_monthly_only(self):
        milestone = self.amc._amc_ensure_monthly_milestone(OCT)
        milestone.amc_send_email = False
        as_pm = milestone.with_user(self.pm)
        with self.assertRaises(UserError):
            as_pm.write({'status': 'customer_approved'})  # skips Completed
        with self.assertRaises(AccessError):
            milestone.with_user(self.qa).action_amc_mark_completed()
        self.assertEqual(milestone.status, 'not_started')
        as_pm.action_amc_mark_completed()  # straight from Not Started: no internal step
        self.assertEqual(milestone.status, 'completed')
        self.assertFalse(milestone.amc_report_id)  # switch off: nothing sent
        self.assertTrue(milestone.amc_task_excel_id)  # but the task Excel is attached
        with self.assertRaises(UserError):
            as_pm.write({'status': 'paid'})
        as_pm.action_amc_customer_approved()
        self.assertEqual(milestone.status, 'customer_approved')
        as_pm.action_amc_invoice_raised()
        as_pm.action_amc_partially_paid()
        as_pm.action_amc_paid()
        self.assertEqual(milestone.status, 'paid')
        self.assertFalse(milestone.is_overdue)
        as_pm.action_amc_reset_not_started()
        self.assertEqual(milestone.status, 'not_started')
        # Paid straight after Invoice Raised (the Paid button is offered there).
        milestone.write({'status': 'invoice_raised'})
        as_pm.action_amc_paid()
        self.assertEqual(milestone.status, 'paid')
        # An ordinary milestone keeps today's free editing and manual hours.
        manual = self.Milestone.create({
            'project_id': self.amc.id, 'name': 'APM manual milestone', 'hours_spent': 4.0})
        manual.with_user(self.pm).write({'status': 'paid'})
        self.assertEqual(manual.status, 'paid')
        self.assertEqual(manual.hours_spent, 4.0)
        manual.with_user(self.pm).write({'status': 'not_started', 'hours_spent': 6.0})
        self.assertEqual(manual.hours_spent, 6.0)

    # ------------------------------------------------------------------
    # Deployed (46, 47)
    # ------------------------------------------------------------------
    def test_deploy_rights_and_rules(self):
        task = self._task('APM deploy rights task approved')
        open_task = self._task('APM deploy open task not final', stage=self.working)
        with self.assertRaises(AccessError):
            task.with_user(self.qa).action_ft_mark_deployed()
        with self.assertRaises(UserError):
            open_task.with_user(self.coord).action_ft_mark_deployed()
        # Bulk is all-or-nothing.
        with self.assertRaises(UserError):
            (task | open_task).with_user(self.coord).action_ft_mark_deployed()
        self.assertFalse(task.ft_deployed)
        # Direct writes of the deployment fields are refused.
        with self.assertRaises(AccessError):
            task.with_user(self.coord).write({'ft_deployed': True})
        # The project's PM may deploy without a PM job.
        self._deploy(task, user=self.pm)
        self.assertTrue(task.ft_deployed)
        self.assertEqual(task.ft_deployed_by_id, self.pm)
        self.assertEqual(task.ft_deployed_date, datetime(2026, 10, 20, 6, 0))
        self.assertEqual(task.ft_deploy_state, 'deployed')
        with self.assertRaises(UserError):
            task.with_user(self.coord).action_ft_mark_deployed()  # already deployed
        with self.assertRaises(AccessError):
            task.with_user(self.qa).action_ft_reset_deployed()
        task.with_user(self.coord).action_ft_reset_deployed()
        self.assertFalse(task.ft_deployed)
        self.assertFalse(task.ft_deployed_date)
        self.assertEqual(task.ft_deploy_state, 'to_deploy')

    # ------------------------------------------------------------------
    # Deployed as a Status value (state = 1_deployed, after Done)
    # ------------------------------------------------------------------
    def test_deployed_status_in_selection_after_done_and_closed(self):
        keys = [key for key, _label in self.env['project.task']._fields['state']
                ._description_selection(self.env)]
        self.assertIn('1_deployed', keys)
        self.assertEqual(keys.index('1_deployed'), keys.index('1_done') + 1)
        self.assertEqual(CLOSED_STATES.get('1_deployed'), 'Billable')
        self.assertNotIn('1_deployed', self.env['project.task'].OPEN_STATES)

    def test_mark_deployed_sets_status_and_keeps_stage_and_date_end(self):
        task = self._task('APM status billable after done')
        self.assertEqual(task.state, '1_done')  # stamped by the final stage
        date_end = task.date_end
        self._deploy(task)
        self.assertEqual(task.state, '1_deployed')
        self.assertTrue(task.is_closed)
        self.assertEqual(task.stage_id, self.completed)
        self.assertTrue(task.pwf_amc_is_completed)
        self.assertEqual(task.date_end, date_end)
        self.assertEqual(task.ft_deploy_state, 'deployed')
        Task = self.env['project.task']
        self.assertIn(task, Task.search([('is_closed', '=', True), ('id', '=', task.id)]))
        self.assertNotIn(task, Task.search([('is_closed', '=', False), ('id', '=', task.id)]))
        self.assertIn(task, Task.search([('state', '=', '1_deployed'), ('id', '=', task.id)]))
        # A stage write that keeps the task in its final stage does not reset
        # the closed state (core's _compute_state keeps CLOSED_STATES).
        task.write({'stage_id': self.completed.id})
        self.assertEqual(task.state, '1_deployed')
        # Undo: back to Done, still closed, still in Completed.
        task.with_user(self.coord).action_ft_reset_deployed()
        self.assertEqual(task.state, '1_done')
        self.assertTrue(task.is_closed)
        self.assertFalse(task.ft_deployed)
        self.assertEqual(task.stage_id, self.completed)

    def test_reopen_returns_status_to_in_progress(self):
        task = self._task('APM status reopened after billable status')
        self._deploy(task)
        self.assertEqual(task.state, '1_deployed')
        task.write({'stage_id': self.working.id})
        self.assertEqual(task.state, '01_in_progress')
        self.assertFalse(task.is_closed)
        self.assertFalse(task.ft_deployed)
        self.assertFalse(task.ft_deploy_state)
        # Completed again: Done (not Deployed) until it is deployed again.
        task.write({'stage_id': self.completed.id})
        self.assertEqual(task.state, '1_done')
        self.assertFalse(task.ft_deployed)

    def test_direct_status_writes(self):
        task = self._task('APM status written directly by users')
        # Nobody sets Deployed through the Status widget, approver included.
        with self.assertRaises(AccessError):
            task.with_user(self.coord).write({'state': '1_deployed'})
        with self.assertRaises(AccessError):
            task.with_user(self.pm).write({'state': '1_deployed'})
        self.assertEqual(task.state, '1_done')
        self.assertFalse(task.ft_deployed)
        with self.assertRaises(AccessError):
            self.env['project.task'].with_user(self.coord).create({
                'name': 'APM task created already billable',
                'project_id': self.amc.id,
                'stage_id': self.completed.id,
                'task_type': 'internal_call',
                'estimated': 2.0,
                'module_id': self.module.id,
                'date_deadline': datetime(2027, 6, 30, 12, 0),
                'state': '1_deployed',
            })
        self._deploy(task)
        october = self._milestone(self.amc, OCT)
        self.assertEqual(task.custom_milestone_id, october)
        # A user without the Undo right cannot move a deployed task's Status.
        with self.assertRaises(AccessError):
            task.with_user(self.qa).write({'state': '1_done'})
        self.assertEqual(task.state, '1_deployed')
        self.assertTrue(task.ft_deployed)
        # An approver moving it to Done undoes the deployment (same rules as
        # Undo Deployed): flag cleared, milestone detached while open.
        task.with_user(self.coord).write({'state': '1_done'})
        self.assertEqual(task.state, '1_done')
        self.assertFalse(task.ft_deployed)
        self.assertFalse(task.ft_deployed_date)
        self.assertFalse(task.custom_milestone_id)
        self.assertEqual(task.ft_deploy_state, 'to_deploy')
        # Other statuses go the same way (the project's PM may undo).
        self._deploy(task, when='2026-10-21 06:00:00')
        task.with_user(self.pm).write({'state': '01_in_progress'})
        self.assertEqual(task.state, '01_in_progress')
        self.assertFalse(task.ft_deployed)

    def test_overdue_dashboard_lists_deployed_task_as_completed(self):
        """ft_amc_overdue_dashboard (no dependency either way): a Deployed
        task is a completed one, with the overdue figure frozen when it
        became Done, not re-stamped by the deployment."""
        if 'ft.amc.overdue.dashboard' not in self.env.registry:
            self.skipTest('ft_amc_overdue_dashboard is not installed')
        # Original deadline 10 Oct (set on create, as the overdue suite does:
        # su is exempt from the future-deadline rule there; 12:00 UTC is the
        # same local day in any zone), completed 18 Oct: 8 days late, frozen
        # on completion.
        task = self.env['project.task'].create({
            'name': 'APM billable task on the overdue board',
            'project_id': self.amc.id,
            'stage_id': self.working.id,
            'task_type': 'internal_call',
            'estimated': 2.0,
            'module_id': self.module.id,
            'date_deadline': datetime(2026, 10, 10, 12, 0),
            'pwf_amc_approval': 'approved',
            'pwf_amc_approved_on': datetime(2026, 10, 15, 6, 0),
            'pwf_amc_approved_by_id': self.coord.id,
        })
        self.assertEqual(task.pwf_original_deadline, datetime(2026, 10, 10, 12, 0))
        with freeze_time('2026-10-18 12:00:00'):
            task.write({'stage_id': self.completed.id})
        self.assertEqual(task.state, '1_done')
        self.assertEqual(task.ft_historical_overdue_days, 8)
        self._deploy(task, when='2026-11-30 12:00:00')
        self.assertEqual(task.state, '1_deployed')
        self.assertEqual(task.ft_historical_overdue_days, 8)
        Dashboard = self.env['ft.amc.overdue.dashboard']
        rows = Dashboard.get_dashboard_data(
            {'project_id': self.amc.id, 'include_closed': True})['rows']
        row = [r for r in rows if r['id'] == task.id]
        self.assertEqual(len(row), 1)
        self.assertTrue(row[0]['is_closed'])
        self.assertEqual(row[0]['overdue_days'], 8)
        self.assertEqual(row[0]['completed_on'], '2026-10-18')
        open_rows = Dashboard.get_dashboard_data({'project_id': self.amc.id})['rows']
        self.assertNotIn(task.id, [r['id'] for r in open_rows])

    # ------------------------------------------------------------------
    # link and hours (42, 48, 49)
    # ------------------------------------------------------------------
    def test_all_hours_go_to_deployment_month(self):
        task = self._task('APM task worked Oct and Nov billable Dec',
                          hours=((date(2026, 10, 10), 2.0), (date(2026, 11, 5), 3.0)))
        self._deploy(task, when='2026-12-10 06:00:00')
        december = self._milestone(self.amc, DEC)
        self.assertTrue(december, "the December milestone is created on the fly")
        self.assertEqual(task.custom_milestone_id, december)
        self.assertEqual(december.amc_task_ids, task)
        self.assertEqual(december.amc_task_count, 1)
        self.assertAlmostEqual(december.amc_hours, 5.0)
        self.assertAlmostEqual(december.hours_spent, 5.0)
        october = self.amc._amc_ensure_monthly_milestone(OCT)
        november = self.amc._amc_ensure_monthly_milestone(NOV)
        self.assertFalse(october.amc_task_ids)
        self.assertFalse(november.amc_task_ids)
        self.assertEqual(october.amc_hours, 0.0)
        self.assertEqual(november.amc_hours, 0.0)

    def test_only_approved_timesheets_count(self):
        task = self._task('APM task with pending and rejected lines',
                          hours=((date(2026, 10, 10), 2.0),))
        pending = self._log(task, date(2026, 10, 12), 4.0, state='pending')
        self._log(task, date(2026, 10, 13), 8.0, state='rejected')
        self.assertAlmostEqual(task._ft_amc_approved_hours(), 2.0)
        self._deploy(task)
        october = self._milestone(self.amc, OCT)
        self.assertAlmostEqual(october.amc_hours, 2.0)
        self.assertAlmostEqual(october.hours_spent, 2.0)
        # Approving a pending line later is picked up by the stored compute.
        pending.write({'ft_approval_state': 'approved'})
        self.assertAlmostEqual(task._ft_amc_approved_hours(), 6.0)
        self.assertAlmostEqual(october.amc_hours, 6.0)
        # Editing a reviewed line sends it back to pending (workflow rule)
        # and the milestone follows.
        pending.write({'unit_amount': 5.0})
        self.assertEqual(pending.ft_approval_state, 'pending')
        self.assertAlmostEqual(task._ft_amc_approved_hours(), 2.0)
        self.assertAlmostEqual(october.amc_hours, 2.0)

    def test_approval_after_deployment_links_and_reset_unlinks(self):
        task = self._task('APM task billable before approval', approval=False)
        self._deploy(task)
        self.assertTrue(task.ft_deployed)
        self.assertFalse(task.custom_milestone_id)
        task.write({'pwf_amc_approval': 'approved'})
        october = self._milestone(self.amc, OCT)
        self.assertEqual(task.custom_milestone_id, october)
        self.assertAlmostEqual(october.amc_hours, 3.5)
        task.write({'pwf_amc_approval': False})
        self.assertFalse(task.custom_milestone_id)
        self.assertEqual(october.amc_hours, 0.0)

    def test_undo_and_reopen_unlink_while_open_keep_once_sent(self):
        task = self._task('APM task undone then reopened')
        self._deploy(task)
        october = self._milestone(self.amc, OCT)
        self.assertEqual(task.custom_milestone_id, october)
        task.with_user(self.coord).action_ft_reset_deployed()
        self.assertFalse(task.custom_milestone_id)
        self._deploy(task, when='2026-10-21 06:00:00')
        self.assertEqual(task.custom_milestone_id, october)
        # Reopen (leaving the final stage) clears the deployment and the link.
        task.write({'stage_id': self.working.id})
        self.assertFalse(task.ft_deployed)
        self.assertFalse(task.custom_milestone_id)
        # Once the month is completed (sent), the link is kept.
        kept = self._task('APM task kept after completion')
        self._deploy(kept, when='2026-10-22 06:00:00')
        october.write({'amc_send_email': False, 'status': 'completed'})
        kept.with_user(self.coord).action_ft_reset_deployed()
        self.assertFalse(kept.ft_deployed)
        self.assertEqual(kept.custom_milestone_id, october)

    # ------------------------------------------------------------------
    # task Excel
    # ------------------------------------------------------------------
    def test_task_excel_rows_and_workbook(self):
        task = self._task('APM first task of the Excel',
                          hours=((date(2026, 10, 10), 2.0), (date(2026, 10, 11), 1.5)))
        self._log(task, date(2026, 10, 12), 4.0, state='pending')  # not counted
        other = self._task('APM second task of the Excel', hours=((date(2026, 10, 15), 3.0),))
        other.write({'ft_billable_hours': 2.5})  # hand-overridden billable hours
        self._deploy(task)
        self._deploy(other, when='2026-10-25 06:00:00')
        milestone = self._milestone(self.amc, OCT)
        # The row data the sheet is built from.
        rows = milestone._amc_task_excel_rows()
        self.assertEqual([list(r) for r in rows], [list(AMC_EXCEL_COLUMNS)] * 2)
        self.assertEqual([r['task'] for r in rows], [task.name, other.name])
        self.assertEqual(rows[0]['stage'], 'Completed')
        self.assertEqual(rows[0]['deployed_on'], date(2026, 10, 20))
        self.assertEqual(rows[1]['deployed_on'], date(2026, 10, 25))
        self.assertEqual(rows[0]['approved_by'], self.coord.name)
        self.assertAlmostEqual(rows[0]['approved_hours'], 3.5)
        self.assertAlmostEqual(rows[0]['billable_hours'], task.ft_billable_hours)
        self.assertAlmostEqual(rows[1]['approved_hours'], 3.0)
        self.assertAlmostEqual(rows[1]['billable_hours'], 2.5)
        # The button: managers / the project's PM only, AMC monthly only.
        with self.assertRaises(AccessError):
            milestone.with_user(self.qa).action_amc_generate_task_excel()
        manual = self.Milestone.create({'project_id': self.amc.id, 'name': 'APM manual milestone'})
        with self.assertRaises(UserError):
            manual.with_user(self.pm).action_amc_generate_task_excel()
        milestone.with_user(self.pm).action_amc_generate_task_excel()
        attachment = milestone.amc_task_excel_id
        self.assertTrue(attachment)
        self.assertEqual(attachment.name, 'Support Services for October 2026 - Tasks.xlsx')
        self.assertEqual(attachment.mimetype, XLSX_MIMETYPE)
        self.assertEqual((attachment.res_model, attachment.res_id), (milestone._name, milestone.id))
        self.assertIn(attachment, milestone.attachment_ids)
        self.assertEqual(self._generated_excels(milestone), attachment)
        # Workbook content: header block, column headers, task rows, total.
        sheet = xlsx_rows(attachment.raw)
        text = [[cell for cell in row if isinstance(cell, str)] for row in sheet]
        self.assertEqual(sheet[0][0], milestone.name)
        info = {row[0]: row[1] for row in text if len(row) >= 2}
        self.assertEqual(info.get('Project'), self.amc.name)
        self.assertEqual(info.get('Customer'), self.customer.display_name)
        self.assertEqual(info.get('Milestone status'), 'Not Started')
        self.assertIn('October 2026', info.get('Billing period') or '')
        header_index = next(i for i, row in enumerate(sheet) if row and row[0] == 'Task')
        self.assertEqual(sheet[header_index][:6], ['Task', 'Stage', 'Marked Billable On', 'Approved By',
                                                   'Approved Hours', 'Billable Hours'])
        first, second, total = sheet[header_index + 1], sheet[header_index + 2], sheet[header_index + 3]
        self.assertEqual(first[0], task.name)
        self.assertEqual(first[1], 'Completed')
        self.assertEqual(first[3], self.coord.name)
        self.assertAlmostEqual(first[4], 3.5)
        self.assertAlmostEqual(first[5], task.ft_billable_hours)
        self.assertEqual(second[0], other.name)
        self.assertAlmostEqual(second[4], 3.0)
        self.assertAlmostEqual(second[5], 2.5)
        self.assertEqual(total[0], 'Total')
        self.assertAlmostEqual(total[4], 6.5)
        self.assertAlmostEqual(total[5], task.ft_billable_hours + 2.5)
        # Regeneration replaces the previous generated file, user uploads stay.
        upload = self.env['ir.attachment'].create({
            'name': 'APM customer PO.pdf', 'raw': b'%PDF-po', 'mimetype': 'application/pdf',
            'res_model': milestone._name, 'res_id': milestone.id})
        milestone.write({'attachment_ids': [Command.link(upload.id)]})
        milestone.with_user(self.pm).action_amc_generate_task_excel()
        self.assertFalse(attachment.exists())
        self.assertEqual(self._generated_excels(milestone), milestone.amc_task_excel_id)
        self.assertNotEqual(milestone.amc_task_excel_id, attachment)
        self.assertIn(upload, milestone.attachment_ids)
        self.assertEqual(len(milestone.attachment_ids), 2)

    def test_task_excel_without_tasks(self):
        milestone = self.amc._amc_ensure_monthly_milestone(OCT)
        self.assertEqual(milestone._amc_task_excel_rows(), [])
        attachment = milestone._amc_build_task_excel()
        sheet = xlsx_rows(attachment.raw)
        flat = [cell for row in sheet for cell in row if isinstance(cell, str)]
        self.assertIn('No approved, billable task in this billing period.', flat)
        self.assertIn('Total', flat)

    # ------------------------------------------------------------------
    # e-mail (43, 44)
    # ------------------------------------------------------------------
    def test_completed_sends_timesheet_email_with_task_excel(self):
        task = self._task('APM task sent with the milestone')
        self._log(task, date(2026, 10, 12), 4.0, state='pending')  # not in the report either
        self._deploy(task)
        milestone = self._milestone(self.amc, OCT)
        self.assertTrue(milestone.amc_send_email)
        # The milestone switch rules, not the project's (44).
        self.amc.amc_report_enabled = False
        with freeze_time('2026-11-07 06:00:00'):
            milestone.with_user(self.pm).action_amc_mark_completed()
        self.assertEqual(milestone.status, 'completed')
        report = milestone.amc_report_id
        self.assertTrue(report)
        self.assertEqual(report, self._reports())
        self.assertEqual(report.state, 'queued')
        self.assertEqual(report.task_ids, task)
        self.assertAlmostEqual(report.total_hours, 3.5)  # approved lines only
        self.assertAlmostEqual(milestone.amc_hours, 3.5)
        self.assertTrue(milestone.amc_sent_on)
        mail = report.mail_id
        self.assertTrue(mail)
        self.assertIn('apm.customer@example.com', mail.email_to)
        # The milestone's task Excel is on the milestone and on the mail,
        # next to the report's own PDF and Excel.
        excel = milestone.amc_task_excel_id
        self.assertTrue(excel)
        self.assertIn(excel, milestone.attachment_ids)
        self.assertEqual(set(mail.attachment_ids.ids),
                         {report.pdf_attachment_id.id, report.xlsx_attachment_id.id, excel.id})
        self.assertEqual(excel.name, 'Support Services for October 2026 - Tasks.xlsx')
        sheet = xlsx_rows(excel.raw)
        header_index = next(i for i, row in enumerate(sheet) if row and row[0] == 'Task')
        self.assertEqual(sheet[header_index + 1][0], task.name)
        self.assertAlmostEqual(sheet[header_index + 1][4], 3.5)

    def test_completed_without_switch_sends_nothing(self):
        task = self._task('APM task completed without e-mail')
        self._deploy(task)
        milestone = self._milestone(self.amc, OCT)
        milestone.amc_send_email = False
        milestone.with_user(self.pm).action_amc_mark_completed()
        self.assertEqual(milestone.status, 'completed')
        self.assertFalse(milestone.amc_report_id)
        self.assertFalse(milestone.amc_sent_on)
        self.assertFalse(self._reports())
        self.assertTrue(milestone.amc_task_excel_id)  # the Excel is still attached

    def test_send_failure_refuses_completion(self):
        task = self._task('APM task whose customer has no e-mail')
        self._deploy(task)
        milestone = self._milestone(self.amc, OCT)
        self.customer.email = False
        with self.assertRaises(UserError):
            milestone.with_user(self.pm).action_amc_mark_completed()
        self.assertEqual(milestone.status, 'not_started')
        self.assertFalse(milestone.amc_sent_on)

    # ------------------------------------------------------------------
    # crons
    # ------------------------------------------------------------------
    def test_day7_cron_completes_previous_month(self):
        task = self._task('APM task for the day seven cron')
        self._deploy(task)
        october = self._milestone(self.amc, OCT)
        self.assertEqual(october.status, 'not_started')
        self.amc_other.amc_report_enabled = False
        waiting = self.amc_other._amc_ensure_monthly_milestone(OCT)  # switch off: manual flow
        self.assertFalse(waiting.amc_send_email)
        november = self.amc._amc_ensure_monthly_milestone(NOV)

        self._run_milestone_cron('2026-11-06 06:00:00')
        self.assertEqual(october.status, 'not_started')
        self.assertFalse(october.amc_report_id)

        self._run_milestone_cron('2026-11-07 06:00:00')
        self.assertEqual(october.status, 'completed')
        self.assertEqual(october.amc_report_id.state, 'queued')
        self.assertTrue(october.amc_sent_on)
        self.assertTrue(october.amc_task_excel_id)
        self.assertIn(october.amc_task_excel_id, october.amc_report_id.mail_id.attachment_ids)
        # Switch off: untouched, and no activity is scheduled any more.
        self.assertEqual(waiting.status, 'not_started')
        self.assertFalse(waiting.activity_ids)
        # The current month is not over: untouched.
        self.assertEqual(november.status, 'not_started')
        self.assertFalse(november.amc_report_id)

        self._run_milestone_cron('2026-11-08 06:00:00')
        self.assertEqual(self.env['mail.mail'].search_count([
            ('model', '=', 'ft.amc.monthly.report'),
            ('res_id', '=', october.amc_report_id.id)]), 1)
        # December's run picks November up.
        self._run_milestone_cron('2026-12-07 06:00:00')
        self.assertEqual(november.status, 'completed')

    def test_day7_cron_failure_keeps_not_started(self):
        task = self._task('APM task for the failing day seven cron')
        self._deploy(task)
        october = self._milestone(self.amc, OCT)
        self.customer.email = False
        self._run_milestone_cron('2026-11-07 06:00:00')
        self.assertEqual(october.status, 'not_started')
        self.assertFalse(october.amc_sent_on)
        self.assertFalse(october.amc_task_excel_id)  # rolled back with the status
        self.assertTrue(october.message_ids.filtered(
            lambda m: 'Automatic sending' in (m.body or '')))

    def test_day5_report_cron_skips_months_with_a_milestone(self):
        self._task('APM task of the milestone-driven month')
        self.amc._amc_ensure_monthly_milestone(OCT)
        self._task('APM task of the project without milestone', project=self.amc_other)
        self._run_report_cron()
        skipped = self._reports(self.amc)
        self.assertNotIn(skipped.state, ('queued', 'sent'))
        self.assertFalse(skipped.mail_id)
        # A month without a milestone keeps the original day-5 behaviour.
        sent = self._reports(self.amc_other)
        self.assertEqual(sent.state, 'queued')
        self.assertTrue(sent.mail_id)

    # ------------------------------------------------------------------
    # timesheet date check (project_date_extension)
    # ------------------------------------------------------------------
    def test_timesheet_date_check_bypassed_for_amc_monthly(self):
        task = self._task('APM task with a line after the due date')
        self._deploy(task)
        self.assertEqual(task.custom_milestone_id.due_date, date(2026, 10, 31))
        line = self._log(task, date(2026, 11, 3), 1.0)
        line.with_user(self.pm)._ft_check_milestone_timesheet_date()  # no error
        manual = self.Milestone.create({
            'project_id': self.amc.id, 'name': 'APM manual stage milestone',
            'due_date': date(2026, 10, 31)})
        task.write({'custom_milestone_id': manual.id})
        with self.assertRaises(UserError):
            line.with_user(self.pm)._ft_check_milestone_timesheet_date()
