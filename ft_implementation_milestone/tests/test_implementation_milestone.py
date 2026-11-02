# -*- coding: utf-8 -*-
"""Implementation payment milestones: the flat Milestone Templates added to
every new Implementation project at 0%, the 100% gate on KICKOFF -> DISC, the plan lock after KICKOFF and the Milestone
Change Request flow.

Fixtures are created as superuser (TransactionCase env is su) like the
sibling PMS suites: bt_project_customization only lets administrators create
projects and wants every lifecycle date, and the workflow gates are skipped
under su. The moves and edits under test run as a Project Manager (by job
position, the right bt_project_customization checks for a stage change) or
as a Date Extension Approver, so the gates and the lock apply.
"""
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

STANDARD_MILESTONES = [
    'Advance', 'BRD Approval', 'After Sandbox Review', 'Before UAT',
    'After UAT', 'Before First User Onboarding', 'Final Project Handover',
]

APPROVER = 'project_date_extension.group_project_date_extension_approver'
PROJECT_WRITER = 'base.group_user,project.group_project_manager'


@tagged('post_install', '-at_install')
class TestImplementationMilestone(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        ref = cls.env.ref
        cls.kickoff = ref('ft_project_stage_dates.stage_kickoff')
        cls.disc = ref('ft_project_lifecycle.stage_disc')
        cls.dev = ref('ft_project_lifecycle.stage_dev')

        Job = cls.env['hr.job']
        cls.job_pm = (Job.search([('name', '=ilike', 'Project Manager')], limit=1)
                      or Job.create({'name': 'Project Manager'}))
        # A Project Manager (job position + project admin group): may move
        # stages, no approver rights -> gates and lock apply to them.
        cls.pm = new_test_user(cls.env, 'fim_pm', groups=PROJECT_WRITER)
        # A Date Extension Approver: bypasses the lock, decides requests.
        cls.approver = new_test_user(
            cls.env, 'fim_approver', groups=PROJECT_WRITER + ',' + APPROVER)
        Employee = cls.env['hr.employee']
        for user in (cls.pm, cls.approver):
            Employee.create({'name': user.name, 'user_id': user.id,
                             'job_id': cls.job_pm.id})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'FIM Customer', 'email': 'fim.customer@example.com'})
        cls.Milestone = cls.env['project.custom.milestone']
        cls.Request = cls.env['ft.milestone.change.request']
        cls.Template = cls.env['ft.milestone.template']
        # The post_install DB may carry extra templates: the tests look at
        # the standard seven by name, and at the count of ACTIVE templates.
        cls.standard = cls.Template.search([('name', 'in', STANDARD_MILESTONES)])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_project(self, percentages=(30, 20, 30, 20), stage=None):
        """Implementation project (superuser: no gates) homed on KICKOFF,
        with one custom milestone per percentage. ``percentages=None``: no
        milestone of its own, so the project starts with the Milestone
        Templates at 0% (what a PM gets from the creation form)."""
        today = fields.Date.today()
        vals = {
            'name': 'FIM Project',
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
            'module_ids': [Command.create({'name': 'FIM Module'})],
        }
        if percentages is not None:
            vals['custom_milestone_ids'] = [
                Command.create({'name': 'Milestone %d' % index, 'percentage': pct})
                for index, pct in enumerate(percentages, 1)]
        if stage is not None:
            vals['stage_id'] = stage.id
        return self.env['project.project'].create(vals)

    def _sql_set_stage(self, project, stage):
        """Place a project on a stage behind the ORM's back: reaching DEV
        through write() runs the Discovery document gates, which these
        tests are not about."""
        self.env.cr.execute(
            'UPDATE project_project SET stage_id = %s WHERE id = %s',
            (stage.id, project.id))
        project.invalidate_recordset()

    def _move(self, project, stage, user=None):
        project.with_user(user or self.pm).write({'stage_id': stage.id})

    def _total(self, project):
        return sum(project.custom_milestone_ids.mapped('percentage'))

    # ------------------------------------------------------------------
    # templates (flat: one record per milestone, no percentage)
    # ------------------------------------------------------------------
    def test_templates_are_flat_milestones(self):
        self.assertEqual(len(self.standard), 7)
        self.assertEqual(
            self.standard.sorted('sequence').mapped('name'), STANDARD_MILESTONES)
        self.assertNotIn('percentage', self.Template._fields)
        self.assertNotIn('line_ids', self.Template._fields)
        self.assertNotIn('ft.milestone.template.line', self.env)
        self.assertNotIn('ft.milestone.template.apply', self.env)
        # One template per name.
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'):
            with self.env.cr.savepoint():
                self.Template.create({'name': 'Advance'})
        copy = self.standard[0].copy()
        self.assertEqual(copy.name, 'Advance (copy)')
        # The milestone a template produces: 0%, no amount, no date.
        self.assertEqual(self.standard[0]._ft_milestone_vals(), {
            'name': 'Advance',
            'description': 'Advance payment on project kick-off',
            'percentage': 0.0, 'amount': 0.0, 'status': 'not_started',
        })

    def test_new_project_starts_with_template_milestones(self):
        project = self._make_project(percentages=None)
        self.assertEqual(project.stage_id, self.kickoff)
        milestones = project.custom_milestone_ids.sorted('id')
        active = self.Template.search([])
        self.assertEqual(milestones.mapped('name'), active.mapped('name'))
        self.assertIn('Advance', milestones.mapped('name'))
        self.assertIn('Final Project Handover', milestones.mapped('name'))
        self.assertEqual(set(milestones.mapped('percentage')), {0.0})
        self.assertEqual(set(milestones.mapped('amount')), {0.0})
        self.assertEqual(set(milestones.mapped('status')), {'not_started'})
        self.assertFalse(any(milestones.mapped('due_date')))
        self.assertEqual(milestones.filtered(lambda m: m.name == 'Advance').description,
                         'Advance payment on project kick-off')
        self.assertEqual(self._total(project), 0)
        self.assertFalse(project.ft_milestone_plan_ok)
        # The 100% rule now applies: KICKOFF -> DISC is refused until the
        # PM has entered the agreed percentages (KICKOFF is unlocked).
        with self.assertRaises(UserError) as ctx:
            self._move(project, self.disc)
        self.assertIn('100%', str(ctx.exception))
        self.assertEqual(project.stage_id, self.kickoff)
        shares = dict(zip(STANDARD_MILESTONES, (20, 15, 15, 10, 15, 10, 15)))
        project.with_user(self.pm).write({'custom_milestone_ids': [
            Command.update(m.id, {'percentage': shares.get(m.name, 0)})
            for m in milestones]})
        self.assertEqual(self._total(project), 100)
        self.assertTrue(project.ft_milestone_plan_ok)
        self._move(project, self.disc)
        self.assertEqual(project.stage_id, self.disc)

    def test_new_project_with_its_own_plan_keeps_it(self):
        """A project created with milestones of its own (import, RPC, a plan
        typed in the creation form) is left as entered."""
        project = self._make_project((100,))
        self.assertEqual(project.custom_milestone_ids.mapped('name'), ['Milestone 1'])
        self.assertEqual(self._total(project), 100)
        # The context key skips the templates for a blank project too.
        blank = self.env['project.project'].with_context(
            ft_skip_template_milestones=True).create({
                'name': 'FIM Blank', 'ft_project_type': 'implementation',
                'partner_id': self.customer.id, 'privacy_visibility': 'employees',
                'milestone_ids': [Command.create({'name': 'Go Live'})],
            })
        self.assertFalse(blank.custom_milestone_ids)

    def test_archived_template_is_not_added(self):
        self.standard.filtered(lambda t: t.name == 'Advance').write({'active': False})
        project = self._make_project(percentages=None)
        names = project.custom_milestone_ids.mapped('name')
        self.assertNotIn('Advance', names)
        self.assertIn('BRD Approval', names)

    def test_conversion_to_implementation_adds_template_milestones(self):
        general = self.env['project.project'].create({
            'name': 'FIM General', 'ft_project_type': 'general',
            'partner_id': self.customer.id, 'privacy_visibility': 'employees',
        })
        self.assertFalse(general.custom_milestone_ids)
        general.write({'ft_project_type': 'implementation'})
        self.assertEqual(general.stage_id, self.kickoff)
        self.assertEqual(general.custom_milestone_ids.sorted('id').mapped('name'),
                         self.Template.search([]).mapped('name'))
        self.assertEqual(self._total(general), 0)
        # A project converted WITH a payment milestone already keeps it.
        other = self.env['project.project'].create({
            'name': 'FIM General 2', 'ft_project_type': 'general',
            'partner_id': self.customer.id, 'privacy_visibility': 'employees',
            'custom_milestone_ids': [Command.create({'name': 'Own', 'percentage': 100})],
        })
        other.write({'ft_project_type': 'implementation'})
        self.assertEqual(other.custom_milestone_ids.mapped('name'), ['Own'])

    # ------------------------------------------------------------------
    # gate
    # ------------------------------------------------------------------
    def test_gate_blocks_kickoff_to_disc_until_100(self):
        project = self._make_project((30, 20, 20))   # 70%
        self.assertFalse(project.ft_milestone_plan_ok)
        self.assertEqual(project.ft_milestone_percentage_total, 70)
        # The form's checklist already names it.
        self.assertIn('currently 70%', project.pwf_next_stage_missing or '')
        with self.assertRaises(UserError) as caught:
            self._move(project, self.disc)
        message = str(caught.exception)
        self.assertIn("cannot be moved to 'DISC'", message)
        self.assertIn(
            "Payment Milestones: the milestone percentages must add up to "
            "100% (currently 70%). Adjust them in the Milestones tab.", message)
        self.assertEqual(project.stage_id, self.kickoff)

        # A plan completed in the SAME save as the move counts: the new line
        # comes in as a (0, 0, vals) command and the stage is judged against
        # KICKOFF, the stage the project is leaving.
        project.with_user(self.pm).write({
            'stage_id': self.disc.id,
            'custom_milestone_ids': [
                Command.create({'name': 'Go-Live', 'percentage': 30})],
        })
        self.assertEqual(project.stage_id, self.disc)
        self.assertEqual(self._total(project), 100)

    def test_gate_passes_at_100_and_applies_to_later_moves(self):
        project = self._make_project()   # 100%
        self.assertTrue(project.ft_milestone_plan_ok)
        self.assertFalse(project.pwf_next_stage_missing)
        self._move(project, self.disc)
        self.assertEqual(project.stage_id, self.disc)
        # Later forward moves are gated too: an approver may break the plan
        # directly (approver right), after which DISC -> DEV lists it.
        project.custom_milestone_ids[0].with_user(self.approver).write({'percentage': 10})
        self.assertEqual(self._total(project), 80)
        self.assertIn('currently 80%', project.pwf_next_stage_missing or '')
        with self.assertRaises(UserError) as caught:
            self._move(project, self.dev)
        self.assertIn('currently 80%', str(caught.exception))
        # Backward moves are never gated.
        self._move(project, self.kickoff)
        self.assertEqual(project.stage_id, self.kickoff)
        # Over 100% is not a plan either.
        project.custom_milestone_ids[0].with_user(self.pm).write({'percentage': 50})
        self.assertEqual(self._total(project), 120)
        with self.assertRaises(UserError) as caught:
            self._move(project, self.disc)
        self.assertIn('currently 120%', str(caught.exception))

    def test_gate_ignores_non_implementation_projects(self):
        project = self._make_project((10,))
        project.sudo().write({'ft_project_type': 'general'})
        self.assertFalse(project.pwf_next_stage_missing)
        self.assertFalse(project.ft_milestone_plan_locked)

    def test_percentage_range_constraint(self):
        project = self._make_project()
        with self.assertRaises(ValidationError):
            project.custom_milestone_ids[0].percentage = 101
        with self.assertRaises(ValidationError):
            project.custom_milestone_ids[0].percentage = -1

    # ------------------------------------------------------------------
    # lock
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # customer e-mail on completion
    # ------------------------------------------------------------------
    def test_completion_email_to_customer(self):
        project = self._make_project((100,))
        milestone = project.custom_milestone_ids
        Mail = self.env['mail.mail']
        before = Mail.search([])
        milestone.write({'status': 'completed'})
        mails = Mail.search([]) - before
        self.assertEqual(len(mails), 1)
        self.assertIn(self.customer.email, mails.email_to)
        self.assertIn('Milestone 1', mails.subject)
        self.assertIn('FIM Project', mails.subject)
        self.assertEqual(mails.state, 'outgoing', 'queued, not force-sent')
        self.assertTrue(any('e-mail sent to' in (m.body or '')
                            for m in project.message_ids))
        # Already completed: no second e-mail on a re-save of the status.
        milestone.write({'status': 'completed'})
        self.assertEqual(len(Mail.search([]) - before), 1)
        # Switch off: nothing. Customer without e-mail: a note, no mail.
        other = self._make_project((100,))
        other.ft_milestone_completion_email = False
        other.custom_milestone_ids.write({'status': 'completed'})
        self.assertEqual(len(Mail.search([]) - before), 1)
        no_mail = self._make_project((100,))
        no_mail.partner_id = self.env['res.partner'].create({'name': 'FIM No Mail'})
        no_mail.custom_milestone_ids.write({'status': 'completed'})
        self.assertEqual(len(Mail.search([]) - before), 1)
        self.assertTrue(any('no e-mail address' in (m.body or '')
                            for m in no_mail.message_ids))
        # Not an Implementation project: nothing.
        general = self.env['project.project'].create({
            'name': 'FIM General Mail', 'ft_project_type': 'general',
            'partner_id': self.customer.id, 'privacy_visibility': 'employees',
            'custom_milestone_ids': [Command.create({'name': 'G', 'percentage': 100})],
        })
        general.custom_milestone_ids.write({'status': 'completed'})
        self.assertEqual(len(Mail.search([]) - before), 1)

    def test_lock_after_kickoff(self):
        project = self._make_project()
        milestone = project.custom_milestone_ids[0]
        # In KICKOFF the plan is free for everybody.
        self.assertFalse(project.ft_milestone_plan_locked)
        milestone.with_user(self.pm).write({'percentage': 25, 'name': 'Advance'})
        milestone.with_user(self.pm).write({'percentage': 30})
        self.assertFalse(milestone.with_user(self.pm).ft_milestone_plan_locked)

        self._move(project, self.disc)
        self.assertTrue(project.ft_milestone_plan_locked)
        self.assertTrue(milestone.with_user(self.pm).ft_milestone_plan_locked)
        self.assertFalse(milestone.with_user(self.approver).ft_milestone_plan_locked)

        for vals in ({'percentage': 25}, {'name': 'Renamed'}, {'amount': 500},
                     {'due_date': fields.Date.today()}):
            with self.assertRaises(UserError, msg=vals):
                milestone.with_user(self.pm).write(vals)
        with self.assertRaises(UserError):
            self.Milestone.with_user(self.pm).create({
                'project_id': project.id, 'name': 'Extra', 'percentage': 0})
        with self.assertRaises(UserError):
            milestone.with_user(self.pm).unlink()
        with self.assertRaises(UserError):
            project.with_user(self.pm).write({'custom_milestone_ids': [
                Command.update(milestone.id, {'percentage': 25})]})
        self.assertEqual(milestone.percentage, 30)
        self.assertEqual(milestone.name, 'Advance')

        # Delivery tracking stays open: status, paid amount, hours,
        # description. Re-stating the current value is not a change either.
        milestone.with_user(self.pm).write({
            'status': 'completed', 'paid_amount': 10, 'hours_spent': 2,
            'description': 'done', 'percentage': 30})
        self.assertEqual(milestone.status, 'completed')

        # Approvers keep their direct right (the exception handling itself
        # runs under their group / the approval context).
        milestone.with_user(self.approver).write({'percentage': 25, 'name': 'Adv'})
        self.assertEqual(milestone.percentage, 25)
        extra = self.Milestone.with_user(self.approver).create({
            'project_id': project.id, 'name': 'Extra', 'percentage': 5})
        extra.with_user(self.approver).unlink()
        self.Milestone.with_context(ft_milestone_change_approval=True).with_user(
            self.pm).create({'project_id': project.id, 'name': 'Ctx', 'percentage': 5}
        ).with_context(ft_milestone_change_approval=True).unlink()

        # Nothing of this touches other project types.
        general = self._make_project((10,))
        general.sudo().write({'ft_project_type': 'general'})
        self._sql_set_stage(general, self.dev)
        general.custom_milestone_ids[0].with_user(self.pm).write({'percentage': 50})

    def test_lock_keeps_date_extension_rule(self):
        """An approver may change a due date directly; a normal user is
        refused in KICKOFF too (project_date_extension's own rule)."""
        project = self._make_project()
        milestone = project.custom_milestone_ids[0]
        with self.assertRaises(AccessError):
            milestone.with_user(self.pm).write({'due_date': fields.Date.today()})
        milestone.with_user(self.approver).write({'due_date': fields.Date.today()})
        self.assertEqual(milestone.due_date, fields.Date.today())

    # ------------------------------------------------------------------
    # change requests
    # ------------------------------------------------------------------
    def test_change_request_flow(self):
        project = self._make_project()   # 30 / 20 / 30 / 20, 100%
        self._move(project, self.disc)
        first, second, third, fourth = project.custom_milestone_ids.sorted('id')

        # Add 10% on top of a complete plan: 110% -> approval refused.
        add = self.Request.with_user(self.pm).create({
            'project_id': project.id,
            'change_type': 'add',
            'new_name': 'Hypercare',
            'new_percentage': 10,
            'reason': 'Customer asked for a hypercare payment.',
        })
        self.assertTrue(add.name.startswith('MCR/'))
        self.assertEqual(add.state, 'draft')
        self.assertEqual(add.requester_id, self.pm)
        self.assertEqual(add.resulting_percentage_total, 110)
        with self.assertRaises(AccessError):
            add.with_user(self.pm).action_approve()      # not an approver
        with self.assertRaises(UserError):
            add.with_user(self.approver).action_approve()  # not submitted
        add.with_user(self.pm).action_submit_request()
        self.assertEqual(add.state, 'request')
        with self.assertRaises(UserError) as caught:
            add.with_user(self.approver).action_approve()
        self.assertIn('110%', str(caught.exception))
        self.assertEqual(add.state, 'request')
        self.assertEqual(len(project.custom_milestone_ids), 4)
        # Submitted: frozen for the requester, deletable by nobody.
        with self.assertRaises(UserError):
            add.with_user(self.pm).write({'new_percentage': 5})
        with self.assertRaises(UserError):
            add.with_user(self.approver).unlink()

        # Approver frees 20% directly, then an update of the first milestone
        # from 30% to 50% lands the plan on 100% and is applied.
        fourth.with_user(self.approver).write({'percentage': 0})
        self.assertEqual(self._total(project), 80)
        update = self.Request.with_user(self.pm).create({
            'project_id': project.id,
            'milestone_id': first.id,
            'change_type': 'update',
            'new_percentage': 50,
            'new_amount': 5000,
            'reason': 'Advance raised to 50%.',
        })
        # Snapshot frozen at creation; the other new values default to the
        # current ones so only the percentage and amount change.
        self.assertEqual(update.current_name, 'Milestone 1')
        self.assertEqual(update.current_percentage, 30)
        self.assertEqual(update.new_name, 'Milestone 1')
        self.assertEqual(update.resulting_percentage_total, 100)
        update.with_user(self.pm).action_submit_request()
        update.with_user(self.approver).action_approve()
        self.assertEqual(update.state, 'approved')
        self.assertEqual(update.approver_id, self.approver)
        self.assertTrue(update.decision_date)
        self.assertEqual(first.percentage, 50)
        self.assertEqual(first.amount, 5000)
        self.assertEqual(first.name, 'Milestone 1')
        self.assertEqual(self._total(project), 100)
        self.assertTrue(project.ft_milestone_plan_ok)
        self.assertEqual(update.current_percentage, 30, "history is kept")
        with self.assertRaises(UserError):
            update.with_user(self.approver).unlink()

        # Remove the 0% milestone: plan still 100%, milestone gone, request
        # keeps its snapshot.
        remove = self.Request.with_user(self.pm).create({
            'project_id': project.id,
            'milestone_id': fourth.id,
            'change_type': 'remove',
            'reason': 'No longer needed.',
        })
        remove.with_user(self.pm).action_submit_request()
        remove.with_user(self.approver)._do_approve(comment='ok')
        self.assertFalse(fourth.exists())
        self.assertEqual(remove.state, 'approved')
        self.assertEqual(remove.current_name, 'Milestone 4')
        self.assertEqual(remove.approval_comment, 'ok')
        self.assertEqual(self._total(project), 100)
        self.assertEqual(project.ft_milestone_change_request_count, 3)

        # The pending 'add' would now be 110% again -> still refused; the
        # approver rejects it with a reason (required).
        with self.assertRaises(UserError):
            add.with_user(self.approver).action_approve()
        with self.assertRaises(UserError):
            add.with_user(self.approver)._do_reject()
        wizard = self.env['ft.milestone.change.reject.wizard'].with_user(
            self.approver).create({'request_id': add.id, 'reason': 'Not in contract.'})
        wizard.action_confirm()
        self.assertEqual(add.state, 'rejected')
        self.assertEqual(add.rejection_reason, 'Not in contract.')
        self.assertEqual(add.approver_id, self.approver)
        # Rejected -> draft -> edit -> resubmit, now at 0% it keeps the plan.
        add.with_user(self.approver).action_reset_to_draft()
        add.with_user(self.pm).write({'new_percentage': 0})
        add.with_user(self.pm).action_submit_request()
        add.with_user(self.approver).action_approve()
        self.assertEqual(add.state, 'approved')
        self.assertEqual(add.milestone_id.name, 'Hypercare')
        self.assertEqual(add.milestone_id.project_id, project)
        self.assertEqual(self._total(project), 100)

        # A never-submitted draft can be deleted by its requester.
        draft = self.Request.with_user(self.pm).create({
            'project_id': project.id, 'milestone_id': second.id,
            'change_type': 'update', 'new_percentage': 20, 'reason': 'typo',
        })
        draft.with_user(self.approver).unlink()

    def test_change_request_update_with_date(self):
        """An approved update also moves the due date, through
        project_date_extension's guard (date_extension_approval context)."""
        project = self._make_project()
        self._move(project, self.disc)
        milestone = project.custom_milestone_ids[0]
        new_date = fields.Date.today() + timedelta(days=30)
        request = self.Request.with_user(self.pm).create({
            'project_id': project.id,
            'milestone_id': milestone.id,
            'change_type': 'update',
            'new_due_date': new_date,
            'reason': 'Advance moved with the kick-off.',
        })
        self.assertEqual(request.new_percentage, 30)
        request.with_user(self.pm).action_submit_request()
        request.with_user(self.approver).action_approve()
        self.assertEqual(milestone.due_date, new_date)
        self.assertEqual(milestone.percentage, 30)
        self.assertEqual(self._total(project), 100)

    def test_change_request_consistency(self):
        project = self._make_project()
        other = self._make_project()
        with self.assertRaises(ValidationError):
            self.Request.create({
                'project_id': project.id, 'change_type': 'update',
                'reason': 'no milestone'})
        with self.assertRaises(ValidationError):
            self.Request.create({
                'project_id': project.id, 'change_type': 'add',
                'reason': 'no name'})
        with self.assertRaises(ValidationError):
            self.Request.create({
                'project_id': project.id,
                'milestone_id': other.custom_milestone_ids[0].id,
                'change_type': 'update', 'reason': 'wrong project'})
        with self.assertRaises(ValidationError):
            self.Request.create({
                'project_id': project.id, 'change_type': 'add',
                'new_name': 'X', 'new_percentage': 150, 'reason': 'range'})
        # An invoiced milestone cannot be removed.
        milestone = project.custom_milestone_ids[0]
        milestone.status = 'paid'
        request = self.Request.create({
            'project_id': project.id, 'milestone_id': milestone.id,
            'change_type': 'remove', 'reason': 'paid'})
        with self.assertRaises(UserError):
            request.action_submit_request()
