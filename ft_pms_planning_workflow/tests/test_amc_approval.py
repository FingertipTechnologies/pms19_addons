# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestPmsAmcApproval(TransactionCase):
    """Task approval (AMC projects only). Fixtures are created as superuser.

    Approval tests use the AMC projects (``amc`` / ``amc_other``); the
    General and Implementation projects check the refusals.

    Task titles are at least 20 characters (TASK_TITLE_MIN_LEN).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        Job = cls.env['hr.job']

        def job(name):
            return Job.search([('name', '=ilike', name)], limit=1) or Job.create({'name': name})

        cls.admin = new_test_user(
            cls.env, 'pwf_amc_admin',
            groups='base.group_user,base.group_system,project.group_project_manager')
        # Project Manager of the project only (job is NOT a PM job).
        cls.proj_pm = new_test_user(
            cls.env, 'pwf_amc_proj_pm', groups='base.group_user,project.group_project_user')
        # Approver by job position (PM_JOB_NAMES), on any project.
        cls.coord = new_test_user(
            cls.env, 'pwf_amc_coord', groups='base.group_user,project.group_project_user')
        cls.dev = new_test_user(
            cls.env, 'pwf_amc_dev', groups='base.group_user,project.group_project_user')
        # Approver by Team Lead job position, on any project.
        cls.tl = new_test_user(
            cls.env, 'pwf_amc_tl', groups='base.group_user,project.group_project_user')
        Employee = cls.env['hr.employee']
        for user, job_name in ((cls.proj_pm, 'Software Developer'),
                               (cls.coord, 'Project Coordinator'),
                               (cls.dev, 'Software Developer'),
                               (cls.tl, 'Technical Lead')):
            Employee.create({'name': user.name, 'user_id': user.id,
                             'job_id': job(job_name).id})

        Project = cls.env['project.project']
        cls.amc = Project.create({
            'name': 'PWF AMC Project', 'ft_project_type': 'amc',
            'user_id': cls.proj_pm.id, 'privacy_visibility': 'employees',
        })
        cls.amc_other = Project.create({
            'name': 'PWF AMC Other', 'ft_project_type': 'amc',
            'user_id': cls.dev.id, 'privacy_visibility': 'employees',
        })
        cls.general = Project.create({
            'name': 'PWF General Project', 'ft_project_type': 'general',
            'user_id': cls.proj_pm.id, 'privacy_visibility': 'employees',
        })
        cls.implementation = Project.create({
            'name': 'PWF Implementation Project', 'ft_project_type': 'implementation',
            'user_id': cls.proj_pm.id, 'privacy_visibility': 'employees',
        })
        projects = cls.amc | cls.amc_other | cls.general | cls.implementation
        Stage = cls.env['project.task.type']
        cls.working = Stage.create({
            'name': 'PWF AMC Working', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})
        # Final by name (COMPLETED_STAGE_NAMES), not by fold.
        cls.completed = Stage.create({
            'name': 'Completed', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})

    def _task(self, project=None, stage=None, name='PWF approval test task'):
        vals = {
            'name': name,
            'project_id': (project or self.amc).id,
            'stage_id': (stage or self.completed).id,
            'task_type': 'internal_call',
            'estimated': 2.0,
            'date_deadline': fields.Datetime.now() + timedelta(days=3),
        }
        if (project or self.amc).ft_project_type == 'implementation':
            # Explicit source, so the Implementation-only Task Source rules
            # do not depend on the project's pipeline stage.
            vals.update(task_source='unplanned',
                        unplanned_reason='Raised during the approval tests.')
        return self.env['project.task'].create(vals)

    def _task_without_project(self, name='PWF approval no-project task'):
        task = self.env['project.task'].create({
            'name': name,
            'project_id': False,
            'task_type': 'internal_call',
            'estimated': 2.0,
            'date_deadline': fields.Datetime.now() + timedelta(days=3),
        })
        self.assertFalse(task.project_id)
        return task

    def _as(self, tasks, user):
        return tasks.with_user(user)

    # ------------------------------------------------------------------
    # approve
    # ------------------------------------------------------------------
    def test_approve_single(self):
        task = self._task()
        self.assertTrue(task.pwf_amc_is_completed)
        self.assertTrue(self._as(task, self.proj_pm).pwf_amc_can_approve)
        action = self._as(task, self.proj_pm).action_pwf_amc_approve()
        self.assertEqual(action['tag'], 'display_notification')
        self.assertIn('1 task(s) approved', action['params']['message'])
        self.assertEqual(task.pwf_amc_approval, 'approved')
        self.assertEqual(task.pwf_amc_approved_by_id, self.proj_pm)
        self.assertTrue(task.pwf_amc_approved_on)
        self.assertTrue(any('approved' in (m.body or '') for m in task.message_ids))

    def test_approve_bulk(self):
        tasks = (self._task(name='PWF approval test task A') | self._task(name='PWF approval test task B')
                 | self._task(name='PWF approval test task C'))
        action = self._as(tasks, self.coord).action_pwf_amc_approve()
        self.assertIn('3 task(s) approved', action['params']['message'])
        self.assertEqual(set(tasks.mapped('pwf_amc_approval')), {'approved'})
        self.assertEqual(tasks.mapped('pwf_amc_approved_by_id'), self.coord)

    def test_approve_clears_previous_reason(self):
        task = self._task()
        self._reject(task, self.proj_pm, 'Missing tests')
        self._as(task, self.proj_pm).action_pwf_amc_approve()
        self.assertEqual(task.pwf_amc_approval, 'approved')
        self.assertFalse(task.pwf_amc_rejection_reason)

    # ------------------------------------------------------------------
    # refusals
    # ------------------------------------------------------------------
    def test_refuse_general_and_implementation_tasks(self):
        """Task approval is AMC-only: Implementation / General tasks are refused."""
        general = self._task(project=self.general, name='PWF approval General task')
        impl = self._task(project=self.implementation, name='PWF approval Implementation task')
        for task, label in ((general, 'General'), (impl, 'Implementation')):
            # Not even the project's PM or an Administrator can act on it.
            for user in (self.proj_pm, self.admin):
                self.assertFalse(self._as(task, user).pwf_amc_can_approve)
                with self.assertRaisesRegex(UserError, 'only used on AMC projects') as cm:
                    self._as(task, user).action_pwf_amc_approve()
                msg = str(cm.exception)
                self.assertIn(task.name, msg)
                self.assertIn('belongs to a %s project' % label, msg)
            with self.assertRaisesRegex(UserError, 'only used on AMC projects'):
                self._as(task, self.coord).action_pwf_amc_reject()
            with self.assertRaisesRegex(UserError, 'only used on AMC projects'):
                self._as(task, self.tl).action_pwf_amc_reset()
            # Direct write (form / list multi-edit / RPC) obeys the same rule.
            with self.assertRaisesRegex(UserError, 'only used on AMC projects'):
                self._as(task, self.admin).write({'pwf_amc_approval': 'approved'})
            self.assertFalse(task.pwf_amc_approval)

    def test_mixed_amc_and_non_amc_bulk_refused(self):
        """A bulk selection with one non-AMC task is refused as a whole."""
        amc_task = self._task(name='PWF approval AMC bulk task')
        general = self._task(project=self.general, name='PWF approval General bulk task')
        with self.assertRaisesRegex(UserError, 'only used on AMC projects'):
            self._as(amc_task | general, self.coord).action_pwf_amc_approve()
        self.assertFalse(amc_task.pwf_amc_approval)
        self.assertFalse(general.pwf_amc_approval)

    def test_refuse_task_without_project(self):
        task = self._task_without_project()
        self.assertFalse(self._as(task, self.admin).pwf_amc_can_approve)
        with self.assertRaisesRegex(UserError, 'project') as cm:
            self._as(task, self.admin).action_pwf_amc_approve()
        self.assertIn(task.name, str(cm.exception))
        with self.assertRaisesRegex(UserError, 'project'):
            self._as(task, self.admin).action_pwf_amc_reject()
        self.assertFalse(task.pwf_amc_approval)

    def test_approve_any_stage(self):
        """Approval is not limited to completed tasks."""
        task = self._task(stage=self.working)
        self.assertFalse(task.pwf_amc_is_completed)
        self.assertTrue(self._as(task, self.proj_pm).pwf_amc_can_approve)
        self._as(task, self.proj_pm).action_pwf_amc_approve()
        self.assertEqual(task.pwf_amc_approval, 'approved')
        self.assertEqual(task.pwf_amc_approved_by_id, self.proj_pm)

    def test_approve_working_task_keeps_stage(self):
        """Approving (PM or Team Lead) a Working-stage task leaves its stage unchanged."""
        by_pm = self._task(stage=self.working, name='PWF approval Working task PM')
        by_tl = self._task(stage=self.working, name='PWF approval Working task TL')
        self._as(by_pm, self.proj_pm).action_pwf_amc_approve()
        self._as(by_tl, self.tl).action_pwf_amc_approve()
        for task, user in ((by_pm, self.proj_pm), (by_tl, self.tl)):
            self.assertEqual(task.stage_id, self.working)
            self.assertEqual(task.pwf_amc_approval, 'approved')
            self.assertEqual(task.pwf_amc_approved_by_id, user)
            self.assertTrue(task.pwf_amc_approved_on)
            self.assertTrue(any('approved' in (m.body or '') for m in task.message_ids))
        # Rejecting a Working-stage task does not move it either.
        open_task = self._task(stage=self.working, name='PWF approval Working task rej')
        self._reject(open_task, self.proj_pm, 'Not ready yet')
        self.assertEqual(open_task.stage_id, self.working)
        self.assertEqual(open_task.pwf_amc_approval, 'rejected')

    def test_bulk_approve_mixed_stages(self):
        """A bulk selection mixing completed and open tasks is approved as a whole."""
        done = self._task(name='PWF approval Done task')
        open_ = self._task(stage=self.working, name='PWF approval Open task')
        tasks = done | open_
        action = self._as(tasks, self.coord).action_pwf_amc_approve()
        self.assertIn('2 task(s) approved', action['params']['message'])
        self.assertEqual(set(tasks.mapped('pwf_amc_approval')), {'approved'})
        self.assertEqual(done.stage_id, self.completed)
        self.assertEqual(open_.stage_id, self.working)

    def test_refuse_non_approver(self):
        task = self._task()
        self.assertFalse(self._as(task, self.dev).pwf_amc_can_approve)
        with self.assertRaises(AccessError) as cm:
            self._as(task, self.dev).action_pwf_amc_approve()
        msg = str(cm.exception)
        self.assertIn('a Team Lead', msg)
        self.assertNotIn('Not allowed on', msg)
        self.assertNotIn(task.name, msg)
        with self.assertRaises(AccessError):
            self._as(task, self.dev).action_pwf_amc_reject()
        # Direct write (form / list multi-edit / RPC) obeys the same rule.
        with self.assertRaises(AccessError):
            self._as(task, self.dev).write({'pwf_amc_approval': 'approved'})
        self.assertFalse(task.pwf_amc_approval)

    def test_stamps_not_writable(self):
        task = self._task()
        with self.assertRaises(AccessError):
            self._as(task, self.admin).write({'pwf_amc_approved_by_id': self.dev.id})

    def test_direct_write_stamps_real_user(self):
        task = self._task()
        self._as(task, self.admin).write({'pwf_amc_approval': 'approved'})
        self.assertEqual(task.pwf_amc_approved_by_id, self.admin)
        self._as(task, self.admin).write({'pwf_amc_approval': False})
        self.assertFalse(task.pwf_amc_approved_by_id)
        self.assertFalse(task.pwf_amc_approved_on)

    # ------------------------------------------------------------------
    # approvers
    # ------------------------------------------------------------------
    def test_project_pm_only_on_own_project(self):
        own, other = self._task(), self._task(project=self.amc_other)
        self._as(own, self.proj_pm).action_pwf_amc_approve()
        self.assertEqual(own.pwf_amc_approval, 'approved')
        with self.assertRaises(AccessError):
            self._as(other, self.proj_pm).action_pwf_amc_approve()

    def test_pm_job_approves_any_project(self):
        tasks = self._task() | self._task(project=self.amc_other)
        self._as(tasks, self.coord).action_pwf_amc_approve()
        self.assertEqual(set(tasks.mapped('pwf_amc_approval')), {'approved'})

    def test_team_lead_job_approves_any_project(self):
        tasks = self._task() | self._task(project=self.amc_other)
        self.assertTrue(all(self._as(tasks, self.tl).mapped('pwf_amc_can_approve')))
        self._as(tasks, self.tl).action_pwf_amc_approve()
        self.assertEqual(set(tasks.mapped('pwf_amc_approval')), {'approved'})
        self.assertEqual(tasks.mapped('pwf_amc_approved_by_id'), self.tl)

    def test_admin_approves(self):
        task = self._task(project=self.amc_other)
        self.assertTrue(self._as(task, self.admin).pwf_amc_can_approve)
        self._as(task, self.admin).action_pwf_amc_approve()
        self.assertEqual(task.pwf_amc_approved_by_id, self.admin)

    # ------------------------------------------------------------------
    # reject / reset
    # ------------------------------------------------------------------
    def _reject(self, tasks, user, reason):
        action = self._as(tasks, user).action_pwf_amc_reject()
        self.assertEqual(action['res_model'], 'ft.pms.amc.reject.wizard')
        wizard = self.env['ft.pms.amc.reject.wizard'].with_user(user).with_context(
            **action['context']).create({'reason': reason})
        return wizard.action_confirm()

    def test_reject_needs_reason(self):
        task = self._task()
        with self.assertRaises(UserError):
            self._as(task, self.proj_pm).write({'pwf_amc_approval': 'rejected'})
        with self.assertRaises(UserError):  # ValidationError is a UserError
            self._reject(task, self.proj_pm, '   ')
        self.assertFalse(task.pwf_amc_approval)
        self._reject(task, self.proj_pm, 'Fix the report header')
        self.assertEqual(task.pwf_amc_approval, 'rejected')
        self.assertEqual(task.pwf_amc_rejection_reason, 'Fix the report header')
        self.assertEqual(task.pwf_amc_approved_by_id, self.proj_pm)

    def test_reject_bulk(self):
        tasks = self._task(name='PWF approval test task A') | self._task(name='PWF approval test task B')
        self._reject(tasks, self.coord, 'Out of scope')
        self.assertEqual(set(tasks.mapped('pwf_amc_approval')), {'rejected'})
        self.assertEqual(set(tasks.mapped('pwf_amc_rejection_reason')), {'Out of scope'})

    def test_reset(self):
        task = self._task()
        self._as(task, self.proj_pm).action_pwf_amc_approve()
        action = self._as(task, self.proj_pm).action_pwf_amc_reset()
        self.assertIn('1 task(s) reset', action['params']['message'])
        self.assertFalse(task.pwf_amc_approval)
        self.assertFalse(task.pwf_amc_approved_by_id)
        self.assertFalse(task.pwf_amc_approved_on)
        with self.assertRaises(AccessError):
            self._as(task, self.dev).action_pwf_amc_reset()

    # ------------------------------------------------------------------
    # all-or-nothing
    # ------------------------------------------------------------------
    def test_mixed_bulk_is_all_or_nothing(self):
        good = self._task(name='PWF approval Good task')
        no_project = self._task_without_project(name='PWF approval Orphan task')
        with self.assertRaisesRegex(UserError, 'Orphan'):
            self._as(good | no_project, self.coord).action_pwf_amc_approve()
        other = self._task(project=self.amc_other, name='PWF approval Other task')
        with self.assertRaises(AccessError) as cm:
            self._as(good | other, self.proj_pm).action_pwf_amc_approve()
        self.assertNotIn('Other', str(cm.exception))
        self.assertFalse(good.pwf_amc_approval)

    # ------------------------------------------------------------------
    # reopen / search
    # ------------------------------------------------------------------
    def test_stage_move_keeps_approval(self):
        """Moving the task to another stage never touches its approval."""
        task = self._task()
        self._as(task, self.proj_pm).action_pwf_amc_approve()
        task.write({'stage_id': self.working.id})
        self.assertEqual(task.pwf_amc_approval, 'approved')
        self.assertEqual(task.pwf_amc_approved_by_id, self.proj_pm)
        task.write({'stage_id': self.completed.id})
        self.assertEqual(task.pwf_amc_approval, 'approved')

    def test_search_is_completed(self):
        done, open_ = self._task(), self._task(stage=self.working)
        Task = self.env['project.task']
        ids = (done | open_).ids
        self.assertEqual(
            Task.search([('id', 'in', ids), ('pwf_amc_is_completed', '=', True)]), done)
        self.assertEqual(
            Task.search([('id', 'in', ids), ('pwf_amc_is_completed', '=', False)]), open_)
        self.assertEqual(
            Task.search([('id', 'in', ids), ('pwf_amc_is_completed', '!=', True)]), open_)
