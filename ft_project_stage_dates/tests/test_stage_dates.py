# -*- coding: utf-8 -*-
from datetime import timedelta

import pytz

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from ..hooks import backfill_actual_stage_dates, _local_date
from ..models.project_project import (
    EARLY_STAGE_KEYS, PL_ACTUAL_DATE_FIELDS, PL_ACTUAL_STAGE_KEYS,
)

APPROVER = 'project_date_extension.group_project_date_extension_approver'
ARCHITECT = 'ft_project_stage_dates.group_technical_architect'
# project.group_project_manager is the Project app's "Administrator" group:
# the one with write access on project.project. A plain project user only
# reads projects, so every user that edits a date in these tests carries it.
PROJECT_WRITER = 'base.group_user,project.group_project_manager'


@tagged('post_install', '-at_install')
class TestProjectStageDates(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        ref = cls.env.ref
        cls.kickoff = ref('ft_project_stage_dates.stage_kickoff')
        cls.disc = ref('ft_project_lifecycle.stage_disc')
        cls.dev = ref('ft_project_lifecycle.stage_dev')
        cls.closed = ref('ft_project_lifecycle.stage_closed')
        cls.started = ref('ft_project_lifecycle.stage_started')

        Job = cls.env['hr.job']
        cls.job_pm = (Job.search([('name', '=ilike', 'Project Manager')], limit=1)
                      or Job.create({'name': 'Project Manager'}))

        # Creates projects: bt_project_customization wants base.group_system,
        # project_date_extension wants the approver group for the dates.
        cls.admin = new_test_user(
            cls.env, 'psd_admin',
            groups=PROJECT_WRITER + ',base.group_system,' + APPROVER)
        # A Project Manager by job position (may move stages), no date rights.
        cls.pm = new_test_user(cls.env, 'psd_pm', groups=PROJECT_WRITER)
        cls.architect = new_test_user(
            cls.env, 'psd_architect', groups=PROJECT_WRITER + ',' + ARCHITECT)
        cls.approver = new_test_user(
            cls.env, 'psd_approver', groups=PROJECT_WRITER + ',' + APPROVER)
        Employee = cls.env['hr.employee']
        for user in (cls.admin, cls.pm):
            Employee.create({'name': user.name, 'user_id': user.id,
                             'job_id': cls.job_pm.id})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'PSD Customer', 'email': 'psd.customer@example.com'})

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _vals(self, stage=None, **extra):
        """Implementation project values, dates in step order (mirrors
        ft_pms_planning_workflow's _make_project)."""
        today = fields.Date.today()
        vals = {
            'name': 'PSD Project',
            'ft_project_type': 'implementation',
            'partner_id': self.customer.id,
            'user_id': self.pm.id,
            'privacy_visibility': 'employees',
            'date_start': today,
            'kick_start_meeting_date': today + timedelta(days=1),
            'brd_approval_date': today + timedelta(days=2),
            'ft_regression_date': today + timedelta(days=3),
            'sandbox_review_date': today + timedelta(days=4),
            'uat_start_date': today + timedelta(days=5),
            'pl_data_upload_date': today + timedelta(days=6),
            'ft_training_date': today + timedelta(days=7),
            'go_live_date': today + timedelta(days=8),
            'support_start_date': today + timedelta(days=9),
            'pl_support_end_date': today + timedelta(days=10),
            'date': today + timedelta(days=60),
            'module_ids': [Command.create({'name': 'PSD Module'})],
            'milestone_ids': [Command.create({'name': 'Go Live'})],
        }
        if stage is not None:
            vals['stage_id'] = stage.id
        vals.update(extra)
        return vals

    def _create(self, stage=None, user=None, **extra):
        Project = self.env['project.project']
        if user is not None:
            Project = Project.with_user(user)
        return Project.create(self._vals(stage, **extra))

    def _move(self, project, stage, user=None):
        project.with_user(user or self.admin).write({'stage_id': stage.id})

    def _actual(self, project):
        return {key: project[fname] for key, fname in PL_ACTUAL_DATE_FIELDS.items()}

    # ------------------------------------------------------------------
    # stage key
    # ------------------------------------------------------------------
    def test_kickoff_stage_key(self):
        Stage = self.env['project.project.stage']
        classify = Stage._ft_classify_stage_name
        for name in ('KICKOFF', 'Kickoff', 'Kick-off', 'Kick off',
                     'KICKOFF - Kick-off meeting', 'Kick Off / Mobilisation'):
            self.assertEqual(classify(name), 'kickoff', name)
        # The existing keys are untouched, and 'kick' alone is not a marker.
        for name, key in (('DISC', 'disc'), ('DISC - Discovery', 'disc'),
                          ('Development', 'dev'), ('DATA', 'data'),
                          ('CLOSED', 'closed'), ('Kick', False),
                          ('Kickstart', False)):
            self.assertEqual(classify(name), key, name)
        self.assertEqual(self.kickoff._ft_stage_key(), 'kickoff')
        self.assertIn('kickoff', Stage._ft_lifecycle_stage_map())
        self.assertEqual(Stage._ft_lifecycle_stage_map()['kickoff'], self.kickoff)
        # Ahead of DISC in the Implementation chain.
        chain = self.env['project.project']._pl_allowed_stages_for_type('implementation')
        self.assertEqual(chain[0], self.kickoff)
        self.assertEqual(chain[1], self.disc)

    # ------------------------------------------------------------------
    # stamping
    # ------------------------------------------------------------------
    def test_new_implementation_project_starts_in_kickoff(self):
        """No stage given: ft_project_lifecycle homes the project on the
        first Implementation stage, now KICKOFF, and its entry is stamped."""
        today = fields.Date.context_today(self.env['project.project'])
        project = self._create(user=self.admin)
        self.assertEqual(project.stage_id, self.kickoff)
        self.assertEqual(project.pl_actual_kickoff_date, today)
        for key, value in self._actual(project).items():
            if key != 'kickoff':
                self.assertFalse(value, key)
        timeline = project._pl_actual_entry_dates()
        self.assertEqual([key for key, _stage, _date in timeline],
                         list(PL_ACTUAL_STAGE_KEYS))
        self.assertEqual(timeline[0], ('kickoff', self.kickoff, today))
        self.assertEqual(timeline[1], ('disc', self.disc, False))
        self.assertEqual(project._pl_actual_date_field('disc'), 'pl_actual_disc_date')
        self.assertFalse(project._pl_actual_date_field('hold'))
        # A stage given that fits the type is kept (superuser: no gates).
        self.assertEqual(self._create(stage=self.dev).stage_id, self.dev)

    def test_entry_dates_first_entry_is_kept(self):
        today = fields.Date.context_today(self.env['project.project'])
        yesterday = today - timedelta(days=1)
        project = self._create(user=self.admin)
        self._move(project, self.disc)
        self.assertEqual(project.stage_id, self.disc)
        self.assertEqual(project.pl_actual_kickoff_date, today)
        self.assertEqual(project.pl_actual_disc_date, today)
        # Pretend DISC was entered yesterday. `project` lives in the admin's
        # (non-superuser) environment, so this must go through sudo: the
        # guard refuses it for anyone else, which is what the install
        # backfill and the stamping rely on.
        project.sudo().write({'pl_actual_disc_date': yesterday})
        self._move(project, self.kickoff)   # backward: ungated
        self._move(project, self.disc)
        self.assertEqual(project.stage_id, self.disc)
        self.assertEqual(project.pl_actual_disc_date, yesterday,
                         "moving back and forward must keep the first entry")
        self.assertEqual(project.pl_actual_kickoff_date, today)
        self.assertFalse(project.pl_actual_dev_date)
        # Entering CLOSED (superuser: gates skipped) stamps its own entry and
        # leaves the planned Closed Date, already set, alone.
        planned_close = project.date
        project.sudo().write({'stage_id': self.closed.id})
        self.assertEqual(project.pl_actual_closed_date, today)
        self.assertEqual(project.date, planned_close)

    def test_type_change_lands_in_kickoff_and_is_stamped(self):
        today = fields.Date.context_today(self.env['project.project'])
        project = self.env['project.project'].create({
            'name': 'PSD General', 'ft_project_type': 'general',
            'partner_id': self.customer.id,
        })
        self.assertEqual(project.stage_id, self.started)
        self.assertFalse(project.pl_actual_kickoff_date)
        project.write({'ft_project_type': 'implementation'})
        self.assertEqual(project.stage_id, self.kickoff)
        self.assertEqual(project.pl_actual_kickoff_date, today)

    def test_actual_dates_cannot_be_edited(self):
        project = self._create(user=self.admin)
        with self.assertRaisesRegex(UserError, 'recorded automatically'):
            project.with_user(self.admin).write(
                {'pl_actual_disc_date': fields.Date.today()})
        with self.assertRaisesRegex(UserError, 'recorded automatically'):
            project.with_user(self.approver).write(
                {'pl_actual_kickoff_date': False})
        with self.assertRaisesRegex(UserError, 'recorded automatically'):
            self._create(user=self.admin, pl_actual_dev_date=fields.Date.today())
        self.assertFalse(project.pl_actual_disc_date)
        # The form field is read-only as well.
        self.assertTrue(project._fields['pl_actual_disc_date'].readonly)
        self.assertFalse(project._fields['pl_actual_disc_date'].copy)

    # ------------------------------------------------------------------
    # who may edit the planned dates
    # ------------------------------------------------------------------
    def test_technical_architect_edits_planned_dates_in_early_stages_only(self):
        today = fields.Date.today()
        project = self._create(stage=self.disc)
        self.assertEqual(EARLY_STAGE_KEYS, ('kickoff', 'disc'))
        self.assertTrue(project._pl_in_early_stage())
        # DISC: the architect may edit directly ...
        project.with_user(self.architect).write(
            {'brd_approval_date': today + timedelta(days=3)})
        self.assertEqual(project.brd_approval_date, today + timedelta(days=3))
        self.assertTrue(project.with_user(self.architect).ft_can_edit_project_dates)
        # ... a plain Project Manager may not ...
        with self.assertRaises(AccessError):
            project.with_user(self.pm).write(
                {'brd_approval_date': today + timedelta(days=2)})
        self.assertFalse(project.with_user(self.pm).ft_can_edit_project_dates)
        # ... and the approver always may.
        project.with_user(self.approver).write(
            {'brd_approval_date': today + timedelta(days=2)})
        self.assertTrue(project.with_user(self.approver).ft_can_edit_project_dates)
        # DEV: the architect goes through a Date Extension Request like
        # everybody else; the approver keeps the direct edit.
        project.write({'stage_id': self.dev.id})
        self.assertFalse(project._pl_in_early_stage())
        with self.assertRaises(AccessError):
            project.with_user(self.architect).write(
                {'brd_approval_date': today + timedelta(days=3)})
        self.assertFalse(project.with_user(self.architect).ft_can_edit_project_dates)
        project.with_user(self.approver).write(
            {'brd_approval_date': today + timedelta(days=3)})
        self.assertEqual(project.brd_approval_date, today + timedelta(days=3))
        # Kick-off Date is protected now too (it never was: label mismatch).
        with self.assertRaises(AccessError):
            project.with_user(self.pm).write({'kick_start_meeting_date': today})
        with self.assertRaises(AccessError):
            project.with_user(self.pm).write({'date': today + timedelta(days=61)})
        # A write that touches no lifecycle date is not the architect's
        # concern at any stage.
        project.with_user(self.architect).write({'description': 'notes'})

    def test_technical_architect_not_on_other_types_or_mixed_sets(self):
        today = fields.Date.today()
        amc = self.env['project.project'].create({
            'name': 'PSD AMC', 'ft_project_type': 'amc',
            'partner_id': self.customer.id, 'date_start': today,
            'date': today + timedelta(days=30), 'privacy_visibility': 'employees',
        })
        with self.assertRaises(AccessError):
            amc.with_user(self.architect).write({'date': today + timedelta(days=31)})
        early = self._create(stage=self.disc)
        late = self._create(stage=self.dev)
        with self.assertRaises(AccessError):
            (early | late).with_user(self.architect).write(
                {'brd_approval_date': today + timedelta(days=2)})

    def test_sequenced_date_fields_include_kickoff_and_closed(self):
        Project = self.env['project.project']
        names = [name for name, _label in Project._sequenced_date_fields()]
        self.assertEqual(names[0], 'date_start')
        self.assertEqual(names[1], 'kick_start_meeting_date')
        self.assertEqual(names[2], 'brd_approval_date')
        self.assertEqual(names[-1], 'date')
        self.assertEqual(len(names), 12)
        self.assertEqual(len(set(names)), 12)
        labels = dict(Project._sequenced_date_fields())
        self.assertEqual(labels['kick_start_meeting_date'], 'Kick-off Date')
        self.assertEqual(labels['date'], 'Closed Date')

    def test_closed_date_still_stamped_for_non_approver(self):
        """ft_project_lifecycle fills the planned Closed Date (core `date`)
        on CLOSED when empty. Closed Date is a protected, sequenced date now,
        but the stamp is a system action: a Project Manager who is no Date
        Extension Approver can still close the project. AMC, so that no stage
        gate stands between the PM and CLOSED."""
        today = fields.Date.context_today(self.env['project.project'])
        project = self.env['project.project'].create({
            'name': 'PSD AMC Close', 'ft_project_type': 'amc',
            'partner_id': self.customer.id, 'date_start': today,
            'privacy_visibility': 'employees',
        })
        self.assertFalse(project.date)
        self.assertFalse(self.pm.has_group(APPROVER))
        self._move(project, self.closed, user=self.pm)
        self.assertEqual(project.stage_id, self.closed)
        self.assertEqual(project.date, today)
        # Not an Implementation project: no actual entry date.
        self.assertFalse(project.pl_actual_closed_date)

    # ------------------------------------------------------------------
    # install backfill
    # ------------------------------------------------------------------
    def test_backfill_from_stage_tracking(self):
        env = self.env
        tz = pytz.timezone(env.company.partner_id.tz or env.user.tz or 'UTC')
        project = self._create(stage=self.disc)
        project.write({'stage_id': self.dev.id})
        # Materialise the stage_id chatter tracking (normally at commit).
        env.flush_all()
        env.cr.precommit.run()
        env.cr.execute(
            "UPDATE project_project SET pl_actual_kickoff_date = NULL, "
            "pl_actual_disc_date = NULL, pl_actual_dev_date = NULL "
            "WHERE id = %s", (project.id,))
        project.invalidate_recordset()
        self.assertFalse(project.pl_actual_dev_date)
        # >= 1: the test database may hold other Implementation projects
        # with an empty actual date (the hook touches them too).
        self.assertGreaterEqual(backfill_actual_stage_dates(env), 1)
        now_local = _local_date(fields.Datetime.now(), tz)
        self.assertEqual(project.pl_actual_dev_date, now_local)     # tracking
        self.assertEqual(project.pl_actual_disc_date,
                         _local_date(project.create_date, tz))       # first stage
        self.assertFalse(project.pl_actual_kickoff_date)             # never passed
        # Idempotent: a second run changes nothing and touches no project.
        project.write({'pl_actual_disc_date': now_local - timedelta(days=5)})
        self.assertEqual(backfill_actual_stage_dates(env), 0)
        self.assertEqual(project.pl_actual_disc_date, now_local - timedelta(days=5))
