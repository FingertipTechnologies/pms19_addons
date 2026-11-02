# -*- coding: utf-8 -*-
"""Implementation Project Stage Report: days worked, overdue days, extension
attribution, triggers, idempotency and the Project Dashboard feeds
(get_dashboard_rows / get_dashboard_matrix: scope by project / manager /
include_closed).

Fixtures are created as superuser (TransactionCase env is su), like the
sibling PMS suites: project creation as a normal user needs groups and
bt_project_customization's rules, and superuser may back-date the actual
entry dates (ft_project_stage_dates' guard lets su through, which is what
the numbers in these tests rely on). Approvals run as base.user_admin, whom
project_date_extension puts in the approver group.

Planned Date of a stage is the date the project must REACH it by
(project_date_extension.STAGE_PLANNED_DATE_FIELD: KICKOFF -> date_start,
DISC -> kick_start_meeting_date, DEV -> brd_approval_date, ...), and Overdue
Days is the stage's approved Extension Days plus entry - planned for a
reached stage, today - planned for the first stage after the current one that
is not reached yet, nothing on top elsewhere (19.0.1.4.0: the approved
extension IS the delay of the stage).
"""
from datetime import date, timedelta

from freezegun import freeze_time

from odoo import fields
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged

from odoo.addons.ft_project_stage_dates.models.project_project import (
    PL_ACTUAL_STAGE_KEYS,
)
from odoo.addons.project_date_extension.models.project_date_extension_request import (
    _stage_planned_date_field,
)

APPROVER = 'project_date_extension.group_project_date_extension_approver'


@tagged('post_install', '-at_install')
class TestProjectStageReport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True))
        ref = cls.env.ref
        cls.kickoff = ref('ft_project_stage_dates.stage_kickoff')
        cls.disc = ref('ft_project_lifecycle.stage_disc')
        cls.dev = ref('ft_project_lifecycle.stage_dev')
        cls.reg = ref('ft_project_lifecycle.stage_reg')
        cls.srv = ref('ft_project_lifecycle.stage_srv')
        cls.support = ref('ft_project_lifecycle.stage_support')
        cls.closed = ref('ft_project_lifecycle.stage_closed')
        cls.started = ref('ft_project_lifecycle.stage_started')
        cls.admin = ref('base.user_admin')
        approver = ref(APPROVER)
        gfield = 'group_ids' if 'group_ids' in cls.admin._fields else 'groups_id'
        cls.admin.write({gfield: [Command.link(approver.id)]})
        cls.customer = cls.env['res.partner'].create(
            {'name': 'PSR Customer', 'email': 'psr.customer@example.com'})
        cls.Line = cls.env['ft.project.stage.line']
        cls.Request = cls.env['project.date.extension.request']
        cls.today = fields.Date.context_today(cls.env['project.project'])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _vals(self, stage=None, **extra):
        """Implementation project values, planned dates in step order."""
        today = self.today
        vals = {
            'name': 'PSR Project',
            'ft_project_type': 'implementation',
            'partner_id': self.customer.id,
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
            'module_ids': [Command.create({'name': 'PSR Module'})],
            'milestone_ids': [Command.create({'name': 'Go Live'})],
        }
        if stage is not None:
            vals['stage_id'] = stage.id
        vals.update(extra)
        return vals

    def _create(self, stage=None, **extra):
        return self.env['project.project'].create(self._vals(stage, **extra))

    def _lines(self, project):
        return self.Line.search([('project_id', '=', project.id)], order='sequence, id')

    def _line(self, project, key):
        line = self._lines(project).filtered(lambda l: l.stage_key == key)
        self.assertEqual(len(line), 1, 'one %s line expected' % key)
        return line

    def _backdate(self, project, **actual):
        """Pretend the project entered stages earlier: superuser may write
        the actual entry dates (the install backfill relies on it)."""
        project.write({'pl_actual_%s_date' % key: date for key, date in actual.items()})

    def _in_disc(self):
        """A project in DISC that entered KICKOFF 10 days ago and DISC 6
        days ago."""
        project = self._create()
        project.write({'stage_id': self.disc.id})
        self._backdate(project, kickoff=self.today - timedelta(days=10),
                       disc=self.today - timedelta(days=6))
        return project

    def _request(self, project, stage, days, **extra):
        planned = project[_stage_planned_date_field(stage)]
        vals = dict(
            project_id=project.id,
            stage_to_extend_id=stage.id,
            requested_date=planned + timedelta(days=days),
            reason='because',
        )
        vals.update(extra)
        return self.Request.create(vals)

    def _approve(self, request):
        request.action_submit_request()
        request.with_user(self.admin)._do_approve(comment='ok')
        self.assertEqual(request.state, 'approved')
        return request

    # ------------------------------------------------------------------
    # lines on creation
    # ------------------------------------------------------------------
    def test_new_project_gets_one_line_per_stage(self):
        project = self._create()
        self.assertEqual(project.stage_id, self.kickoff)
        lines = self._lines(project)
        self.assertEqual(lines.mapped('stage_key'), list(PL_ACTUAL_STAGE_KEYS))
        self.assertEqual(project.ft_stage_line_count, len(PL_ACTUAL_STAGE_KEYS))
        kickoff = self._line(project, 'kickoff')
        self.assertEqual(kickoff.stage_id, self.kickoff)
        self.assertEqual(kickoff.sequence, self.kickoff.sequence)
        self.assertTrue(kickoff.is_current)
        self.assertEqual(kickoff.actual_entry_date, self.today)
        self.assertFalse(kickoff.actual_exit_date)
        self.assertEqual(kickoff.days_worked, 0)
        # Reached today, planned (Start Date) today: on time.
        self.assertEqual(kickoff.overdue_days, 0)
        self.assertEqual(kickoff.planned_date, project.date_start)
        disc = self._line(project, 'disc')
        self.assertFalse(disc.is_current)
        self.assertFalse(disc.actual_entry_date)
        self.assertEqual(disc.planned_date, project.kick_start_meeting_date)
        self.assertEqual(disc.days_worked, 0)
        # Planned dates are the reach-by dates of the same name on the form.
        self.assertEqual(self._line(project, 'dev').planned_date, project.brd_approval_date)
        self.assertEqual(self._line(project, 'reg').planned_date, project.ft_regression_date)
        self.assertEqual(self._line(project, 'srv').planned_date, project.sandbox_review_date)
        self.assertEqual(self._line(project, 'uat').planned_date, project.uat_start_date)
        self.assertEqual(self._line(project, 'data').planned_date, project.pl_data_upload_date)
        self.assertEqual(self._line(project, 'tra').planned_date, project.ft_training_date)
        self.assertEqual(self._line(project, 'support').planned_date, project.support_start_date)
        closed = self._line(project, 'closed')
        self.assertEqual(closed.planned_date, project.date)
        self.assertEqual(len(lines.filtered('is_current')), 1)
        self.assertEqual(lines.mapped('company_id'), project.company_id)
        self.assertEqual(kickoff.display_name, 'PSR Project / KICKOFF')

    # ------------------------------------------------------------------
    # days worked
    # ------------------------------------------------------------------
    def test_days_worked_between_entries_and_today(self):
        project = self._in_disc()
        kickoff = self._line(project, 'kickoff')
        self.assertEqual(kickoff.actual_entry_date, self.today - timedelta(days=10))
        self.assertEqual(kickoff.actual_exit_date, self.today - timedelta(days=6))
        self.assertEqual(kickoff.days_worked, 4)
        self.assertFalse(kickoff.is_current)
        disc = self._line(project, 'disc')
        self.assertEqual(disc.actual_entry_date, self.today - timedelta(days=6))
        self.assertFalse(disc.actual_exit_date)
        self.assertEqual(disc.days_worked, 6)
        self.assertTrue(disc.is_current)
        dev = self._line(project, 'dev')
        self.assertFalse(dev.actual_entry_date)
        self.assertEqual(dev.days_worked, 0)
        self.assertFalse(dev.is_current)
        # Moving on closes DISC today and opens DEV (stage write trigger).
        project.write({'stage_id': self.dev.id})
        disc = self._line(project, 'disc')
        self.assertEqual(disc.actual_exit_date, self.today)
        self.assertEqual(disc.days_worked, 6)
        self.assertFalse(disc.is_current)
        dev = self._line(project, 'dev')
        self.assertTrue(dev.is_current)
        self.assertEqual(dev.actual_entry_date, self.today)
        self.assertEqual(dev.days_worked, 0)
        self.assertEqual(len(self._lines(project).filtered('is_current')), 1)

    def test_skipped_stage_and_missing_current_entry(self):
        project = self._in_disc()
        # Straight to REG: DEV was never entered, DISC exits on REG's entry.
        project.write({'stage_id': self.reg.id})
        self.assertEqual(project.pl_actual_reg_date, self.today)
        self.assertEqual(self._line(project, 'disc').actual_exit_date, self.today)
        self.assertEqual(self._line(project, 'disc').days_worked, 6)
        dev = self._line(project, 'dev')
        self.assertFalse(dev.actual_entry_date)
        self.assertEqual(dev.days_worked, 0)
        self.assertTrue(self._line(project, 'reg').is_current)
        # Imported data: the current stage carries no entry date. DISC, the
        # last entered stage, is not current, so it is counted up to today.
        self._backdate(project, reg=False)
        reg = self._line(project, 'reg')
        self.assertTrue(reg.is_current)
        self.assertFalse(reg.actual_entry_date)
        self.assertEqual(reg.days_worked, 0)
        disc = self._line(project, 'disc')
        self.assertEqual(disc.actual_exit_date, self.today)
        self.assertEqual(disc.days_worked, 6)

    # ------------------------------------------------------------------
    # overdue
    # ------------------------------------------------------------------
    def test_overdue_days_against_planned_date(self):
        project = self._in_disc()
        # Planned dates today or in the future: nothing is overdue (KICKOFF
        # and DISC were reached before their reach-by dates; DEV, the next
        # stage to reach, is not due yet).
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 0)
        # KICKOFF had to be reached 12 days ago and was entered 10 days ago:
        # 2. DISC had to be reached 8 days ago, entered 6 days ago: 2 (the
        # current stage follows the same rule, it does not grow daily). DEV,
        # the first stage after the current one not reached yet, had to be
        # reached 3 days ago: 3, growing by one a day. REG was also due 1
        # day ago but is NOT the next stage: 0, a late project is counted
        # once, not once per remaining stage.
        project.with_context(skip_date_sequence_check=True).write({
            'date_start': self.today - timedelta(days=12),
            'kick_start_meeting_date': self.today - timedelta(days=8),
            'brd_approval_date': self.today - timedelta(days=3),
            'ft_regression_date': self.today - timedelta(days=1),
        })
        kickoff = self._line(project, 'kickoff')
        self.assertEqual(kickoff.planned_date, self.today - timedelta(days=12))
        self.assertEqual(kickoff.overdue_days, 2)
        disc = self._line(project, 'disc')
        self.assertEqual(disc.planned_date, self.today - timedelta(days=8))
        self.assertEqual(disc.overdue_days, 2)
        dev = self._line(project, 'dev')
        self.assertFalse(dev.actual_entry_date)
        self.assertEqual(dev.planned_date, self.today - timedelta(days=3))
        self.assertEqual(dev.overdue_days, 3)
        self.assertEqual(self._line(project, 'reg').overdue_days, 0)
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 7)
        # Replanning DEV into the future clears its overdue days; REG stays
        # 0 even though it is past due, DEV is still the next stage.
        project.with_context(skip_date_sequence_check=True).write(
            {'brd_approval_date': self.today + timedelta(days=5)})
        self.assertEqual(self._line(project, 'dev').overdue_days, 0)
        self.assertEqual(self._line(project, 'reg').overdue_days, 0)
        # Moving into DEV today, 5 days before its reach-by date: DEV is
        # reached early, 0; REG becomes the next stage and is 1 day past due.
        project.write({'stage_id': self.dev.id})
        self.assertEqual(self._line(project, 'dev').overdue_days, 0)
        self.assertEqual(self._line(project, 'reg').overdue_days, 1)
        self.assertEqual(self._line(project, 'disc').overdue_days, 2)
        # No planned date: 0, days worked untouched (DISC left today).
        project.with_context(skip_date_sequence_check=True).write(
            {'kick_start_meeting_date': False})
        disc = self._line(project, 'disc')
        self.assertFalse(disc.planned_date)
        self.assertEqual(disc.overdue_days, 0)
        self.assertEqual(disc.days_worked, 6)
        self.assertEqual(self._line(project, 'kickoff').overdue_days, 2)
        project.with_context(skip_date_sequence_check=True).write(
            {'ft_regression_date': False})
        self.assertEqual(self._line(project, 'reg').overdue_days, 0)

    def test_overdue_reached_late_and_next_unreached(self):
        """The worked example behind the reach-by rule, on fixed calendar
        dates (time frozen on 28 Oct 2026): a project in SUPPORT that
        reached DISC 2 days late, DATA 58 days late, SUPPORT 19 days late,
        skipped REG, and should have reached CLOSED 19 days ago."""
        today = date(2026, 10, 28)
        with freeze_time(today):
            project = self._create()
            project.with_context(skip_date_sequence_check=True).write({
                'date_start': date(2026, 4, 1),               # KICKOFF
                'kick_start_meeting_date': date(2026, 4, 8),  # DISC
                'brd_approval_date': date(2026, 5, 1),        # DEV
                'ft_regression_date': date(2026, 6, 1),       # REG
                'sandbox_review_date': date(2026, 6, 15),     # SRV
                'uat_start_date': date(2026, 7, 1),           # UAT
                'pl_data_upload_date': date(2026, 7, 19),     # DATA
                'ft_training_date': date(2026, 9, 20),        # TRA
                'go_live_date': date(2026, 9, 22),            # no stage
                'support_start_date': date(2026, 9, 23),      # SUPPORT
                'pl_support_end_date': date(2026, 10, 5),     # no stage
                'date': date(2026, 10, 9),                    # CLOSED
            })
            # SUPPORT by SQL (the workflow gates on the way there are not
            # the point); the actual entry dates as superuser, whose write
            # rebuilds the lines with SUPPORT as the current stage.
            self._sql_set(project, stage_id=self.support.id)
            self.assertEqual(project.stage_id, self.support)
            self._backdate(
                project,
                kickoff=date(2026, 4, 1), disc=date(2026, 4, 10),
                dev=date(2026, 5, 1), reg=False, srv=date(2026, 6, 15),
                uat=date(2026, 7, 1), data=date(2026, 9, 15),
                tra=date(2026, 9, 20), support=date(2026, 10, 12),
                closed=False)
            lines = self._lines(project)
            self.assertEqual(len(lines), len(PL_ACTUAL_STAGE_KEYS))
            self.assertTrue(self._line(project, 'support').is_current)
            overdue = {l.stage_key: l.overdue_days for l in lines}
            self.assertEqual(overdue, {
                'kickoff': 0,   # reached on its Start Date
                'disc': 2,      # Kick-off 8 Apr, entered 10 Apr
                'dev': 0,       # reached on its BRD Approval Date
                'reg': 0,       # skipped: never entered, before current
                'srv': 0,
                'uat': 0,
                'data': 58,     # Data Upload 19 Jul, entered 15 Sep
                'tra': 0,
                'support': 19,  # Support Start 23 Sep, entered 12 Oct
                'closed': 19,   # Closed Date 9 Oct, not reached, today 28 Oct
            })
            # Days Worked are untouched by the rule: exit = next entry.
            self.assertEqual(self._line(project, 'dev').actual_exit_date,
                             date(2026, 6, 15))
            self.assertEqual(self._line(project, 'dev').days_worked, 45)
            self.assertEqual(self._line(project, 'reg').days_worked, 0)
            self.assertEqual(self._line(project, 'support').days_worked, 16)
            self.assertFalse(self._line(project, 'closed').actual_entry_date)
            row = self._matrix({'project_id': project.id})['projects'][0]
            self.assertEqual(row['current_stage_id'], self.support.id)
            self.assertEqual(row['total_overdue_days'], 98)
            self.assertEqual(row['total_days_worked'], 210)
            self.assertTrue(row['is_overdue'])
            cells = row['cells']
            self.assertEqual(cells[str(self.closed.id)]['overdue_days'], 19)
            self.assertFalse(cells[str(self.closed.id)]['reached'])
            self.assertEqual(cells[str(self.closed.id)]['planned_date'], '2026-10-09')
            self.assertEqual(cells[str(self.reg.id)]['overdue_days'], 0)
            self.assertEqual(cells[str(self.disc.id)]['planned_date'], '2026-04-08')
        # Reaching CLOSED late, on 30 Oct: CLOSED becomes "reached 21 days
        # late" and nothing is the next stage any more.
        with freeze_time(date(2026, 10, 30)):
            self._sql_set(project, stage_id=self.closed.id)
            self._backdate(project, closed=date(2026, 10, 30))
            self.assertEqual(self._line(project, 'closed').overdue_days, 21)
            self.assertEqual(self._line(project, 'support').overdue_days, 19)
            self.assertEqual(self._line(project, 'support').days_worked, 18)
            self.assertTrue(self._line(project, 'closed').is_current)

    # ------------------------------------------------------------------
    # extension attribution
    # ------------------------------------------------------------------
    def test_extension_days_attributed_to_targeted_stage_only(self):
        project = self._in_disc()
        self.assertEqual(project.pl_total_extension_days, 0)
        before = {
            'disc': project.kick_start_meeting_date,
            'dev': project.brd_approval_date,
            'reg': project.ft_regression_date,
            'srv': project.sandbox_review_date,
        }
        # DISC +3: the Kick-off Date (DISC's reach-by date) and every later
        # date move by 3.
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 0)
        first = self._approve(self._request(project, self.disc, 3))
        self.assertEqual(first.delay_days, 3)
        self.assertEqual(project.kick_start_meeting_date, before['disc'] + timedelta(days=3))
        self.assertEqual(project.brd_approval_date, before['dev'] + timedelta(days=3))
        self.assertEqual(self._line(project, 'disc').extension_days, 3)
        self.assertEqual(self._line(project, 'dev').extension_days, 0)
        self.assertEqual(self._line(project, 'reg').extension_days, 0)
        self.assertEqual(project.pl_total_extension_days, 3)
        # The approved extension is the delay of the stage: DISC was entered
        # before its (extended) reach-by date, yet it is 3 days overdue.
        self.assertEqual(self._line(project, 'disc').overdue_days, 3)
        self.assertEqual(self._line(project, 'dev').overdue_days, 0)
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 3)
        # The planned dates on the lines follow the shift (read live from
        # the project, so they are the dates after the approved extension).
        self.assertEqual(self._line(project, 'disc').planned_date,
                         before['disc'] + timedelta(days=3))
        self.assertEqual(self._line(project, 'dev').planned_date,
                         before['dev'] + timedelta(days=3))
        # DEV +5: BRD Approval (DEV's reach-by date) and later move by 5
        # more; DEV counts 5 only.
        second = self._approve(self._request(project, self.dev, 5))
        self.assertEqual(second.delay_days, 5)
        self.assertEqual(project.brd_approval_date, before['dev'] + timedelta(days=8))
        self.assertEqual(project.ft_regression_date, before['reg'] + timedelta(days=8))
        self.assertEqual(self._line(project, 'disc').extension_days, 3)
        self.assertEqual(self._line(project, 'dev').extension_days, 5)
        self.assertEqual(self._line(project, 'reg').extension_days, 0,
                         'a downstream shift is never counted again')
        self.assertEqual(self._line(project, 'srv').extension_days, 0)
        self.assertEqual(self._line(project, 'reg').planned_date,
                         before['reg'] + timedelta(days=8))
        self.assertEqual(sum(self._lines(project).mapped('extension_days')), 8)
        self.assertEqual(project.pl_total_extension_days, 8)
        # Overdue follows the same attribution, never the downstream shifts:
        # DEV (not reached, reach-by date in the future) is 5 overdue.
        self.assertEqual(self._line(project, 'dev').overdue_days, 5)
        self.assertEqual(self._line(project, 'reg').overdue_days, 0)
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 8)
        # A request that is not approved counts nothing.
        pending = self._request(project, self.dev, 7)
        pending.action_submit_request()
        self.assertEqual(self._line(project, 'dev').extension_days, 5)
        self.assertEqual(self._line(project, 'dev').overdue_days, 5)
        self.assertEqual(project.pl_total_extension_days, 8)
        pending.with_user(self.admin)._do_reject(comment='no')
        self.assertEqual(self._line(project, 'dev').extension_days, 5)
        self.assertEqual(self._line(project, 'dev').overdue_days, 5)
        self.assertEqual(project.pl_total_extension_days, 8)
        # A preponement (REG -1) is approved but counts 0; it moves only the
        # Regression Date (REG's reach-by date), not the later ones.
        prepone = self._approve(self._request(project, self.reg, -1))
        self.assertTrue(prepone.is_preponement)
        self.assertEqual(prepone.delay_days, 0)
        self.assertEqual(self._line(project, 'reg').extension_days, 0)
        self.assertEqual(self._line(project, 'reg').overdue_days, 0)
        self.assertEqual(sum(self._lines(project).mapped('overdue_days')), 8)
        self.assertEqual(self._line(project, 'reg').planned_date,
                         before['reg'] + timedelta(days=7))
        self.assertEqual(self._line(project, 'srv').planned_date,
                         before['srv'] + timedelta(days=8))
        self.assertEqual(sum(self._lines(project).mapped('extension_days')), 8)
        self.assertEqual(project.pl_total_extension_days, 8)
        # Still one line per stage after all those rebuilds.
        self.assertEqual(len(self._lines(project)), len(PL_ACTUAL_STAGE_KEYS))

    def test_total_extension_days_follows_request_state(self):
        project = self._in_disc()
        request = self._approve(self._request(project, self.dev, 4))
        self.assertEqual(project.pl_total_extension_days, 4)
        self.assertEqual(self._line(project, 'dev').extension_days, 4)
        self.assertEqual(self._line(project, 'dev').overdue_days, 4)
        # Superuser edits the state back (there is no button for it): the
        # stored total and the line follow.
        request.write({'state': 'rejected'})
        self.assertEqual(project.pl_total_extension_days, 0)
        self.assertEqual(self._line(project, 'dev').extension_days, 0)
        self.assertEqual(self._line(project, 'dev').overdue_days, 0)
        request.write({'state': 'approved'})
        self.assertEqual(project.pl_total_extension_days, 4)
        self.assertEqual(self._line(project, 'dev').extension_days, 4)
        self.assertEqual(self._line(project, 'dev').overdue_days, 4)

    # ------------------------------------------------------------------
    # only Implementation projects
    # ------------------------------------------------------------------
    def test_other_project_types_have_no_lines(self):
        amc = self.env['project.project'].create({
            'name': 'PSR AMC', 'ft_project_type': 'amc',
            'partner_id': self.customer.id, 'date_start': self.today,
            'date': self.today + timedelta(days=30),
            'privacy_visibility': 'employees',
        })
        self.assertFalse(self._lines(amc))
        self.assertEqual(amc.ft_stage_line_count, 0)
        self.Line._rebuild_for_projects(amc)
        self.assertFalse(self._lines(amc))
        general = self.env['project.project'].create({
            'name': 'PSR General', 'ft_project_type': 'general',
            'partner_id': self.customer.id,
        })
        self.assertEqual(general.stage_id, self.started)
        self.assertFalse(self._lines(general))
        # Becoming an Implementation project builds the lines.
        general.write({'ft_project_type': 'implementation'})
        self.assertEqual(general.stage_id, self.kickoff)
        lines = self._lines(general)
        self.assertEqual(len(lines), len(PL_ACTUAL_STAGE_KEYS))
        self.assertTrue(self._line(general, 'kickoff').is_current)
        self.assertEqual(self._line(general, 'kickoff').actual_entry_date, self.today)

    def test_smart_button_opens_the_project_lines(self):
        project = self._in_disc()
        self.assertTrue(self._lines(project))
        action = project.action_view_stage_report()
        self.assertEqual(action['res_model'], 'ft.project.stage.line')
        self.assertEqual(action['domain'], [('project_id', '=', project.id)])
        self.assertEqual(action['context']['pivot_measures'],
                         ['days_worked', 'overdue_days', 'extension_days'])
        self.assertEqual(self.Line._fields['project_id'].ondelete, 'cascade')

    # ------------------------------------------------------------------
    # rebuild / cron idempotent
    # ------------------------------------------------------------------
    def test_rebuild_is_idempotent(self):
        project = self._in_disc()
        other = self._create(name='PSR Other')
        per_project = {p: len(self._lines(p)) for p in (project, other)}
        total = self.Line.search_count([])
        self.Line._rebuild_for_projects()
        self.Line._rebuild_for_projects()
        self.assertEqual(self.Line.search_count([]), total)
        for p, count in per_project.items():
            self.assertEqual(len(self._lines(p)), count)
        self.assertEqual(self._line(project, 'kickoff').days_worked, 4)
        self.assertEqual(self._line(project, 'disc').days_worked, 6)
        # The list button rebuilds everything too, and returns to the list.
        self.assertTrue(self.Line.browse().action_refresh())
        self.assertEqual(self.Line.search_count([]), total)
        # The nightly cron calls the same rebuild.
        cron = self.env.ref('ft_project_stage_report.ir_cron_refresh_stage_report')
        self.assertTrue(cron.active)
        self.assertEqual(cron.model_id.model, 'ft.project.stage.line')
        self.assertIn('_rebuild_for_projects', cron.code)
        self.assertEqual(cron.interval_type, 'days')
        self.assertEqual(cron.interval_number, 1)

    # ------------------------------------------------------------------
    # Project Dashboard feed (get_dashboard_rows)
    # ------------------------------------------------------------------
    def _rows(self, scope=None, projects=None):
        """get_dashboard_rows, kept to the test's own projects: the DB the
        post_install suite runs on may hold other Implementation projects."""
        rows = self.Line.get_dashboard_rows(scope or {})
        if projects is not None:
            rows = [r for r in rows if r['project_id'] in projects.ids]
        return rows

    def _sql_set(self, project, **cols):
        """Set project columns behind the ORM's back. Used for the CLOSED
        stage and the template flag only: reaching CLOSED through write()
        runs the planning-workflow gates (finance, retrospective, feedback
        evidence ...), which is not what these tests are about, and the
        dashboard feed only READS the stage."""
        assignments = ', '.join('%s = %%s' % col for col in cols)
        self.env.cr.execute(
            'UPDATE project_project SET %s WHERE id = %%s' % assignments,
            list(cols.values()) + [project.id])
        project.invalidate_recordset()

    def test_dashboard_rows_content_and_order(self):
        project = self._in_disc()
        project.write({'user_id': self.admin.id})
        rows = self._rows(projects=project)
        self.assertEqual(len(rows), len(PL_ACTUAL_STAGE_KEYS))
        # Pipeline order within the project, the stage sequence as tie-break
        # key for the client (DataTable sorts on one key, stably).
        self.assertEqual([r['sequence'] for r in rows],
                         sorted(r['sequence'] for r in rows))
        self.assertEqual(rows[0]['stage_name'], self.kickoff.name)
        self.assertEqual(rows[1]['stage_name'], self.disc.name)
        expected_keys = {
            'id', 'project_id', 'project_name', 'stage_name', 'sequence',
            'planned_date', 'actual_entry_date', 'actual_exit_date',
            'is_current', 'days_worked', 'overdue_days', 'extension_days',
            'project_closed',
        }
        for row in rows:
            self.assertEqual(set(row), expected_keys)
            self.assertEqual(row['project_id'], project.id)
            self.assertEqual(row['project_name'], 'PSR Project')
            self.assertFalse(row['project_closed'])
        kickoff, disc, dev = rows[0], rows[1], rows[2]
        self.assertEqual(kickoff['id'], self._line(project, 'kickoff').id)
        self.assertFalse(kickoff['is_current'])
        # Dates travel as ISO strings, empty ones as False.
        self.assertEqual(kickoff['actual_entry_date'],
                         fields.Date.to_string(self.today - timedelta(days=10)))
        self.assertEqual(kickoff['actual_exit_date'],
                         fields.Date.to_string(self.today - timedelta(days=6)))
        self.assertEqual(kickoff['planned_date'],
                         fields.Date.to_string(project.date_start))
        self.assertEqual(disc['planned_date'],
                         fields.Date.to_string(project.kick_start_meeting_date))
        self.assertEqual(kickoff['days_worked'], 4)
        self.assertEqual(kickoff['overdue_days'], 0)
        self.assertEqual(kickoff['extension_days'], 0)
        self.assertTrue(disc['is_current'])
        self.assertEqual(disc['days_worked'], 6)
        self.assertFalse(disc['actual_exit_date'])
        self.assertFalse(dev['actual_entry_date'])
        self.assertFalse(dev['is_current'])
        # An approved extension shows up on the stage it targeted.
        self._approve(self._request(project, self.dev, 5))
        rows = self._rows(projects=project)
        self.assertEqual(rows[2]['extension_days'], 5)
        self.assertEqual(rows[1]['extension_days'], 0)
        self.assertEqual(rows[2]['planned_date'],
                         fields.Date.to_string(project.brd_approval_date))

    def test_dashboard_rows_scope_project_and_manager(self):
        gfield = 'group_ids' if 'group_ids' in self.admin._fields else 'groups_id'
        other_pm = self.env['res.users'].create({
            'name': 'PSR Other PM', 'login': 'psr_other_pm',
            gfield: [Command.link(self.env.ref('project.group_project_manager').id)],
        })
        first = self._in_disc()
        first.write({'user_id': self.admin.id})
        second = self._create(name='PSR Second', user_id=other_pm.id)
        both = first | second
        # No scope: both, the first project's rows before the second's.
        rows = self._rows(projects=both)
        self.assertEqual(len(rows), 2 * len(PL_ACTUAL_STAGE_KEYS))
        names = [r['project_name'] for r in rows]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertEqual(names[0], 'PSR Project')
        # One project.
        rows = self._rows({'project_id': second.id}, projects=both)
        self.assertEqual({r['project_id'] for r in rows}, {second.id})
        self.assertEqual(len(rows), len(PL_ACTUAL_STAGE_KEYS))
        # One Project Manager (res.users id, like the dashboard header).
        rows = self._rows({'manager_id': self.admin.id}, projects=both)
        self.assertEqual({r['project_id'] for r in rows}, {first.id})
        rows = self._rows({'manager_id': other_pm.id}, projects=both)
        self.assertEqual({r['project_id'] for r in rows}, {second.id})
        # Project AND manager that do not match each other: nothing.
        self.assertEqual(
            self._rows({'project_id': first.id, 'manager_id': other_pm.id},
                       projects=both), [])
        # A non-Implementation project is never listed, even when asked for.
        amc = self.env['project.project'].create({
            'name': 'PSR AMC', 'ft_project_type': 'amc',
            'partner_id': self.customer.id, 'date_start': self.today,
            'date': self.today + timedelta(days=30),
            'privacy_visibility': 'employees',
        })
        self.assertEqual(self._rows({'project_id': amc.id}), [])

    def test_dashboard_rows_include_closed(self):
        running = self._in_disc()
        archived = self._create(name='PSR Archived')
        archived.action_archive()
        self.assertFalse(archived.active)
        in_closed = self._create(name='PSR Closed')
        closed_stage = self.env.ref('ft_project_lifecycle.stage_closed')
        self._sql_set(in_closed, stage_id=closed_stage.id)
        self.assertEqual(in_closed.stage_id, closed_stage)
        self.assertEqual(closed_stage._ft_stage_key(), 'closed')
        every = running | archived | in_closed
        # Hidden by default: both the CLOSED stage and the archive bin.
        rows = self._rows(projects=every)
        self.assertEqual({r['project_id'] for r in rows}, {running.id})
        self.assertEqual(self._rows({'project_id': archived.id}), [])
        self.assertEqual(self._rows({'project_id': in_closed.id}), [])
        # Include closed: all three, the closed ones flagged for the client.
        rows = self._rows({'include_closed': True}, projects=every)
        self.assertEqual({r['project_id'] for r in rows}, set(every.ids))
        closed_flags = {r['project_id']: r['project_closed'] for r in rows}
        self.assertFalse(closed_flags[running.id])
        self.assertTrue(closed_flags[archived.id])
        self.assertTrue(closed_flags[in_closed.id])
        # A template is a blueprint, not a delivery: never listed.
        if 'is_template' in self.env['project.project']._fields:
            template = self._create(name='PSR Template')
            self._sql_set(template, is_template=True)
            self.assertTrue(template.is_template)
            self.assertEqual(
                self._rows({'project_id': template.id, 'include_closed': True}),
                [])

    # ------------------------------------------------------------------
    # Project Dashboard matrix (get_dashboard_matrix)
    # ------------------------------------------------------------------
    def _matrix(self, scope=None, projects=None):
        """get_dashboard_matrix, its projects kept to the test's own (the
        post_install DB may hold other Implementation projects)."""
        data = self.Line.get_dashboard_matrix(scope or {})
        if projects is not None:
            data['projects'] = [p for p in data['projects']
                                if p['project_id'] in projects.ids]
        return data

    def test_dashboard_matrix_shape_and_totals(self):
        gfield = 'group_ids' if 'group_ids' in self.admin._fields else 'groups_id'
        other_pm = self.env['res.users'].create({
            'name': 'PSR Other PM', 'login': 'psr_other_pm',
            gfield: [Command.link(self.env.ref('project.group_project_manager').id)],
        })
        project = self._in_disc()
        project.write({'user_id': self.admin.id})
        # KICKOFF had to be reached 12 days ago, entered 10 days ago: 2.
        # DISC had to be reached 8 days ago, entered 6 days ago: 2. DEV, the
        # next stage, had to be reached 3 days ago: 3 (see the overdue test).
        project.with_context(skip_date_sequence_check=True).write({
            'date_start': self.today - timedelta(days=12),
            'kick_start_meeting_date': self.today - timedelta(days=8),
            'brd_approval_date': self.today - timedelta(days=3),
        })
        second = self._create(name='PSR Second', user_id=other_pm.id)
        both = project | second

        data = self._matrix({'project_id': project.id})
        self.assertEqual(set(data), {'stages', 'projects'})
        # One column per line of the project, in pipeline order, keyed by
        # the stage id.
        lines = self._lines(project)
        stages = data['stages']
        self.assertEqual([s['id'] for s in stages], lines.mapped('stage_id').ids)
        self.assertEqual([s['sequence'] for s in stages],
                         sorted(s['sequence'] for s in stages))
        self.assertEqual(stages[0]['name'], self.kickoff.name)
        self.assertEqual(stages[1]['name'], self.disc.name)
        self.assertEqual(set(stages[0]), {'id', 'name', 'sequence'})
        # One row for the project.
        self.assertEqual(len(data['projects']), 1)
        row = data['projects'][0]
        self.assertEqual(set(row), {
            'project_id', 'project_name', 'manager_name', 'project_closed',
            'current_stage_id', 'total_days_worked', 'total_overdue_days',
            'is_overdue', 'cells',
        })
        self.assertEqual(row['project_id'], project.id)
        self.assertEqual(row['project_name'], 'PSR Project')
        self.assertEqual(row['manager_name'], self.admin.name)
        self.assertFalse(row['project_closed'])
        self.assertEqual(row['current_stage_id'], self.disc.id)
        # Cells keyed by the stage id as a string (JSON), one per line.
        self.assertEqual(set(row['cells']), {str(s['id']) for s in stages})
        kickoff = row['cells'][str(self.kickoff.id)]
        self.assertEqual(set(kickoff), {
            'days_worked', 'overdue_days', 'extension_days', 'planned_date',
            'actual_entry_date', 'actual_exit_date', 'is_current', 'reached',
        })
        self.assertEqual(kickoff['days_worked'], 4)
        self.assertEqual(kickoff['overdue_days'], 2)
        self.assertTrue(kickoff['reached'])
        self.assertFalse(kickoff['is_current'])
        self.assertEqual(kickoff['actual_entry_date'],
                         fields.Date.to_string(self.today - timedelta(days=10)))
        self.assertEqual(kickoff['actual_exit_date'],
                         fields.Date.to_string(self.today - timedelta(days=6)))
        self.assertEqual(kickoff['planned_date'],
                         fields.Date.to_string(self.today - timedelta(days=12)))
        disc = row['cells'][str(self.disc.id)]
        self.assertTrue(disc['is_current'])
        self.assertTrue(disc['reached'])
        self.assertEqual(disc['days_worked'], 6)
        self.assertEqual(disc['overdue_days'], 2)
        self.assertFalse(disc['actual_exit_date'])
        self.assertEqual(disc['planned_date'],
                         fields.Date.to_string(self.today - timedelta(days=8)))
        dev = row['cells'][str(self.dev.id)]
        self.assertFalse(dev['reached'])
        self.assertFalse(dev['actual_entry_date'])
        self.assertEqual(dev['days_worked'], 0)
        # Not reached, but the next stage to reach and 3 days past due.
        self.assertEqual(dev['overdue_days'], 3)
        self.assertEqual(dev['planned_date'],
                         fields.Date.to_string(self.today - timedelta(days=3)))
        self.assertEqual(row['cells'][str(self.reg.id)]['overdue_days'], 0)
        # Totals are the plain sums over the lines; overdue when any is.
        self.assertEqual(row['total_days_worked'], sum(lines.mapped('days_worked')))
        self.assertEqual(row['total_days_worked'], 10)
        self.assertEqual(row['total_overdue_days'], sum(lines.mapped('overdue_days')))
        self.assertEqual(row['total_overdue_days'], 7)
        self.assertTrue(row['is_overdue'])
        # An approved extension lands in the cell of the stage it targeted,
        # and is its overdue: DEV's reach-by date moves from 3 days ago to
        # 2 days ahead (nothing missed any more), the 5 extended days are
        # the delay. Total 2 + 2 + 5.
        self._approve(self._request(project, self.dev, 5))
        row = self._matrix({'project_id': project.id})['projects'][0]
        dev = row['cells'][str(self.dev.id)]
        self.assertEqual(dev['extension_days'], 5)
        self.assertEqual(dev['overdue_days'], 5)
        self.assertEqual(dev['planned_date'],
                         fields.Date.to_string(self.today + timedelta(days=2)))
        self.assertEqual(row['cells'][str(self.disc.id)]['extension_days'], 0)
        self.assertEqual(row['cells'][str(self.disc.id)]['overdue_days'], 2)
        self.assertEqual(row['total_overdue_days'], 9)
        self.assertTrue(row['is_overdue'])
        # The second project: nothing overdue, in KICKOFF, other manager.
        row = self._matrix({'project_id': second.id})['projects'][0]
        self.assertEqual(row['manager_name'], 'PSR Other PM')
        self.assertEqual(row['current_stage_id'], self.kickoff.id)
        self.assertEqual(row['total_overdue_days'], 0)
        self.assertFalse(row['is_overdue'])
        # Scope goes through the same helper as the flat rows: no scope lists
        # both by name, a manager scope one, and the two feeds agree.
        data = self._matrix(projects=both)
        self.assertEqual([p['project_id'] for p in data['projects']],
                         [project.id, second.id])
        for scope in ({}, {'manager_id': self.admin.id},
                      {'manager_id': other_pm.id}, {'project_id': second.id}):
            matrix_ids = {p['project_id']
                          for p in self._matrix(scope, projects=both)['projects']}
            rows_ids = {r['project_id'] for r in self._rows(scope, projects=both)}
            self.assertEqual(matrix_ids, rows_ids, scope)
        self.assertEqual(
            {p['project_id']
             for p in self._matrix({'manager_id': other_pm.id}, projects=both)['projects']},
            {second.id})
        # Out of scope entirely: an empty matrix, not a crash.
        amc = self.env['project.project'].create({
            'name': 'PSR AMC', 'ft_project_type': 'amc',
            'partner_id': self.customer.id, 'date_start': self.today,
            'date': self.today + timedelta(days=30),
            'privacy_visibility': 'employees',
        })
        self.assertEqual(self._matrix({'project_id': amc.id}),
                         {'stages': [], 'projects': []})

    def test_no_menu_of_its_own(self):
        """Since 19.0.1.1.0 the table lives in the Project Dashboard; the
        former Project > Implementation Report menus are gone, the actions
        behind the smart button are not."""
        for xmlid in ('menu_ft_project_stage_report_root',
                      'menu_ft_project_stage_report_days',
                      'menu_ft_project_stage_report_delays'):
            self.assertFalse(self.env.ref(
                'ft_project_stage_report.' + xmlid, raise_if_not_found=False))
        for xmlid in ('action_ft_project_stage_report_days',
                      'action_ft_project_stage_report_delays'):
            action = self.env.ref('ft_project_stage_report.' + xmlid)
            self.assertEqual(action.res_model, 'ft.project.stage.line')
        self.assertFalse(self.env['ir.ui.menu'].search([
            ('action', 'in', [
                'ir.actions.act_window,%d' % self.env.ref(
                    'ft_project_stage_report.' + xmlid).id
                for xmlid in ('action_ft_project_stage_report_days',
                              'action_ft_project_stage_report_delays')]),
        ]))

