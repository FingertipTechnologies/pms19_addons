# -*- coding: utf-8 -*-
import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged

FINANCE = '(?i)finance'
DASH = '\u2013'


@tagged('post_install', '-at_install')
class TestPmsStageWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        ref = cls.env.ref
        cls.stage = {
            key: ref('ft_project_lifecycle.stage_%s' % key)
            for key in ('disc', 'dev', 'reg', 'srv', 'uat', 'data', 'tra', 'support', 'closed')
        }

        Job = cls.env['hr.job']

        def job(name):
            return Job.search([('name', '=ilike', name)], limit=1) or Job.create({'name': name})

        cls.job_pm = job('Project Manager')
        cls.job_tester = job('Software Tester')
        cls.job_pc = job('Project Coordinator')
        cls.job_dev = job('Software Developer')
        cls.job_fin = job('Accountant')

        cls.admin = new_test_user(
            cls.env, 'pwf_admin',
            groups='base.group_user,base.group_system,project.group_project_manager')
        cls.pm = new_test_user(
            cls.env, 'pwf_pm', groups='base.group_user,project.group_project_manager')
        cls.qa = new_test_user(
            cls.env, 'pwf_qa', groups='base.group_user,project.group_project_user')
        cls.pc = new_test_user(
            cls.env, 'pwf_pc', groups='base.group_user,project.group_project_user')
        cls.dev = new_test_user(
            cls.env, 'pwf_dev', groups='base.group_user,project.group_project_user')
        # Finance: project *user* only (no project write right), so the
        # finance-only write elevation is exercised too.
        cls.finance = new_test_user(
            cls.env, 'pwf_finance',
            groups='base.group_user,project.group_project_user,'
                   'ft_pms_planning_workflow.group_pms_finance')
        Employee = cls.env['hr.employee']
        for user, user_job in ((cls.admin, cls.job_pm), (cls.pm, cls.job_pm),
                               (cls.qa, cls.job_tester), (cls.pc, cls.job_pc),
                               (cls.dev, cls.job_dev), (cls.finance, cls.job_fin)):
            Employee.create({'name': user.name, 'user_id': user.id, 'job_id': user_job.id})

        cls.customer = cls.env['res.partner'].create(
            {'name': 'PWF Customer', 'email': 'pwf.customer@example.com'})
        cls.ops = cls.env['res.partner'].create(
            {'name': 'PWF Ops', 'email': 'pwf.ops@example.com'})
        cls.env.company.write({
            'pwf_stage_notify_partner_ids': [Command.set(cls.ops.ids)],
            'pwf_stage_notify_email': 'pwf.info@example.com',
        })

    def setUp(self):
        super().setUp()
        self.project = self._make_project()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_project(self, stage_key='dev', user=None):
        today = fields.Date.today()
        dates = {
            'date_start': today,
            'kick_start_meeting_date': today + timedelta(days=1),
            'brd_approval_date': today + timedelta(days=2),
            'ft_regression_date': today + timedelta(days=3),
            'sandbox_review_date': today + timedelta(days=4),
            'uat_start_date': today + timedelta(days=5),
            'pl_data_upload_date': today + timedelta(days=6),
            'ft_training_date': today + timedelta(days=7),
            'support_start_date': today + timedelta(days=8),
            'go_live_date': today + timedelta(days=9),
            'date': today + timedelta(days=60),
        }
        Project = self.env['project.project']
        if user:
            Project = Project.with_user(user)
        return Project.create(dict(
            dates,
            name='PWF Project',
            ft_project_type='implementation',
            stage_id=self.stage[stage_key].id,
            partner_id=self.customer.id,
            user_id=self.pm.id,
            privacy_visibility='employees',
        ))

    def _attach(self, project, name='evidence.png'):
        return self.env['ir.attachment'].create({
            'name': name,
            'datas': base64.b64encode(b'evidence'),
            'res_model': 'project.project',
            'res_id': project.id,
        }).ids

    def _finance(self, project, *keys, value=True, user=None):
        """Finance ticks (or unticks) the payment clearance of stage ``keys``."""
        project.with_user(user or self.finance).write(
            {'pwf_fin_clear_%s' % key: value for key in keys})

    def _fill_reg(self, project):
        # Sign-off Details are optional: only Current Status / Open Issues.
        project.with_user(self.qa).write({
            'pwf_reg_current_status': '<p>All regression cases pass</p>',
            'pwf_reg_open_issues': '<p>None</p>',
        })
        project.with_user(self.qa).action_pwf_reg_signoff()

    def _fill_up_to_srv(self, project):
        project.write({'pwf_brd_signoff_attachment_ids': [Command.set(self._attach(project))]})
        self._finance(project, 'dev')
        self._fill_reg(project)

    def _move(self, project, key, user=None):
        project.with_user(user or self.pm).write({'stage_id': self.stage[key].id})

    def _mails(self, project):
        return self.env['mail.mail'].sudo().search([
            ('model', '=', 'project.project'), ('res_id', '=', project.id),
            ('subject', 'ilike', 'project now in')])

    def _ready_for_uat(self, project):
        """DEV -> SRV with evidence, sandbox review + UAT finance in place."""
        self._fill_up_to_srv(project)
        self._move(project, 'reg')
        self._move(project, 'srv')
        project.write({'pwf_sandbox_review_attachment_ids': [Command.set(self._attach(project))]})
        self._finance(project, 'uat')

    def _reach_uat(self, project):
        """DEV -> SRV with evidence, then UAT through an approved request."""
        self._ready_for_uat(project)
        project.with_user(self.pm).action_request_uat_approval()
        approval = project.pwf_approval_ids.filtered(lambda a: a.state == 'pending')
        approval.with_user(self.admin).action_approve()
        return approval

    def _reach_support(self, project):
        self._reach_uat(project)
        project.write({
            'pwf_uat_signoff_attachment_ids': [Command.set(self._attach(project))],
        })
        self._finance(project, 'data', 'support')
        self._move(project, 'data')
        self._move(project, 'tra')
        self._move(project, 'support')

    def _portal_feedback(self, project):
        return self.env['ft.feedback.response'].create({
            'partner_id': self.customer.id,
            'project_id': project.id,
            'state': 'submitted',
            'submission_token': 'pwf-portal-token-%s' % project.id,
        })

    def _retro_vals(self):
        return {
            'pwf_retro_went_well': '<p>Testing</p>',
            'pwf_retro_went_wrong': '<p>Late data</p>',
            'pwf_retro_to_correct': '<p>Plan data early</p>',
        }

    def _fill_closing(self, project, internal=True, external=True, finance=True,
                      retro=True):
        vals = {}
        if internal:
            vals['pwf_internal_feedback_attachment_ids'] = [
                Command.set(self._attach(project, 'internal.png'))]
        if external:
            vals['pwf_external_feedback_attachment_ids'] = [
                Command.set(self._attach(project, 'external.png'))]
        if retro:
            vals.update(self._retro_vals())
        if vals:
            project.write(vals)
        if finance:
            self._finance(project, 'closed')

    def _reach_closed(self, project):
        self._reach_support(project)
        self._fill_closing(project)
        self._move(project, 'closed')

    # ------------------------------------------------------------------
    # gates
    # ------------------------------------------------------------------
    def test_dev_gate(self):
        project = self._make_project('disc')
        # Neither BRD nor finance clearance: both are reported.
        with self.assertRaises(UserError) as caught:
            self._move(project, 'dev')
        message = str(caught.exception)
        stage = self.stage['dev'].name
        self.assertIn("Project '%s' cannot be moved to '%s'. Please complete the "
                      "following mandatory actions before moving the project to "
                      "'%s':\n" % (project.display_name, stage, stage), message)
        self.assertIn('1. BRD Sign-off: Upload a screenshot', message)
        self.assertIn('2. Finance Payment Clearance: Finance must confirm', message)
        # A single stage is crossed: no stage prefix on the items.
        self.assertNotIn('DEV %s' % DASH, message)
        # BRD alone is not enough.
        with self.assertRaisesRegex(UserError, FINANCE):
            project.with_user(self.pm).write({
                'stage_id': self.stage['dev'].id,
                'pwf_brd_signoff_attachment_ids': [Command.set(self._attach(project))],
            })
        self.assertEqual(project.stage_id, self.stage['disc'])
        # Finance alone is not enough either.
        self._finance(project, 'dev')
        with self.assertRaisesRegex(UserError, 'signed BRD'):
            self._move(project, 'dev')
        # evidence supplied in the same write counts
        project.with_user(self.pm).write({
            'stage_id': self.stage['dev'].id,
            'pwf_brd_signoff_attachment_ids': [Command.set(self._attach(project))],
        })
        self.assertEqual(project.stage_id, self.stage['dev'])

    def test_create_into_gated_stage_refused(self):
        """Create / copy / import straight into a gated stage is gated too."""
        with self.assertRaisesRegex(UserError, 'signed BRD'):
            self._make_project('dev', user=self.admin)

    def test_type_switch_cannot_bypass_closed_gate(self):
        with self.assertRaisesRegex(UserError, '(?i)retrospective|went well'):
            self.project.with_user(self.admin).write({
                'ft_project_type': 'general',
                'stage_id': self.stage['closed'].id,
            })

    def test_srv_gate_requires_reg_signoff(self):
        """Only the QA sign-off is required; the REG text fields are optional."""
        self._move(self.project, 'reg')
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'srv')
        message = str(caught.exception)
        self.assertIn("before moving the project to '%s':"
                      % self.stage['srv'].name, message)
        self.assertIn('1. REG Sign-off by QA', message)
        self.assertNotIn('REG Current Status', message)
        self.assertNotIn('REG Open Issues', message)
        self.assertNotIn('Sign-off Details', message)
        # QA may sign off with every REG text field empty.
        self.project.with_user(self.qa).action_pwf_reg_signoff()
        self.assertEqual(self.project.pwf_reg_signed_by_id, self.qa)
        self._move(self.project, 'srv')
        self.assertEqual(self.project.stage_id, self.stage['srv'])

    def test_srv_gate_requires_signed_by(self):
        """Text alone is not enough: QA must still sign off (by / on)."""
        self._move(self.project, 'reg')
        self.project.with_user(self.qa).write({
            'pwf_reg_current_status': '<p>All pass</p>',
            'pwf_reg_open_issues': '<p>None</p>',
        })
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'srv')
        message = str(caught.exception)
        self.assertIn('1. REG Sign-off by QA', message)
        self.assertNotIn('REG Current Status', message)

    def test_uat_gate_requires_approval(self):
        self._ready_for_uat(self.project)
        # even an administrator cannot move directly into UAT
        with self.assertRaisesRegex(UserError, 'Admin Approval'):
            self._move(self.project, 'uat', user=self.admin)
        self.project.with_user(self.pm).action_request_uat_approval()
        approval = self.project.pwf_approval_ids
        self.assertEqual(approval.state, 'pending')
        approval.with_user(self.admin).action_approve()
        self.assertEqual(self.project.stage_id, self.stage['uat'])
        self.assertEqual(approval.state, 'approved')
        self.assertEqual(approval.decided_by_id, self.admin)

    def test_forged_approval_context_refused_for_pm(self):
        self._ready_for_uat(self.project)
        self.project.with_user(self.pm).action_request_uat_approval()
        approval = self.project.pwf_approval_ids
        with self.assertRaises(UserError):
            self.project.with_user(self.pm).with_context(pwf_approval_id=approval.id).write(
                {'stage_id': self.stage['uat'].id})

    def test_post_uat_gates(self):
        self._reach_uat(self.project)
        # DATA: UAT sign-off and DATA finance clearance.
        with self.assertRaisesRegex(UserError, 'Customer UAT Sign-off / Completion E-mail'):
            self._move(self.project, 'data')
        self.project.write({'pwf_uat_signoff_attachment_ids': [Command.set(self._attach(self.project))]})
        with self.assertRaisesRegex(UserError, FINANCE):
            self._move(self.project, 'data')
        self._finance(self.project, 'data')
        self._move(self.project, 'data')
        # TRA: no finance of its own.
        self._move(self.project, 'tra')
        # SUPPORT: only the SUPPORT finance clearance (the UAT sign-off /
        # completion e-mail is one and the same evidence, already attached).
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'support')
        message = str(caught.exception)
        self.assertIn('1. Finance Payment Clearance', message)
        self.assertNotIn('2.', message)
        self.assertNotIn('UAT', message.split('\n', 1)[1])
        self.assertFalse(self.project.pwf_uat_completion_attachment_ids)
        self._finance(self.project, 'support')
        self._move(self.project, 'support')
        # CLOSED: internal + external feedback, finance, three retro fields.
        with self.assertRaisesRegex(UserError, 'Internal Feedback'):
            self._move(self.project, 'closed')
        self.project.write({
            'pwf_internal_feedback_attachment_ids': [
                Command.set(self._attach(self.project, 'internal.png'))],
            'pwf_external_feedback_attachment_ids': [
                Command.set(self._attach(self.project, 'external.png'))],
            'pwf_retro_went_wrong': '<p>Late data</p>',
            'pwf_retro_went_well': '<p>Testing</p>',
            'pwf_retro_to_correct': '<p><br></p>',  # empty Html
        })
        self._finance(self.project, 'closed')
        with self.assertRaisesRegex(
                UserError, 'Retrospective - What Needs to Be Corrected'):
            self._move(self.project, 'closed')
        self.project.write({'pwf_retro_to_correct': '<p>Plan data early</p>'})
        self._finance(self.project, 'closed', value=False)
        with self.assertRaisesRegex(UserError, FINANCE):
            self._move(self.project, 'closed')
        self._finance(self.project, 'closed')
        self._move(self.project, 'closed')
        self.assertEqual(self.project.stage_id, self.stage['closed'])
        self.assertTrue(self.project.pwf_locked)

    def test_closed_requires_external_feedback(self):
        self._reach_support(self.project)
        self._fill_closing(self.project, external=False)
        with self.assertRaisesRegex(UserError, 'External Review'):
            self._move(self.project, 'closed')
        self.assertEqual(self.project.stage_id, self.stage['support'])
        # A portal-submitted response no longer counts: the screenshot does.
        self.project.write({
            'pwf_portal_feedback_response_id': self._portal_feedback(self.project).id})
        with self.assertRaisesRegex(UserError, 'External Review'):
            self._move(self.project, 'closed')
        self.project.write({'pwf_external_feedback_attachment_ids': [
            Command.set(self._attach(self.project, 'external.png'))]})
        self._move(self.project, 'closed')
        self.assertEqual(self.project.stage_id, self.stage['closed'])

    def test_closed_requires_internal_feedback_screenshot(self):
        self._reach_support(self.project)
        self._fill_closing(self.project, internal=False)
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'closed')
        message = str(caught.exception)
        self.assertIn('1. Internal Feedback: Upload a screenshot', message)
        self.assertNotIn('2.', message)
        self.project.write({'pwf_internal_feedback_attachment_ids': [
            Command.set(self._attach(self.project, 'internal.png'))]})
        self._move(self.project, 'closed')
        self.assertEqual(self.project.stage_id, self.stage['closed'])

    def test_closed_gate_message(self):
        self._reach_support(self.project)
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'closed')
        expected = (
            "Project '%s' cannot be moved to '%s'. Please complete "
            "the following mandatory actions before closing the project:\n"
            % (self.project.display_name, self.stage['closed'].name)
        ) + (
            "1. Internal Feedback: Upload a screenshot confirming that the "
            "internal project feedback has been submitted.\n"
            "2. External Review (Partner Portal): Upload a screenshot confirming "
            "that the external review has been submitted through the Partner "
            "Portal.\n"
            "3. Finance Payment Clearance: Finance must confirm the payment "
            "clearance for this stage.\n"
            "4. Retrospective - What Went Well\n"
            "5. Retrospective - What Went Wrong\n"
            "6. Retrospective - What Needs to Be Corrected"
        )
        self.assertEqual(caught.exception.args[0], expected)

    def test_skip_requires_intermediate_gates(self):
        self.project.write({'pwf_brd_signoff_attachment_ids': [Command.set(self._attach(self.project))]})
        with self.assertRaises(UserError) as caught:
            self._move(self.project, 'data', user=self.admin)
        message = str(caught.exception)
        self.assertIn("before moving the project to '%s':"
                      % self.stage['data'].name, message)
        # Several stages crossed: every item names its stage.
        self.assertIn('1. SRV %s REG Sign-off by QA' % DASH, message)
        self.assertNotIn('REG Current Status', message)
        self.assertIn('UAT %s Sandbox Review' % DASH, message)
        self.assertIn('UAT %s Finance Payment Clearance' % DASH, message)
        self.assertIn('UAT %s Admin Approval' % DASH, message)
        self.assertIn('DATA %s Customer UAT Sign-off / Completion E-mail' % DASH, message)
        self.assertIn('DATA %s Finance Payment Clearance' % DASH, message)
        self.assertNotIn('BRD', message)
        self.assertEqual(self.project.stage_id, self.stage['dev'])

    def test_backward_move_ungated(self):
        self._fill_up_to_srv(self.project)
        self._move(self.project, 'reg')
        self._move(self.project, 'srv')
        self.project.write({'pwf_brd_signoff_attachment_ids': [Command.clear()]})
        self._finance(self.project, 'dev', value=False)
        self._move(self.project, 'dev')
        self._move(self.project, 'disc')
        self.assertEqual(self.project.stage_id, self.stage['disc'])

    # ------------------------------------------------------------------
    # finance clearance rights
    # ------------------------------------------------------------------
    def test_finance_clearance_rights(self):
        project = self.project
        for user in (self.pm, self.dev, self.qa):
            with self.assertRaises(AccessError):
                project.with_user(user).write({'pwf_fin_clear_dev': True})
        self.assertFalse(project.pwf_fin_clear_dev)
        self.assertFalse(project.with_user(self.pm).pwf_can_edit_finance)
        self.assertTrue(project.with_user(self.finance).pwf_can_edit_finance)
        # Administrators are not Finance any more.
        self.assertFalse(project.with_user(self.admin).pwf_can_edit_finance)
        with self.assertRaises(AccessError):
            project.with_user(self.admin).write({'pwf_fin_clear_dev': True})
        self.assertFalse(project.pwf_fin_clear_dev)

        # Finance (without project write access) may set it; by/on stamped.
        before = fields.Datetime.now()
        self._finance(project, 'dev')
        self.assertTrue(project.pwf_fin_clear_dev)
        self.assertEqual(project.pwf_fin_clear_dev_by_id, self.finance)
        self.assertTrue(project.pwf_fin_clear_dev_on)
        self.assertGreaterEqual(project.pwf_fin_clear_dev_on, before.replace(microsecond=0))
        # Other stages untouched.
        self.assertFalse(project.pwf_fin_clear_uat)
        self.assertFalse(project.pwf_fin_clear_uat_by_id)

        # Unticking clears the stamp; PM still cannot untick.
        with self.assertRaises(AccessError):
            project.with_user(self.pm).write({'pwf_fin_clear_dev': False})
        self._finance(project, 'dev', value=False)
        self.assertFalse(project.pwf_fin_clear_dev)
        self.assertFalse(project.pwf_fin_clear_dev_by_id)
        self.assertFalse(project.pwf_fin_clear_dev_on)

        # An administrator cannot untick a clearance either.
        self._finance(project, 'closed')
        with self.assertRaises(AccessError):
            self._finance(project, 'closed', value=False, user=self.admin)
        self.assertTrue(project.pwf_fin_clear_closed)
        self.assertEqual(project.pwf_fin_clear_closed_by_id, self.finance)
        # Internal (sudo) code still bypasses the Finance check.
        project.sudo().write({'pwf_fin_clear_support': True})
        self.assertTrue(project.pwf_fin_clear_support)

        # Finance cannot piggy-back other fields on the elevated write.
        with self.assertRaises(AccessError):
            project.with_user(self.finance).write({
                'pwf_fin_clear_uat': True, 'name': 'Renamed by finance'})

    def test_finance_grant_revoke_buttons(self):
        project = self.project
        # Finance holds no write access on the project (read-only form).
        self.assertFalse(project.with_user(self.finance).has_access('write'))
        as_finance = project.with_user(self.finance)

        before = fields.Datetime.now().replace(microsecond=0)
        as_finance.with_context(pwf_fin_key='uat').action_pwf_finance_grant()
        self.assertTrue(project.pwf_fin_clear_uat)
        self.assertEqual(project.pwf_fin_clear_uat_by_id, self.finance)
        self.assertGreaterEqual(project.pwf_fin_clear_uat_on, before)
        self.assertFalse(project.pwf_fin_clear_dev)
        note = project.message_ids.filtered(
            lambda m: 'Finance payment clearance granted for UAT by %s'
            % self.finance.name in (m.body or ''))
        self.assertEqual(len(note), 1)
        self.assertEqual(note.author_id, self.finance.partner_id)

        # Administrator and PM are refused, by both buttons.
        for user in (self.admin, self.pm):
            for method in ('action_pwf_finance_grant', 'action_pwf_finance_revoke'):
                with self.assertRaises(AccessError):
                    getattr(project.with_user(user).with_context(
                        pwf_fin_key='uat'), method)()
        self.assertTrue(project.pwf_fin_clear_uat)
        self.assertEqual(project.pwf_fin_clear_uat_by_id, self.finance)

        # The stage key is validated.
        for bad in ('srv', 'tra', False, 'pwf_fin_clear_dev'):
            with self.assertRaises(UserError):
                as_finance.with_context(pwf_fin_key=bad).action_pwf_finance_grant()
        with self.assertRaises(UserError):
            as_finance.action_pwf_finance_grant()

        # Revoke clears the flag and the stamp and leaves a note.
        as_finance.with_context(pwf_fin_key='uat').action_pwf_finance_revoke()
        self.assertFalse(project.pwf_fin_clear_uat)
        self.assertFalse(project.pwf_fin_clear_uat_by_id)
        self.assertFalse(project.pwf_fin_clear_uat_on)
        self.assertTrue(project.message_ids.filtered(
            lambda m: 'Finance payment clearance revoked for UAT by %s'
            % self.finance.name in (m.body or '')))

        # Every stage key works.
        for key in ('dev', 'uat', 'data', 'support', 'closed'):
            as_finance.with_context(pwf_fin_key=key).action_pwf_finance_grant()
            self.assertTrue(project['pwf_fin_clear_%s' % key])
            self.assertEqual(project['pwf_fin_clear_%s_by_id' % key], self.finance)

    def test_finance_button_needs_read_access(self):
        project = self.project
        project.sudo().write({'privacy_visibility': 'followers'})
        project.sudo().message_unsubscribe(partner_ids=self.finance.partner_id.ids)
        if project.with_user(self.finance).has_access('read'):
            self.skipTest('Finance user can still read the project')
        with self.assertRaises(AccessError):
            project.with_user(self.finance).with_context(
                pwf_fin_key='dev').action_pwf_finance_grant()
        self.assertFalse(project.pwf_fin_clear_dev)

    # ------------------------------------------------------------------
    # REG rights
    # ------------------------------------------------------------------
    def test_reg_fields_only_qa(self):
        with self.assertRaises(AccessError):
            self.project.with_user(self.pm).write({'pwf_reg_current_status': '<p>x</p>'})
        with self.assertRaises(AccessError):
            self.project.with_user(self.dev).write({'pwf_reg_current_status': '<p>x</p>'})
        with self.assertRaises(AccessError):
            self.project.with_user(self.pm).action_pwf_reg_signoff()
        self.assertFalse(self.project.with_user(self.pm).pwf_can_edit_reg)
        self.assertTrue(self.project.with_user(self.qa).pwf_can_edit_reg)
        self._fill_reg(self.project)
        self.assertEqual(self.project.pwf_reg_signed_by_id, self.qa)
        self.project.with_user(self.admin).write({'pwf_reg_open_issues': '<p>One minor</p>'})

    # ------------------------------------------------------------------
    # approvals
    # ------------------------------------------------------------------
    def _ready_for_uat_request(self):
        self._ready_for_uat(self.project)
        self.project.with_user(self.pm).action_request_uat_approval()
        return self.project.pwf_approval_ids

    def test_request_checks_prerequisites(self):
        self._fill_up_to_srv(self.project)
        self._move(self.project, 'reg')
        self._move(self.project, 'srv')
        with self.assertRaisesRegex(UserError, 'Sandbox Review'):
            self.project.with_user(self.pm).action_request_uat_approval()
        self.project.write({'pwf_sandbox_review_attachment_ids': [Command.set(self._attach(self.project))]})
        with self.assertRaisesRegex(UserError, FINANCE):
            self.project.with_user(self.pm).action_request_uat_approval()
        with self.assertRaises(AccessError):
            self.project.with_user(self.dev).action_request_uat_approval()

    def test_approve_rechecks_prerequisites(self):
        approval = self._ready_for_uat_request()
        self.project.write({'pwf_sandbox_review_attachment_ids': [Command.clear()]})
        with self.assertRaisesRegex(UserError, 'Sandbox Review'):
            approval.with_user(self.admin).action_approve()
        self.assertEqual(approval.state, 'pending')
        self.assertEqual(self.project.stage_id, self.stage['srv'])

    def test_approve_rechecks_finance(self):
        approval = self._ready_for_uat_request()
        # Finance withdraws the UAT clearance after the request was raised.
        self._finance(self.project, 'uat', value=False)
        before = len(self._mails(self.project))
        with self.assertRaisesRegex(UserError, FINANCE):
            approval.with_user(self.admin).action_approve()
        self.assertEqual(approval.state, 'pending')
        self.assertEqual(self.project.stage_id, self.stage['srv'])
        self.assertEqual(len(self._mails(self.project)), before)
        self._finance(self.project, 'uat')
        approval.with_user(self.admin).action_approve()
        self.assertEqual(self.project.stage_id, self.stage['uat'])

    def test_stale_approval_refused(self):
        approval = self._ready_for_uat_request()
        self._move(self.project, 'reg')
        with self.assertRaisesRegex(UserError, 'out of date'):
            approval.with_user(self.admin).action_approve()
        self.assertEqual(approval.state, 'pending')

    def test_only_admin_decides(self):
        approval = self._ready_for_uat_request()
        with self.assertRaises(AccessError):
            approval.with_user(self.pm).action_approve()
        with self.assertRaises(AccessError):
            approval.with_user(self.pm)._pwf_do_reject('no')
        with self.assertRaises(AccessError):
            approval.with_user(self.pm).write({'state': 'approved'})

    def test_reject_requires_reason(self):
        approval = self._ready_for_uat_request()
        with self.assertRaises(UserError):
            approval.with_user(self.admin)._pwf_do_reject('   ')
        blank = self.env['ft.pms.stage.approval.reject.wizard'].with_user(self.admin).create({
            'approval_ids': [Command.set(approval.ids)],
            'reason': '  ',
        })
        with self.assertRaises(UserError):
            blank.action_confirm()
        self.assertEqual(approval.state, 'pending')
        wizard = self.env['ft.pms.stage.approval.reject.wizard'].with_user(self.admin).create({
            'approval_ids': [Command.set(approval.ids)],
            'reason': 'Sandbox not reviewed by client',
        })
        wizard.action_confirm()
        self.assertEqual(approval.state, 'rejected')
        self.assertEqual(approval.rejection_reason, 'Sandbox not reviewed by client')
        self.assertEqual(self.project.stage_id, self.stage['srv'])

    def test_rejection_keeps_stage_and_history(self):
        first = self._ready_for_uat_request()
        before = len(self._mails(self.project))
        first.with_user(self.admin)._pwf_do_reject('Client has not paid')
        # Stage unchanged, no stage notification, request kept as history.
        self.assertEqual(self.project.stage_id, self.stage['srv'])
        self.assertEqual(len(self._mails(self.project)), before)
        self.assertTrue(first.exists())
        self.assertEqual(first.state, 'rejected')
        self.assertEqual(first.decided_by_id, self.admin)
        # A fresh request can follow; both stay on the project.
        self.project.with_user(self.pm).action_request_uat_approval()
        self.assertEqual(len(self.project.pwf_approval_ids), 2)
        second = self.project.pwf_approval_ids - first
        self.assertEqual(second.state, 'pending')
        second.with_user(self.admin).action_approve()
        self.assertEqual(self.project.stage_id, self.stage['uat'])
        self.assertEqual(
            sorted(self.project.pwf_approval_ids.mapped('state')),
            ['approved', 'rejected'])

    def test_duplicate_pending_refused(self):
        approval = self._ready_for_uat_request()
        with self.assertRaises(UserError):
            self.project.with_user(self.pm).action_request_uat_approval()
        with self.assertRaises(ValidationError):
            self.env['ft.pms.stage.approval'].create({
                'project_id': self.project.id,
                'from_stage_id': self.stage['srv'].id,
                'target_stage_id': self.stage['uat'].id,
            })
        approval.with_user(self.pm).action_cancel()
        self.assertEqual(approval.state, 'cancelled')
        self.project.with_user(self.pm).action_request_uat_approval()

    def test_approve_twice_refused(self):
        approval = self._ready_for_uat_request()
        approval.with_user(self.admin).action_approve()
        with self.assertRaisesRegex(UserError, 'already'):
            approval.with_user(self.admin).action_approve()

    # ------------------------------------------------------------------
    # notifications
    # ------------------------------------------------------------------
    def test_notification_once_per_transition(self):
        self.env.company.pwf_stage_notify_email = 'PWF.OPS@example.com, pwf.info@example.com'
        self._move(self.project, 'reg')
        mails = self._mails(self.project)
        self.assertEqual(len(mails), 1)
        # customer + Project Manager + Settings contacts
        self.assertEqual(mails.recipient_ids,
                         self.customer | self.pm.partner_id | self.ops)
        # info address equal to a partner's e-mail (case-insensitive) is skipped
        self.assertEqual(mails.email_to, 'pwf.info@example.com')
        self.assertIn('%s: project now in %s stage' % (
            self.project.name, self.stage['reg'].name), mails.subject)
        # body: previous / new / next stage labels, who moved it, the PM
        body = mails.body_html or ''
        self.assertIn('is now in the', body)
        self.assertIn('DEV %s Development' % DASH, body)
        self.assertIn('REG %s Regression' % DASH, body)
        self.assertIn('Next stage', body)
        self.assertIn('SRV %s Sandbox Review' % DASH, body)
        self.assertIn(self.pm.name, body)
        self.assertIn(self.customer.name, body)

        # no change -> nothing
        self._move(self.project, 'reg')
        self.assertEqual(len(self._mails(self.project)), 1)
        # failure -> nothing
        with self.assertRaises(UserError):
            self._move(self.project, 'srv')
        self.assertEqual(len(self._mails(self.project)), 1)
        # unrelated write -> nothing
        self.project.with_user(self.pm).write({'description': '<p>x</p>'})
        self.assertEqual(len(self._mails(self.project)), 1)
        # finance clearance alone -> nothing
        self._finance(self.project, 'uat')
        self.assertEqual(len(self._mails(self.project)), 1)
        # next successful transition -> exactly one more, with its own names
        self._fill_reg(self.project)
        self._move(self.project, 'srv')
        mails = self._mails(self.project)
        self.assertEqual(len(mails), 2)
        latest = mails.sorted('id')[-1]
        self.assertIn(self.stage['reg'].name, latest.body_html or '')
        self.assertIn(self.stage['srv'].name, latest.body_html or '')

    def test_notification_recipients_include_pm(self):
        partners, emails = self.project._pwf_stage_notify_recipients()
        self.assertIn(self.pm.partner_id, partners)
        self.assertEqual(partners, self.customer | self.pm.partner_id | self.ops)
        self.assertEqual(emails, ['pwf.info@example.com'])
        # PM sharing an address with a Settings contact is not duplicated
        self.pm.partner_id.email = 'PWF.Ops@example.com'
        partners, emails = self.project._pwf_stage_notify_recipients()
        self.assertEqual(partners, self.customer | self.pm.partner_id)

    def test_notification_body_uat_label(self):
        self._reach_uat(self.project)
        latest = self._mails(self.project).sorted('id')[-1]
        body = latest.body_html or ''
        self.assertIn('is now in the', body)
        self.assertIn('User Acceptance Testing', body)
        self.assertIn('UAT %s User Acceptance Testing' % DASH, body)
        self.assertIn('Next stage', body)
        self.assertIn('DATA %s Data Upload' % DASH, body)
        self.assertIn(self.pm.name, body)
        self.assertIn('project now in UAT stage', latest.subject)

    def test_uat_request_state(self):
        self.assertEqual(self.project.pwf_uat_request_state, 'none')
        self.assertFalse(self.project.pwf_uat_request_date)
        first = self._ready_for_uat_request()
        self.assertEqual(self.project.pwf_uat_request_state, 'pending')
        self.assertTrue(self.project.pwf_uat_request_date)
        self.assertFalse(self.project.pwf_uat_request_decided_by_id)
        first.with_user(self.admin)._pwf_do_reject('Client has not paid')
        self.assertEqual(self.project.pwf_uat_request_state, 'rejected')
        self.assertEqual(self.project.pwf_uat_request_decided_by_id, self.admin)
        self.assertEqual(self.project.pwf_uat_request_reason, 'Client has not paid')
        self.project.with_user(self.pm).action_request_uat_approval()
        self.assertEqual(self.project.pwf_uat_request_state, 'pending')
        self.assertFalse(self.project.pwf_uat_request_reason)
        second = self.project.pwf_approval_ids - first
        second.with_user(self.admin).action_approve()
        self.assertEqual(self.project.pwf_uat_request_state, 'approved')
        self.assertEqual(self.project.pwf_uat_request_decided_by_id, self.admin)
        # readable by a plain project user
        self.assertEqual(
            self.project.with_user(self.dev).pwf_uat_request_state, 'approved')

    def test_no_notification_on_pending_approval(self):
        self._ready_for_uat_request()
        before = len(self._mails(self.project))
        approval = self.project.pwf_approval_ids
        self.assertEqual(approval.state, 'pending')
        self.assertEqual(len(self._mails(self.project)), before)
        approval.with_user(self.admin).action_approve()
        self.assertEqual(len(self._mails(self.project)), before + 1)

    def test_settings_email_validation(self):
        with self.assertRaises(ValidationError):
            self.env.company.pwf_stage_notify_email = 'not-an-email'
        self.env.company.pwf_stage_notify_email = 'a@example.com; b@example.com'

    # ------------------------------------------------------------------
    # lock
    # ------------------------------------------------------------------
    def test_lock_blocks_tasks_and_timesheets(self):
        task = self.env['project.task'].create({
            'name': 'PWF existing task',
            'project_id': self.project.id,
            'task_type': 'internal_call',
        })
        with self.assertRaises(AccessError):
            self.project.with_user(self.pm).write({'pwf_locked': True})
        self.project.with_user(self.pm).write({'pl_on_hold': True})
        self.assertTrue(self.project.pwf_locked)
        with self.assertRaisesRegex(UserError, 'locked'):
            self.env['project.task'].with_user(self.pm).create({
                'name': 'PWF new task on locked project',
                'project_id': self.project.id,
                'task_type': 'internal_call',
            })
        employee = self.env['hr.employee'].search([('user_id', '=', self.dev.id)], limit=1)
        with self.assertRaisesRegex(UserError, 'locked'):
            self.env['account.analytic.line'].with_user(self.dev).create({
                'name': 'work',
                'project_id': self.project.id,
                'task_id': task.id,
                'employee_id': employee.id,
                'unit_amount': 1.0,
            })
        # PM cannot unlock; an administrator can.
        with self.assertRaises(AccessError):
            self.project.with_user(self.pm).write({'pwf_locked': False})
        self.project.with_user(self.admin).write({'pwf_locked': False})
        self.assertFalse(self.project.pwf_locked)
        self.assertTrue(self.project.pwf_manual_unlock)
        self.env['project.task'].with_user(self.pm).create({
            'name': 'PWF task after admin unlock',
            'project_id': self.project.id,
            'task_type': 'internal_call',
        })

    def test_on_hold_locks_and_unlocks(self):
        self.project.with_user(self.pm).write({'pl_on_hold': True})
        self.assertTrue(self.project.pwf_locked)
        self.project.with_user(self.pm).write({'pl_on_hold': False})
        self.assertFalse(self.project.pwf_locked)
        self.assertFalse(self.project.pwf_manual_unlock)

    def test_closed_locks_and_unlocks_on_stage_move(self):
        self._reach_closed(self.project)
        self.assertTrue(self.project.pwf_locked)
        # Moving off CLOSED (backward, ungated) lifts the automatic lock.
        self._move(self.project, 'support')
        self.assertEqual(self.project.stage_id, self.stage['support'])
        self.assertFalse(self.project.pwf_locked)

    def test_overdue_locks_and_unlocks_when_extended(self):
        project = self.project
        today = fields.Date.today()
        project.sudo().write({
            'kick_start_meeting_date': today - timedelta(days=40),
            'brd_approval_date': today - timedelta(days=30),
        })
        self._move(project, 'disc', user=self.admin)  # backward, ungated
        # BRD Approval Date passed while the project is still short of DEV
        self.assertTrue(project.ft_is_overdue)
        self.assertTrue(project.pwf_locked)
        Project = self.env['project.project']
        Project._cron_pwf_evaluate_locks()
        self.assertTrue(project.pwf_locked)
        # Old cron name kept as an alias.
        Project._cron_pwf_lock_overdue_projects()
        self.assertTrue(project.pwf_locked)
        # Extending the missed milestone date clears overdue and the lock.
        project.with_user(self.admin).write({'brd_approval_date': today + timedelta(days=2)})
        self.assertFalse(project.ft_is_overdue)
        self.assertFalse(project.pwf_locked)
        Project._cron_pwf_evaluate_locks()
        self.assertFalse(project.pwf_locked)

    def test_manual_unlock_cleared_on_stage_change(self):
        project = self.project
        project.with_user(self.pm).write({'pl_on_hold': True})
        self.assertTrue(project.pwf_locked)
        project.with_user(self.admin).write({'pwf_locked': False})
        self.assertFalse(project.pwf_locked)
        self.assertTrue(project.pwf_manual_unlock)
        # Re-evaluation (cron, date edits) honours the override.
        self.env['project.project']._cron_pwf_evaluate_locks()
        project.with_user(self.admin).write({'date': fields.Date.today() + timedelta(days=90)})
        self.assertFalse(project.pwf_locked)
        self.assertTrue(project.pwf_manual_unlock)
        # A stage change drops the override; still on hold -> locked again.
        self._move(project, 'reg')
        self.assertFalse(project.pwf_manual_unlock)
        self.assertTrue(project.pwf_locked)

    # ------------------------------------------------------------------
    # testing task
    # ------------------------------------------------------------------
    def test_testing_task_assignees(self):
        Task = self.env['project.task']
        task = Task.create({
            'name': 'PWF testing task',
            'project_id': self.project.id,
            'task_type': 'testing',
            'user_ids': [Command.set((self.qa | self.pc).ids)],
        })
        self.assertEqual(task.task_type, 'testing')
        Task.create({
            'name': 'PWF testing task unassigned',
            'project_id': self.project.id,
            'task_type': 'testing',
            'user_ids': [Command.clear()],
        })
        with self.assertRaises(ValidationError):
            Task.create({
                'name': 'PWF testing task dev',
                'project_id': self.project.id,
                'task_type': 'testing',
                'user_ids': [Command.set(self.dev.ids)],
            })
        with self.assertRaises(ValidationError):
            task.write({'user_ids': [Command.link(self.dev.id)]})

    # ------------------------------------------------------------------
    # PT-10 testing task: 40 h cap, single week
    # ------------------------------------------------------------------
    def _pt10_week(self, day):
        Week = self.env['qa_testapp.sprint']
        Week._ensure_weeks({day})
        monday = day - timedelta(days=day.weekday())
        return Week.search([('start_date', '=', monday)], limit=1)

    def _pt10_noon(self, day):
        # Noon UTC is the same calendar day in every realistic timezone.
        return fields.Datetime.to_datetime('%s 12:00:00' % day)

    def _pt10_task(self, **vals):
        monday = fields.Date.today() - timedelta(days=fields.Date.today().weekday())
        return self.env['project.task'].create(dict({
            'name': 'PWF PT-10 testing task',
            'project_id': self.project.id,
            'task_type': 'testing',
            'user_ids': [Command.set(self.qa.ids)],
            'date_deadline': self._pt10_noon(monday + timedelta(days=2)),
        }, **vals))

    def _pt10_line(self, task, hours, day=None):
        employee = self.env['hr.employee'].search([('user_id', '=', self.qa.id)], limit=1)
        return self.env['account.analytic.line'].create({
            'name': 'testing',
            'project_id': task.project_id.id,
            'task_id': task.id,
            'employee_id': employee.id,
            'unit_amount': hours,
            'date': day or task.sprint_id.start_date,
        })

    def test_pt10_testing_estimate_cap(self):
        task = self._pt10_task(estimated=40.0)
        self.assertEqual(task.estimated, 40.0)
        with self.assertRaises(ValidationError):
            task.write({'estimated': 40.5})
        with self.assertRaises(ValidationError):
            self._pt10_task(estimated=40.5)
        # Not a testing task: no cap.
        other = self._pt10_task(task_type='internal_call', estimated=60.0,
                                user_ids=[Command.clear()])
        self.assertEqual(other.estimated, 60.0)
        with self.assertRaises(ValidationError):
            other.write({'task_type': 'testing'})

    def test_pt10_testing_timesheet_cap(self):
        task = self._pt10_task(estimated=40.0)
        self._pt10_line(task, 30.0)
        line = self._pt10_line(task, 10.0)
        self.assertEqual(sum(task.timesheet_ids.mapped('unit_amount')), 40.0)
        with self.assertRaisesRegex(ValidationError, '40'):
            self._pt10_line(task, 0.5)
        with self.assertRaises(ValidationError):
            line.write({'unit_amount': 10.5})
        # Moving an entry from another task onto the full one is refused too.
        other = self._pt10_task(name='PWF PT-10 other testing task')
        spare = self._pt10_line(other, 1.0)
        with self.assertRaises(ValidationError):
            spare.write({'task_id': task.id})

    def test_pt10_testing_timesheet_outside_week_allowed(self):
        # Timesheets of a Testing task are no longer restricted to its Week.
        task = self._pt10_task()
        week = task.sprint_id
        self.assertTrue(week)
        before = self._pt10_line(task, 1.0, day=week.start_date - timedelta(days=1))
        line = self._pt10_line(task, 1.0, day=week.start_date)
        line.write({'date': week.end_date + timedelta(days=1)})
        self.assertEqual(before.task_id, task)
        # The task can move to another week despite its timesheets.
        next_week = self._pt10_week(week.end_date + timedelta(days=1))
        task.write({'sprint_id': next_week.id})
        self.assertEqual(task.sprint_id, next_week)

    def test_pt10_testing_deadline_outside_week(self):
        task = self._pt10_task()
        week = task.sprint_id
        self.assertTrue(week)
        # Without the Week re-sync (as an import or a raw write could do) the
        # deadline would leave the Week: refused.
        with self.assertRaises(ValidationError):
            task.with_context(ft_skip_week_sync=True).write({
                'date_deadline': self._pt10_noon(week.end_date + timedelta(days=3)),
            })
        next_week = self._pt10_week(week.end_date + timedelta(days=1))
        with self.assertRaises(ValidationError):
            task.with_context(ft_skip_week_sync=True).write({'sprint_id': next_week.id})
        # Normal flows keep deadline and Week together.
        task.write({'sprint_id': next_week.id})
        self.assertEqual(task.sprint_id, next_week)
        self.assertEqual(task._ft_local_date(task.date_deadline), next_week.end_date)
        task.write({'date_deadline': self._pt10_noon(week.start_date + timedelta(days=1))})
        self.assertEqual(task.sprint_id, week)

    def test_pt10_testing_week_auto_assigned(self):
        task = self._pt10_task()
        self.assertTrue(task.sprint_id)
        day = task._ft_local_date(task.date_deadline)
        self.assertTrue(task.sprint_id.start_date <= day <= task.sprint_id.end_date)
        # No deadline, no timesheets: a Week is not required yet.
        bare = self._pt10_task(date_deadline=False)
        self.assertFalse(bare.sprint_id)
        # Without the re-sync a testing task cannot carry a deadline but no Week.
        with self.assertRaises(ValidationError):
            bare.with_context(ft_skip_week_sync=True).write({
                'date_deadline': task.date_deadline})
        bare.write({'date_deadline': task.date_deadline})
        self.assertEqual(bare.sprint_id, task.sprint_id)
