# -*- coding: utf-8 -*-
"""Reason for Reopen entries on bugs (qa_testapp.bug_reopen_reason).

Fixtures are created as superuser (TransactionCase env is su), the way the
ft_amc_* suites do. The actions under test run as a Senior QA who created
the bug (so the Senior QA record rule lets them write it and press Re-Open),
as the bug's developer (assignee) for the developer resolutions, and as the
project's PM where rights matter. Mail sending is a no-op in test mode.
"""
import base64

from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestBugReopenReason(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True,
                                       tracking_disable=True, mail_create_nolog=True))
        cls.pm = new_test_user(cls.env, 'qarr_pm', email='qarr_pm@example.com',
                               groups='base.group_user,project.group_project_manager')
        cls.qa = new_test_user(cls.env, 'qarr_qa', email='qarr_qa@example.com',
                               groups='base.group_user,qa_testapp.group_qa_senior')
        cls.junior = new_test_user(cls.env, 'qarr_junior', email='qarr_junior@example.com',
                                   groups='base.group_user,qa_testapp.group_qa_junior')
        # Developer: plain internal user, assignee of the bugs (is_dev_user).
        cls.dev = new_test_user(cls.env, 'qarr_dev', email='qarr_dev@example.com',
                                groups='base.group_user')
        cls.project = cls.env['project.project'].create({
            'name': 'QARR Project', 'ft_project_type': 'implementation',
            'user_id': cls.pm.id, 'privacy_visibility': 'employees',
        })
        cls.Ticket = cls.env['qa_testapp.ticket']
        cls.Reason = cls.env['qa_testapp.bug_reopen_reason']

    def _make_bug(self, user=None, **vals):
        return self.Ticket.with_user(user or self.qa).create(dict({
            'title': 'Login fails with 500 when password contains #',
            'project_id': self.project.id,
            'assignee_id': self.dev.id,
            'severity': 'major',
            'priority': 'p3',
        }, **vals))

    def _upload(self, bug, name='screenshot.png'):
        """What the qa_evidence_files / html editor upload does: an attachment
        created against the record the form shows (the bug)."""
        return self.env['ir.attachment'].with_user(self.qa).create({
            'name': name,
            'datas': base64.b64encode(b'fake image bytes'),
            'mimetype': 'image/png',
            'res_model': 'qa_testapp.ticket',
            'res_id': bug.id,
        })

    # ------------------------------------------------------------------
    def test_first_reopen_creates_editable_entry(self):
        bug = self._make_bug()
        bug_qa = bug.with_user(self.qa)
        bug_qa.action_fixed()
        self.assertEqual(bug.status, 'fixed')
        self.assertEqual(bug.reopen_count, 0)
        self.assertFalse(bug.reopen_reason_ids)
        self.assertFalse(bug.latest_reopen_reason_id)

        bug_qa.action_reopen()

        self.assertEqual(bug.status, 'reopened')
        self.assertEqual(bug.reopen_count, 1)
        self.assertEqual(len(bug.reopen_reason_ids), 1)
        entry = bug.reopen_reason_ids
        self.assertEqual(entry.name, 'Reopen 1')
        self.assertEqual(entry.number, 1)
        self.assertEqual(entry.reopened_by, self.qa)
        self.assertTrue(entry.reopened_on)
        self.assertTrue(entry.is_latest)
        self.assertFalse(entry.reason)
        self.assertEqual(bug.latest_reopen_reason_id, entry)

        # The user who pressed Re-Open fills it in: typed reason + a file.
        att = self._upload(bug)
        entry.with_user(self.qa).write({
            'reason': '<p>Still reproducible on Chrome 130</p>',
            'attachment_ids': [Command.link(att.id)],
        })
        self.assertIn('Still reproducible', entry.reason)
        self.assertEqual(entry.attachment_ids, att)
        # Re-linked to the entry, like Evidence does for the bug.
        self.assertEqual((att.res_model, att.res_id), (entry._name, entry.id))
        self.assertEqual(entry.attachment_count, 1)

        # The inline proxies on the bug form edit that same entry.
        bug_qa.write({'latest_reopen_reason': '<p>Still reproducible, see video</p>'})
        self.assertIn('see video', entry.reason)
        self.assertEqual(bug.latest_reopen_attachment_ids, att)
        video = self._upload(bug, name='recording.webm')
        bug_qa.write({'latest_reopen_attachment_ids': [Command.link(video.id)]})
        self.assertEqual(entry.attachment_ids, att | video)
        self.assertEqual((video.res_model, video.res_id), (entry._name, entry.id))

    def test_second_reopen_locks_previous_entry(self):
        bug = self._make_bug()
        bug_qa = bug.with_user(self.qa)
        bug_qa.action_fixed()
        bug_qa.action_reopen()
        first = bug.reopen_reason_ids
        att = self._upload(bug)
        first.with_user(self.qa).write({
            'reason': '<p>First reason</p>',
            'attachment_ids': [Command.link(att.id)],
        })

        bug_qa.action_fixed()
        bug_qa.action_reopen()

        self.assertEqual(bug.reopen_count, 2)
        self.assertEqual(bug.reopen_reason_ids.mapped('name'), ['Reopen 1', 'Reopen 2'])
        second = bug.reopen_reason_ids - first
        self.assertEqual(second.number, 2)
        self.assertTrue(second.is_latest)
        self.assertFalse(first.is_latest)
        self.assertEqual(bug.latest_reopen_reason_id, second)

        # Reopen 1 is now read-only on the server, for everyone.
        with self.assertRaises(UserError):
            first.with_user(self.qa).write({'reason': '<p>Rewritten</p>'})
        with self.assertRaises(UserError):
            first.with_user(self.qa).write({'attachment_ids': [Command.clear()]})
        with self.assertRaises(UserError):
            first.with_user(self.qa).unlink()
        with self.assertRaises(UserError):
            first.with_user(self.pm).write({'reason': '<p>Rewritten by PM</p>'})
        with self.assertRaises(UserError):
            first.with_user(self.pm).unlink()

        # ... and preserved: reason and attachment intact.
        self.assertTrue(first.exists())
        self.assertIn('First reason', first.reason)
        self.assertEqual(first.attachment_ids, att)
        self.assertTrue(att.exists())
        self.assertEqual((att.res_model, att.res_id), (first._name, first.id))

        # Reopen 2 is the editable one, directly and through the bug's proxies.
        second.with_user(self.qa).write({'reason': '<p>Second reason</p>'})
        bug_qa.write({'latest_reopen_reason': '<p>Second reason, more detail</p>'})
        self.assertIn('more detail', second.reason)
        self.assertIn('First reason', first.reason)
        self.assertFalse(bug.latest_reopen_attachment_ids)

        # Sudo keeps maintenance possible (same pattern as the module's other guards).
        first.sudo().write({'reason': '<p>First reason (admin correction)</p>'})
        self.assertIn('admin correction', first.reason)

    def test_reopen_count_and_status_behave_as_before(self):
        bug = self._make_bug()
        bug_qa = bug.with_user(self.qa)
        bug_qa.action_fixed()
        bug_qa.action_reopen()
        self.assertEqual((bug.status, bug.reopen_count), ('reopened', 1))
        self.assertEqual(bug.escalation_level, 'none')
        self.assertEqual(bug.assignee_id, self.dev)

        bug_qa.action_in_progress()
        bug_qa.action_fixed()
        bug_qa.action_closed()
        self.assertEqual(bug.status, 'closed')
        bug_qa.action_reopen()
        self.assertEqual((bug.status, bug.reopen_count), ('reopened', 2))

        # Developer rejection, then QA re-opens: rejection reason cleared as before.
        bug.with_user(self.dev).action_dev_reject('Works for me')
        self.assertEqual(bug.status, 'rejected')
        self.assertEqual(bug.dev_rejection_reason, 'Works for me')
        bug_qa.action_reopen()
        self.assertEqual((bug.status, bug.reopen_count), ('reopened', 3))
        self.assertFalse(bug.dev_rejection_reason)
        # 3rd reopen escalates exactly as before: no customer on the project,
        # so the PM is the fallback target at the 'qa_lead' level.
        self.assertEqual(bug.escalation_level, 'qa_lead')
        self.assertEqual(bug.assignee_id, self.pm)

        # One entry per reopen, numbered from the count, oldest first.
        self.assertEqual(bug.reopen_reason_ids.mapped('number'), [1, 2, 3])
        self.assertEqual(bug.reopen_reason_ids.mapped('name'), ['Reopen 1', 'Reopen 2', 'Reopen 3'])
        self.assertEqual(bug.reopen_reason_ids.mapped('is_latest'), [False, False, True])
        self.assertEqual(bug.latest_reopen_reason_id.name, 'Reopen 3')

    def test_pending_approval_bug_cannot_reopen_and_gets_no_entry(self):
        bug = self._make_bug(user=self.junior)
        self.assertEqual(bug.approval_state, 'pending_approval')
        with self.assertRaises(UserError):
            bug.with_user(self.junior).action_reopen()
        self.assertEqual(bug.reopen_count, 0)
        self.assertFalse(bug.reopen_reason_ids)

    def test_entry_must_match_current_reopen(self):
        bug = self._make_bug()
        bug_qa = bug.with_user(self.qa)
        # Never re-opened: no hand-made entry.
        with self.assertRaises(UserError):
            self.Reason.with_user(self.qa).create({'ticket_id': bug.id})

        bug_qa.action_fixed()
        bug_qa.action_reopen()
        entry = bug.reopen_reason_ids
        # Duplicate of the current reopen, or a number that is not the current one.
        with self.assertRaises(UserError):
            self.Reason.with_user(self.qa).create({'ticket_id': bug.id, 'number': 1})
        with self.assertRaises(UserError):
            self.Reason.with_user(self.qa).create({'ticket_id': bug.id, 'number': 5})
        # An entry cannot be renumbered or moved to another bug.
        with self.assertRaises(UserError):
            entry.with_user(self.qa).write({'number': 7})
        other = self._make_bug(title='Another bug')
        with self.assertRaises(UserError):
            entry.with_user(self.qa).write({'ticket_id': other.id})
        self.assertEqual(bug.reopen_reason_ids, entry)
        self.assertEqual(entry.number, 1)

    def test_entries_follow_bug_deletion(self):
        bug = self._make_bug()
        bug_qa = bug.with_user(self.qa)
        bug_qa.action_fixed()
        bug_qa.action_reopen()
        entry_id = bug.reopen_reason_ids.id
        bug.sudo().unlink()
        self.assertFalse(self.Reason.browse(entry_id).exists())
