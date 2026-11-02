# -*- coding: utf-8 -*-
"""Timesheet review from inside the task form (19.0.1.27.0): the task's
"Approve All Pending" / "Reject All Pending" actions and the visibility flag
behind the buttons. The per-line buttons call the existing line actions
(action_ft_timesheet_approve / _reject / _reset), covered by the list-level
behaviour; here only the task-level wrappers and the flag are checked.

Fixtures are created as superuser (see test_amc_approval): a General project
managed by ``proj_pm`` (a Software Developer, so NOT a global approver), a
developer ``dev`` with no review rights and a Project Coordinator ``coord``
who may review every project.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestTaskTimesheetApproval(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        Job = cls.env['hr.job']

        def job(name):
            return Job.search([('name', '=ilike', name)], limit=1) or Job.create({'name': name})

        cls.proj_pm = new_test_user(
            cls.env, 'pwf_tsa_proj_pm', groups='base.group_user,project.group_project_user')
        cls.coord = new_test_user(
            cls.env, 'pwf_tsa_coord', groups='base.group_user,project.group_project_user')
        cls.dev = new_test_user(
            cls.env, 'pwf_tsa_dev', groups='base.group_user,project.group_project_user')
        Employee = cls.env['hr.employee']
        cls.employees = {}
        for user, job_name in ((cls.proj_pm, 'Software Developer'),
                               (cls.coord, 'Project Coordinator'),
                               (cls.dev, 'Software Developer')):
            cls.employees[user] = Employee.create({
                'name': user.name, 'user_id': user.id, 'job_id': job(job_name).id})

        cls.project = cls.env['project.project'].create({
            'name': 'PWF TSA Project', 'ft_project_type': 'general',
            'user_id': cls.proj_pm.id, 'privacy_visibility': 'employees',
        })
        cls.other = cls.env['project.project'].create({
            'name': 'PWF TSA Other Project', 'ft_project_type': 'general',
            'user_id': cls.dev.id, 'privacy_visibility': 'employees',
        })
        cls.today = fields.Date.context_today(cls.project)

    def _task(self, project=None, name='PWF timesheet approval task'):
        # Same values as test_amc_approval: the title / estimate / deadline
        # rules of bt_project_customization are satisfied even when not su.
        return self.env['project.task'].create({
            'name': name,
            'project_id': (project or self.project).id,
            'task_type': 'internal_call',
            'estimated': 2.0,
            'date_deadline': fields.Datetime.now() + timedelta(days=3),
        })

    def _line(self, task, hours, employee=None, day=None):
        return self.env['account.analytic.line'].create({
            'name': 'PWF TSA work',
            'project_id': task.project_id.id,
            'task_id': task.id,
            'employee_id': (employee or self.employees[self.dev]).id,
            'date': day or self.today,
            'unit_amount': hours,
        })

    # ------------------------------------------------------------------
    # visibility flag
    # ------------------------------------------------------------------
    def test_can_review_flag_follows_the_review_rule(self):
        task = self._task()
        self.assertTrue(task.with_user(self.proj_pm).ft_can_review_timesheets,
                        'the Project Manager of the project may review')
        self.assertTrue(task.with_user(self.coord).ft_can_review_timesheets,
                        'a Project Coordinator job reviews every project')
        self.assertFalse(task.with_user(self.dev).ft_can_review_timesheets,
                         'a developer who is not the PM may not review')
        other = self._task(project=self.other)
        self.assertFalse(other.with_user(self.proj_pm).ft_can_review_timesheets,
                         'PM of another project only')
        self.assertTrue(other.with_user(self.dev).ft_can_review_timesheets,
                        'PM of this one')

    # ------------------------------------------------------------------
    # approve all pending
    # ------------------------------------------------------------------
    def test_approve_all_pending_approves_only_the_pending_lines(self):
        task = self._task()
        pending_a = self._line(task, 2.0)
        pending_b = self._line(task, 1.5, day=self.today - timedelta(days=1))
        rejected = self._line(task, 1.0, day=self.today - timedelta(days=2))
        rejected._ft_timesheet_apply_approval('rejected', 'no')
        # A line of another task of the project is not touched.
        sibling = self._task(name='PWF timesheet approval sibling')
        untouched = self._line(sibling, 3.0)
        self.assertEqual(task.ft_pending_timesheet_count, 2)

        res = task.with_user(self.proj_pm).action_ft_timesheet_approve_all()
        self.assertEqual(res['type'], 'ir.actions.client')
        self.assertEqual(res['tag'], 'display_notification')
        self.assertEqual(pending_a.ft_approval_state, 'approved')
        self.assertEqual(pending_b.ft_approval_state, 'approved')
        self.assertEqual(pending_a.ft_approved_by_id, self.proj_pm)
        self.assertEqual(rejected.ft_approval_state, 'rejected',
                         'a reviewed line is left alone')
        self.assertEqual(untouched.ft_approval_state, 'pending')
        task.invalidate_recordset()
        self.assertEqual(task.ft_pending_timesheet_count, 0)
        self.assertAlmostEqual(task.ft_approved_hours, 3.5)
        self.assertAlmostEqual(task.ft_rejected_hours, 1.0)
        # Nothing left to approve: a clear refusal, not a silent no-op.
        with self.assertRaises(UserError):
            task.with_user(self.proj_pm).action_ft_timesheet_approve_all()

    def test_approve_all_pending_needs_review_rights(self):
        task = self._task()
        line = self._line(task, 2.0)
        with self.assertRaises(AccessError):
            task.with_user(self.dev).action_ft_timesheet_approve_all()
        self.assertEqual(line.ft_approval_state, 'pending')
        # A global approver (Project Coordinator job) may, on any project.
        task.with_user(self.coord).action_ft_timesheet_approve_all()
        self.assertEqual(line.ft_approval_state, 'approved')
        self.assertEqual(line.ft_approved_by_id, self.coord)

    # ------------------------------------------------------------------
    # reject all pending
    # ------------------------------------------------------------------
    def test_reject_all_pending_opens_the_reason_wizard_on_pending_lines(self):
        task = self._task()
        pending = self._line(task, 2.0)
        approved = self._line(task, 1.0, day=self.today - timedelta(days=1))
        approved._ft_timesheet_apply_approval('approved')

        action = task.with_user(self.proj_pm).action_ft_timesheet_reject_all()
        self.assertEqual(action['res_model'], 'ft.timesheet.reject.wizard')
        self.assertEqual(action['context']['default_line_ids'], [(6, 0, pending.ids)])
        wizard = self.env['ft.timesheet.reject.wizard'].with_user(self.proj_pm).create({
            'line_ids': [(6, 0, pending.ids)], 'reason': 'wrong task',
        })
        wizard.action_confirm()
        self.assertEqual(pending.ft_approval_state, 'rejected')
        self.assertEqual(pending.ft_rejection_reason, 'wrong task')
        self.assertEqual(approved.ft_approval_state, 'approved')
        with self.assertRaises(AccessError):
            task.with_user(self.dev).action_ft_timesheet_reject_all()
        with self.assertRaises(UserError):
            # Nothing pending any more.
            task.with_user(self.proj_pm).action_ft_timesheet_reject_all()
