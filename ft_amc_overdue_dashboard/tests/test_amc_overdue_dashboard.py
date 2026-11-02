# -*- coding: utf-8 -*-
"""AMC Task Overdue Dashboard: scope, day arithmetic, ordering and filters.

Fixtures are created as superuser (TransactionCase env is su), the same way
the AMC monthly timesheet tests do: bt_project_customization's task rules
(deadline required, same-day deadline for call types, Task Source on User
Stories, future-deadline on write) all exempt su, so deadlines in the past and
a task with no deadline can be set up deterministically. The one rule that
does NOT exempt su, the future-deadline check on write, is opted out of with
``skip_ft_deadline_validation`` wherever a past deadline is written.

Day arithmetic is anchored on ``fields.Date.context_today`` of the test env.
Every deadline and completion is placed at 12:00 UTC on its day, so its local
calendar day is that same day in any timezone the test user may carry
(UTC-11 .. UTC+11).

Overdue is measured from the ORIGINAL deadline (``pwf_original_deadline``,
set by ft_pms_planning_workflow on create when a deadline is given), and a
completed task carries the figure frozen on its completion day
(``ft_historical_overdue_days``).

The database under test is not assumed empty: it may already hold AMC projects
with tasks. Absolute figures are therefore asserted through the project_id
filter on projects created here; unfiltered calls are checked for consistency
and for the presence / absence of the rows created here.
"""
from datetime import datetime, time, timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.fields import Command
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ft_amc_overdue_dashboard.hooks import (
    backfill_historical_overdue,
    backfill_original_deadlines,
    post_init_hook,
)


@tagged('post_install', '-at_install')
class TestAmcOverdueDashboard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, no_reset_password=True,
                                       tracking_disable=True))
        cls.company = cls.env.company
        cls.Dashboard = cls.env['ft.amc.overdue.dashboard']
        cls.today = fields.Date.context_today(cls.Dashboard)
        cls.customer = cls.env['res.partner'].create({
            'name': 'AMC Overdue Customer', 'email': 'overdue@example.com'})

        # bt_project_customization declares module_id required. Make sure the
        # database offers one so every task created here carries it.
        cls.module = cls.env['cus.module'].search([], limit=1)
        if not cls.module:
            cls.module = cls.env['cus.module'].create({
                'name': 'AMC Overdue Test Module'})

        cls.pm = new_test_user(
            cls.env, 'amc_overdue_pm', email='overdue_pm@example.com',
            groups='base.group_user,project.group_project_user')
        cls.dev = new_test_user(
            cls.env, 'amc_overdue_dev', email='overdue_dev@example.com',
            groups='base.group_user,project.group_project_user')
        # A plain AMC Reporting Manager: the least privileged group the data
        # provider's model access is open to (the Project Dashboard the table
        # sits in is admin-only, but the access is kept for other clients),
        # used to check the provider works under record rules.
        cls.amc_manager = new_test_user(
            cls.env, 'amc_overdue_mgr', email='overdue_mgr@example.com',
            groups='base.group_user,ft_amc_monthly_timesheet.group_amc_manager')

        cls.amc = cls._make_project('AMC Overdue Contract A', 'amc')
        cls.amc_other = cls._make_project('AMC Overdue Contract B', 'amc')
        cls.general = cls._make_project('AMC Overdue General Project', 'general')
        projects = cls.amc | cls.amc_other | cls.general

        Stage = cls.env['project.task.type']
        cls.working = Stage.create({
            'name': 'AMC Overdue Working', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})
        # Final by name (COMPLETED_STAGE_NAMES), not by fold, so Odoo's own
        # update_date_end leaves date_end alone and the test sets it itself.
        cls.completed = Stage.create({
            'name': 'Completed', 'fold': False,
            'project_ids': [Command.set(projects.ids)]})

        # --- AMC project A -------------------------------------------------
        # Overdue by 5 days, created today.
        cls.t_overdue = cls._task('Overdue 5 days', deadline=-5,
                                  users=cls.pm | cls.dev)
        # Overdue by the same 5 days but 10 days old: the age tie-break.
        cls.t_overdue_old = cls._task('Overdue 5 days, 10 days old', deadline=-5)
        cls._age(cls.t_overdue_old, 10)
        # Due tomorrow: not overdue.
        cls.t_future = cls._task('Due tomorrow', deadline=1)
        # No deadline at all: a User Story, which is not held to the same-day
        # default the call types get in create().
        cls.t_no_deadline = cls._task('No deadline', deadline=None,
                                      task_type='user_story')
        # Completed 3 days ago, 10 days past its deadline: frozen at 7 days.
        cls.t_closed = cls._task('Closed late', deadline=-10,
                                 stage=cls.completed)
        cls.t_closed.write({'date_end': cls._noon_utc(-3)})
        # Archived: never listed.
        cls.t_archived = cls._task('Archived overdue', deadline=-5)
        cls.t_archived.write({'active': False})

        # --- AMC project B -------------------------------------------------
        cls.t_other = cls._task('Other contract, overdue 2 days', deadline=-2,
                                project=cls.amc_other)

        # --- General project: out of scope --------------------------------
        cls.t_general = cls._task('General project overdue', deadline=-5,
                                  project=cls.general)

    # ------------------------------------------------------------------
    # fixtures
    # ------------------------------------------------------------------
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
            'date_start': cls.today - timedelta(days=365),
            'date': cls.today + timedelta(days=365),
        }, **vals))

    @classmethod
    def _noon_utc(cls, days_from_today):
        """12:00 UTC on today + n days: the same local day in every zone."""
        return datetime.combine(
            cls.today + timedelta(days=days_from_today), time(12, 0))

    @classmethod
    def _day(cls, days_from_today):
        return fields.Date.to_string(cls.today + timedelta(days=days_from_today))

    @staticmethod
    def _task_title(name):
        return '%s [AMC overdue test]' % name

    @classmethod
    def _task(cls, name, deadline, project=None, stage=None,
              task_type='internal_call', users=None):
        # bt_project_customization requires a task title of 20+ characters.
        vals = {
            'name': cls._task_title(name),
            'project_id': (project or cls.amc).id,
            'stage_id': (stage or cls.working).id,
            'task_type': task_type,
            'estimated': 2.0,
            'module_id': cls.module.id,
        }
        if deadline is not None:
            vals['date_deadline'] = cls._noon_utc(deadline)
        if users:
            vals['user_ids'] = [Command.set(users.ids)]
        return cls.env['project.task'].create(vals)

    @classmethod
    def _age(cls, task, days):
        """Back-date a task's creation by ``days`` days.

        create_date is not writable through the ORM, so it is set in SQL;
        the pending ORM writes are flushed first so nothing later overwrites
        it, and the record's cache is dropped so ft_task_age is recomputed.
        """
        cls.env.flush_all()
        cls.env.cr.execute(
            "UPDATE project_task SET create_date = create_date - %s::interval "
            "WHERE id = %s", ('%s days' % days, task.id))
        task.invalidate_recordset()

    def _revise_deadline(self, task, days_from_today):
        """Move a task's Deadline (its ORIGINAL one stays as it was)."""
        task.with_context(skip_ft_deadline_validation=True).write(
            {'date_deadline': self._noon_utc(days_from_today)})

    def _complete(self, task, days_from_today=0):
        """Move a task into Completed, then set the completion day.

        bt_project_customization stamps date_end = now on the move; the second
        write re-dates it to the wanted day (12:00 UTC), which re-stamps the
        frozen figure for that day.
        """
        task.write({'stage_id': self.completed.id})
        if days_from_today != 0:
            task.write({'date_end': self._noon_utc(days_from_today)})

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _data(self, **filters):
        return self.Dashboard.get_dashboard_data(filters or None)

    def _rows(self, data, project=None):
        if project is None:
            return data['rows']
        return [r for r in data['rows'] if r['project_id'] == project.id]

    def _row(self, data, task):
        rows = [r for r in data['rows'] if r['id'] == task.id]
        self.assertEqual(len(rows), 1, 'expected exactly one row for %s' % task.name)
        return rows[0]

    def _ids(self, rows):
        return [r['id'] for r in rows]

    def _assert_kpis_match_rows(self, data):
        rows = data['rows']
        overdue = [r['overdue_days'] for r in rows if r['overdue_days'] is not None]
        self.assertEqual(data['kpis'], {
            'total_tasks': len(rows),
            'overdue_tasks': len(overdue),
            'overdue_days': sum(overdue),
            'projects': len({r['project_id'] for r in rows}),
        })

    def _assert_sorted(self, rows):
        keys = [self.Dashboard._row_sort_key(r) for r in rows]
        self.assertEqual(keys, sorted(keys))

    # ------------------------------------------------------------------
    # fixture sanity
    # ------------------------------------------------------------------
    def test_fixture_states(self):
        self.assertTrue(self.t_closed.is_closed)
        self.assertEqual(self.t_closed.state, '1_done')
        self.assertFalse(self.t_overdue.is_closed)
        self.assertFalse(self.t_archived.active)
        self.assertFalse(self.t_no_deadline.date_deadline)
        self.assertFalse(self.t_no_deadline.pwf_original_deadline)
        self.assertEqual(self.t_overdue.ft_task_age, 0)
        self.assertEqual(self.t_overdue_old.ft_task_age, 10)
        # ft_pms_planning_workflow stamps the original deadline on create.
        for task in (self.t_overdue, self.t_overdue_old, self.t_future,
                     self.t_closed, self.t_other):
            self.assertEqual(task.pwf_original_deadline, task.date_deadline,
                             task.name)
        # The frozen figure of the completed fixture.
        self.assertEqual(self.t_closed.ft_historical_overdue_days, 7)
        # Open tasks carry nothing.
        self.assertEqual(self.t_overdue.ft_historical_overdue_days, 0)

    # ------------------------------------------------------------------
    # filter options
    # ------------------------------------------------------------------
    def test_filter_options_lists_only_amc_projects(self):
        options = self.Dashboard.get_filter_options()
        self.assertEqual(list(options), ['projects'])
        projects = options['projects']
        ids = [p['id'] for p in projects]
        self.assertIn(self.amc.id, ids)
        self.assertIn(self.amc_other.id, ids)
        self.assertNotIn(self.general.id, ids)
        self.assertEqual(
            [p['name'] for p in projects],
            sorted((p['name'] for p in projects), key=str.lower))
        self.assertLess(ids.index(self.amc.id), ids.index(self.amc_other.id))
        for project in projects:
            self.assertEqual(set(project), {'id', 'name'})

    def test_filter_options_skip_archived_amc_projects(self):
        self.amc_other.write({'active': False})
        ids = [p['id'] for p in self.Dashboard.get_filter_options()['projects']]
        self.assertIn(self.amc.id, ids)
        self.assertNotIn(self.amc_other.id, ids)

    # ------------------------------------------------------------------
    # default view (open tasks only)
    # ------------------------------------------------------------------
    def test_default_rows_and_kpis_for_one_project(self):
        data = self._data(project_id=self.amc.id)
        self.assertEqual(data['today'], fields.Date.to_string(self.today))
        self.assertEqual(set(data), {'kpis', 'rows', 'today'})

        rows = data['rows']
        # Most overdue first, oldest among equals; the two rows with no
        # overdue figure come last, in either order.
        self.assertEqual(self._ids(rows[:2]),
                         [self.t_overdue_old.id, self.t_overdue.id])
        self.assertEqual(set(self._ids(rows[2:])),
                         {self.t_future.id, self.t_no_deadline.id})
        self.assertEqual(data['kpis'], {
            'total_tasks': 4,
            'overdue_tasks': 2,
            'overdue_days': 10,
            'projects': 1,
        })

    def test_row_fields(self):
        data = self._data(project_id=self.amc.id)
        row = self._row(data, self.t_overdue)
        self.assertEqual(row, {
            'id': self.t_overdue.id,
            'project_id': self.amc.id,
            'project_name': 'AMC Overdue Contract A',
            'task_name': self._task_title('Overdue 5 days'),
            'assignees': ', '.join(sorted((self.pm | self.dev).mapped('name'))),
            'stage': 'AMC Overdue Working',
            'is_closed': False,
            'original_deadline': self._day(-5),
            'deadline': self._day(-5),
            'completed_on': None,
            'total_days': 0,
            'overdue_days': 5,
        })

        old = self._row(data, self.t_overdue_old)
        # Created without assignees: Odoo defaults user_ids to the creator,
        # so the column mirrors whatever the record carries rather than ''.
        self.assertEqual(old['assignees'], ', '.join(
            self.t_overdue_old.user_ids.mapped('name')))
        self.assertEqual(old['total_days'], 10)
        self.assertEqual(old['overdue_days'], 5)

        future = self._row(data, self.t_future)
        self.assertEqual(future['deadline'], self._day(1))
        self.assertEqual(future['original_deadline'], self._day(1))
        self.assertIsNone(future['overdue_days'])

        none = self._row(data, self.t_no_deadline)
        self.assertIsNone(none['deadline'])
        self.assertIsNone(none['original_deadline'])
        self.assertIsNone(none['overdue_days'])

    def test_due_today_is_not_overdue(self):
        task = self._task('Due today', deadline=0)
        row = self._row(self._data(project_id=self.amc.id), task)
        self.assertEqual(row['deadline'], self._day(0))
        self.assertIsNone(row['overdue_days'])

    def test_closed_archived_and_general_tasks_excluded_by_default(self):
        data = self._data()
        ids = self._ids(data['rows'])
        self.assertIn(self.t_overdue.id, ids)
        self.assertIn(self.t_other.id, ids)
        self.assertNotIn(self.t_closed.id, ids)
        self.assertNotIn(self.t_archived.id, ids)
        self.assertNotIn(self.t_general.id, ids)
        self.assertFalse([r for r in data['rows'] if r['project_id'] == self.general.id])
        self.assertFalse([r for r in data['rows'] if r['is_closed']])

    def test_unfiltered_is_consistent_and_sorted(self):
        data = self._data()
        self._assert_kpis_match_rows(data)
        self._assert_sorted(data['rows'])
        # Both AMC projects created here are counted.
        self.assertGreaterEqual(data['kpis']['projects'], 2)
        self.assertEqual(self._row(data, self.t_other)['overdue_days'], 2)

    # ------------------------------------------------------------------
    # original deadline
    # ------------------------------------------------------------------
    def test_open_task_overdue_counts_from_original_deadline(self):
        # Pushing the deadline out to next week does not shrink the figure.
        self._revise_deadline(self.t_overdue, 7)
        self.assertEqual(self.t_overdue.pwf_original_deadline, self._noon_utc(-5))
        self.assertEqual(self.t_overdue.date_deadline, self._noon_utc(7))
        row = self._row(self._data(project_id=self.amc.id), self.t_overdue)
        self.assertEqual(row['original_deadline'], self._day(-5))
        self.assertEqual(row['deadline'], self._day(7))
        self.assertEqual(row['overdue_days'], 5)

    def test_task_without_original_deadline_falls_back_to_current(self):
        # A task from before deadline tracking that the hook could not fill.
        self.t_overdue.write({'pwf_original_deadline': False})
        self.assertFalse(self.t_overdue.pwf_original_deadline)
        self.assertEqual(self.t_overdue.ft_overdue_reference_deadline(),
                         self.t_overdue.date_deadline)
        row = self._row(self._data(project_id=self.amc.id), self.t_overdue)
        self.assertEqual(row['original_deadline'], self._day(-5))
        self.assertEqual(row['overdue_days'], 5)

    def test_original_deadline_lock_blocks_a_change_by_a_user(self):
        task = self.t_overdue.with_user(self.pm)
        self.assertTrue(task.pwf_original_deadline)
        with self.assertRaises(UserError):
            task.write({'pwf_original_deadline': self._noon_utc(3)})
        with self.assertRaises(UserError):
            task.write({'pwf_original_deadline': False})
        # Re-sending the same value is not a change and goes through.
        task.write({'pwf_original_deadline': task.pwf_original_deadline})
        self.assertEqual(self.t_overdue.pwf_original_deadline, self._noon_utc(-5))
        # The superuser (system code, the install hook) is not locked out.
        self.t_overdue.write({'pwf_original_deadline': self._noon_utc(-6)})
        self.assertEqual(self.t_overdue.pwf_original_deadline, self._noon_utc(-6))

    def test_original_deadline_lock_allows_the_first_set(self):
        # Direct fill of an empty original deadline by a plain user.
        task = self.t_no_deadline.with_user(self.pm)
        self.assertFalse(task.pwf_original_deadline)
        task.write({'pwf_original_deadline': self._noon_utc(2)})
        self.assertEqual(self.t_no_deadline.pwf_original_deadline,
                         self._noon_utc(2))

        # The lazy first set in ft_pms_planning_workflow's write hook: giving
        # a deadline to a task that never had one stamps the original from
        # that same write (a User Story, so no same-day rule applies).
        other = self._task('No deadline, set later', deadline=None,
                           task_type='user_story')
        self.assertFalse(other.pwf_original_deadline)
        other.with_user(self.pm).write({'date_deadline': self._noon_utc(3)})
        self.assertEqual(other.pwf_original_deadline, self._noon_utc(3))

    # ------------------------------------------------------------------
    # filters
    # ------------------------------------------------------------------
    def test_project_filter(self):
        data_a = self._data(project_id=self.amc.id)
        self.assertEqual({r['project_id'] for r in data_a['rows']}, {self.amc.id})
        self.assertEqual(data_a['kpis']['projects'], 1)

        data_b = self._data(project_id=self.amc_other.id)
        self.assertEqual(self._ids(data_b['rows']), [self.t_other.id])
        self.assertEqual(data_b['kpis'], {
            'total_tasks': 1, 'overdue_tasks': 1,
            'overdue_days': 2, 'projects': 1,
        })

        # Only AMC projects are in scope: picking a General project, even by
        # id, yields nothing rather than its tasks.
        data_g = self._data(project_id=self.general.id)
        self.assertEqual(data_g['rows'], [])
        self.assertEqual(data_g['kpis'], {
            'total_tasks': 0, 'overdue_tasks': 0,
            'overdue_days': 0, 'projects': 0,
        })

    def test_manager_filter(self):
        """manager_id (the dashboard's Project Manager picker) keeps the tasks
        of the projects that res.users runs — project.project.user_id — and
        nothing else; it composes with project_id and arrives as a string
        from the dashboard."""
        other_pm = new_test_user(
            self.env, 'amc_overdue_pm2', email='overdue_pm2@example.com',
            groups='base.group_user,project.group_project_user')
        other_proj = self._make_project('AMC Overdue Contract C', 'amc',
                                        user_id=other_pm.id)
        self.working.write({'project_ids': [Command.link(other_proj.id)]})
        t_mgr = self._task('Other manager, overdue 3 days', deadline=-3,
                           project=other_proj)

        # Every fixture project is run by self.pm, so its rows are all there
        # and the other manager's task is not.
        data_pm = self._data(manager_id=self.pm.id)
        self._assert_kpis_match_rows(data_pm)
        ids = self._ids(data_pm['rows'])
        self.assertIn(self.t_overdue.id, ids)
        self.assertIn(self.t_other.id, ids)
        self.assertNotIn(t_mgr.id, ids)
        for row in data_pm['rows']:
            project = self.env['project.project'].browse(row['project_id'])
            self.assertEqual(project.user_id, self.pm)

        # The other manager runs exactly one AMC project with one task. The
        # id is sent as a string, the way the dashboard's picker holds it.
        data_other = self._data(manager_id=str(other_pm.id))
        self.assertEqual(self._ids(data_other['rows']), [t_mgr.id])
        self.assertEqual(data_other['kpis'], {
            'total_tasks': 1, 'overdue_tasks': 1,
            'overdue_days': 3, 'projects': 1,
        })

        # Composes with project_id: a project the manager does not run
        # yields nothing, the one they run yields the same single row.
        self.assertEqual(
            self._data(project_id=self.amc.id, manager_id=other_pm.id)['rows'],
            [])
        self.assertEqual(
            self._ids(self._data(project_id=other_proj.id,
                                 manager_id=other_pm.id)['rows']),
            [t_mgr.id])

        # A manager with no AMC project (the developer) sees an empty table,
        # not an error.
        self.assertEqual(self._data(manager_id=self.dev.id)['rows'], [])

    def test_include_closed(self):
        data = self._data(project_id=self.amc.id, include_closed=True)
        rows = data['rows']
        # The closed task is 7 days late (deadline -10, closed -3) and so
        # outranks the two 5-day rows.
        self.assertEqual(self._ids(rows[:3]), [
            self.t_closed.id, self.t_overdue_old.id, self.t_overdue.id])
        closed = self._row(data, self.t_closed)
        self.assertTrue(closed['is_closed'])
        self.assertEqual(closed['stage'], 'Completed')
        self.assertEqual(closed['overdue_days'], 7)
        self.assertEqual(closed['completed_on'], self._day(-3))
        self.assertEqual(closed['original_deadline'], self._day(-10))
        # Created today, completed "3 days ago": the age never goes negative.
        self.assertEqual(closed['total_days'], 0)
        self.assertEqual(data['kpis'], {
            'total_tasks': 5,
            'overdue_tasks': 3,
            'overdue_days': 17,
            'projects': 1,
        })
        # Archived tasks stay out even with closed ones in.
        self.assertNotIn(self.t_archived.id, self._ids(rows))

    def test_closed_task_age_stops_at_completion(self):
        task = self._task('Old and closed late', deadline=-10)
        self._age(task, 30)
        self._complete(task, -3)
        row = self._row(
            self._data(project_id=self.amc.id, include_closed=True), task)
        self.assertEqual(row['total_days'], 27)
        self.assertEqual(row['overdue_days'], 7)

    def test_closed_task_without_date_end_counts_to_today(self):
        # Re-dating the completion re-stamps the frozen figure, and a missing
        # completion date means "now".
        self.t_closed.write({'date_end': False})
        self.assertEqual(self.t_closed.ft_historical_overdue_days, 10)
        row = self._row(
            self._data(project_id=self.amc.id, include_closed=True), self.t_closed)
        self.assertEqual(row['overdue_days'], 10)
        self.assertIsNone(row['completed_on'])

    def test_closed_on_time_has_no_overdue_days(self):
        task = self._task('Closed on time', deadline=-4, stage=self.completed)
        task.write({'date_end': self._noon_utc(-4)})
        self.assertEqual(task.ft_historical_overdue_days, 0)
        row = self._row(
            self._data(project_id=self.amc.id, include_closed=True), task)
        self.assertTrue(row['is_closed'])
        self.assertIsNone(row['overdue_days'])

    def test_cancelled_tasks_are_never_listed(self):
        task = self._task('Cancelled, overdue 5 days', deadline=-5)
        task.write({'state': '1_canceled'})
        self.assertTrue(task.is_closed)
        self.assertEqual(task.ft_historical_overdue_days, 0)
        for filters in ({}, {'include_closed': True},
                        {'include_closed': True, 'overdue_only': True}):
            data = self._data(project_id=self.amc.id, **filters)
            self.assertNotIn(task.id, self._ids(data['rows']), filters)
        # Still in the table once it is not cancelled any more.
        task.write({'state': '01_in_progress'})
        self.assertIn(task.id, self._ids(self._data(project_id=self.amc.id)['rows']))

    def test_overdue_only(self):
        data = self._data(project_id=self.amc.id, overdue_only=True)
        self.assertEqual(self._ids(data['rows']),
                         [self.t_overdue_old.id, self.t_overdue.id])
        self.assertTrue(all(r['overdue_days'] for r in data['rows']))
        self.assertEqual(data['kpis'], {
            'total_tasks': 2,
            'overdue_tasks': 2,
            'overdue_days': 10,
            'projects': 1,
        })

    def test_overdue_only_with_closed(self):
        data = self._data(project_id=self.amc.id, overdue_only=True,
                          include_closed=True)
        self.assertEqual(self._ids(data['rows']), [
            self.t_closed.id, self.t_overdue_old.id, self.t_overdue.id])
        self.assertEqual(data['kpis']['overdue_days'], 17)

    def test_filters_accept_missing_and_none(self):
        # '' is what the dashboard's header pickers hold for "all".
        for filters in (None, {},
                        {'project_id': None, 'manager_id': None,
                         'include_closed': None, 'overdue_only': None},
                        {'project_id': '', 'manager_id': ''}):
            data = self.Dashboard.get_dashboard_data(filters)
            self._assert_kpis_match_rows(data)
            self.assertIn(self.t_overdue.id, self._ids(data['rows']))

    # ------------------------------------------------------------------
    # frozen figure at completion
    # ------------------------------------------------------------------
    def test_worked_example_original_10_revised_15_completed_17(self):
        """Original deadline D, revised to D+5, completed D+7: 7 days.

        Laid out relative to today: original -10, revised -5, completed -3.
        """
        task = self._task('Worked example, revised then completed', deadline=-10)
        self._revise_deadline(task, -5)
        self.assertEqual(task.pwf_original_deadline, self._noon_utc(-10))
        self.assertEqual(task.date_deadline, self._noon_utc(-5))
        self.assertEqual(task.ft_historical_overdue_days, 0)

        self._complete(task, -3)
        self.assertEqual(task.state, '1_done')
        self.assertEqual(task.ft_historical_overdue_days, 7)

        data = self._data(project_id=self.amc.id, include_closed=True)
        row = self._row(data, task)
        self.assertEqual(row['overdue_days'], 7)
        self.assertEqual(row['original_deadline'], self._day(-10))
        self.assertEqual(row['deadline'], self._day(-5))
        self.assertEqual(row['completed_on'], self._day(-3))

        # Unrelated edits later on do not touch the figure, and neither does
        # a further deadline change on the completed task.
        task.write({'name': self._task_title('Worked example, renamed')})
        task.with_context(skip_ft_deadline_validation=True).write(
            {'date_deadline': self._noon_utc(-1)})
        self.assertEqual(task.ft_historical_overdue_days, 7)
        row = self._row(self._data(project_id=self.amc.id, include_closed=True), task)
        self.assertEqual(row['overdue_days'], 7)

    def test_frozen_figure_does_not_grow_with_time(self):
        """Viewed weeks later, a completed task still shows the same figure."""
        task = self._task('Completed late, viewed later', deadline=-10)
        self._complete(task, -3)
        later = self.today + timedelta(days=40)

        def fake_today(record, timestamp=None):
            return later

        with patch.object(fields.Date, 'context_today', staticmethod(fake_today)):
            self.env.invalidate_all()
            data = self._data(project_id=self.amc.id, include_closed=True)
            self.assertEqual(data['today'], fields.Date.to_string(later))
            row = self._row(data, task)
            self.assertEqual(row['overdue_days'], 7)
            self.assertEqual(row['total_days'], 0)
            # Whereas an open task keeps accumulating.
            self.assertEqual(self._row(data, self.t_overdue)['overdue_days'], 45)
        self.env.invalidate_all()

    def test_reopened_task_keeps_figure_until_completed_again(self):
        task = self._task('Reopened then completed again', deadline=-10)
        self._complete(task, -3)
        self.assertEqual(task.ft_historical_overdue_days, 7)

        # Back to work (su: the reopen wizard's own write is sudo too).
        task.write({'stage_id': self.working.id})
        self.assertEqual(task.state, '01_in_progress')
        self.assertFalse(task.is_closed)
        # Not reset on reopen: the last completion's figure is kept ...
        self.assertEqual(task.ft_historical_overdue_days, 7)
        # ... but the open row counts live again, from the original deadline.
        row = self._row(self._data(project_id=self.amc.id), task)
        self.assertEqual(row['overdue_days'], 10)
        self.assertIsNone(row['completed_on'])

        # Completed again today: 10 days past the original deadline.
        self._complete(task)
        self.assertEqual(task.state, '1_done')
        self.assertEqual(task.ft_historical_overdue_days, 10)
        row = self._row(self._data(project_id=self.amc.id, include_closed=True), task)
        self.assertEqual(row['overdue_days'], 10)
        self.assertEqual(row['completed_on'], self._day(0))

    def test_task_created_completed_is_stamped(self):
        task = self._task('Born completed, 4 days late', deadline=-4,
                          stage=self.completed)
        self.assertEqual(task.state, '1_done')
        # Completed on creation day (today): 4 days past its deadline.
        self.assertEqual(task.ft_historical_overdue_days, 4)

    def test_freeze_helper_is_a_no_op_on_open_tasks(self):
        self.t_overdue._ft_amc_freeze_overdue()
        self.assertEqual(self.t_overdue.ft_historical_overdue_days, 0)
        self.assertEqual(
            self.t_closed._ft_amc_overdue_days_between(
                self._noon_utc(-10), self._noon_utc(-3)), 7)
        self.assertEqual(
            self.t_closed._ft_amc_overdue_days_between(
                self._noon_utc(-3), self._noon_utc(-10)), 0)
        self.assertEqual(
            self.t_closed._ft_amc_overdue_days_between(False, self._noon_utc(-3)), 0)

    # ------------------------------------------------------------------
    # install hook
    # ------------------------------------------------------------------
    def _track_deadline(self, task, old, new, days_ago):
        """A chatter tracking row of date_deadline, as the mail module would
        have written it ``days_ago`` days ago (tracking is disabled in the
        test env, so it is written by hand)."""
        message = self.env['mail.message'].create({
            'model': 'project.task',
            'res_id': task.id,
            'message_type': 'notification',
            'body': 'deadline changed',
        })
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE mail_message SET create_date = create_date - %s::interval "
            "WHERE id = %s", ('%s days' % days_ago, message.id))
        message.invalidate_recordset()
        field = self.env['ir.model.fields']._get('project.task', 'date_deadline')
        return self.env['mail.tracking.value'].create({
            'mail_message_id': message.id,
            'field_id': field.id,
            'old_value_datetime': old,
            'new_value_datetime': new,
        })

    def test_hook_backfills_original_deadline_and_frozen_figure(self):
        # (a) A completed task from before deadline tracking: no original
        #     deadline, but the chatter shows the deadline was moved twice
        #     (-12 -> -8, then -8 -> -4). The earliest "old value" wins.
        tracked = self._task('Pre-tracking, moved twice', deadline=-4,
                             stage=self.completed)
        tracked.write({'date_end': self._noon_utc(-3)})
        tracked.write({'pwf_original_deadline': False})
        self._track_deadline(tracked, self._noon_utc(-12), self._noon_utc(-8), 9)
        self._track_deadline(tracked, self._noon_utc(-8), self._noon_utc(-4), 5)
        # (b) A completed task with no tracking at all: current deadline.
        plain = self._task('Pre-tracking, never moved', deadline=-6,
                           stage=self.completed)
        plain.write({'date_end': self._noon_utc(-3),
                     'pwf_original_deadline': False})
        # (c) An original deadline already set is never overwritten, however
        #     the chatter reads.
        kept = self._task('Original already known', deadline=-4)
        self._track_deadline(kept, self._noon_utc(-20), self._noon_utc(-4), 2)
        # (d) Completed with no date_end at all: date_last_stage_update.
        no_end = self._task('Completed, no end date', deadline=-5,
                            stage=self.completed)
        no_end.write({'date_end': False})
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE project_task SET date_last_stage_update = %s, "
            "ft_historical_overdue_days = 0 WHERE id = %s",
            (self._noon_utc(-2), no_end.id))
        # Stale figures everywhere, as on a database upgraded from 19.0.1.0.0.
        self.env.cr.execute(
            "UPDATE project_task SET ft_historical_overdue_days = 0 "
            "WHERE id IN %s", (tuple((tracked | plain | self.t_closed).ids),))
        self.env['project.task'].invalidate_model()

        self.assertFalse(tracked.pwf_original_deadline)
        self.assertFalse(plain.pwf_original_deadline)
        self.assertEqual(tracked.ft_historical_overdue_days, 0)

        filled = backfill_original_deadlines(self.env)
        self.assertGreaterEqual(filled, 2)
        self.assertEqual(tracked.pwf_original_deadline, self._noon_utc(-12))
        self.assertEqual(plain.pwf_original_deadline, self._noon_utc(-6))
        self.assertEqual(kept.pwf_original_deadline, self._noon_utc(-4))
        self.assertFalse(self.t_no_deadline.pwf_original_deadline)

        changed = backfill_historical_overdue(self.env)
        self.assertGreaterEqual(changed, 3)
        self.assertEqual(tracked.ft_historical_overdue_days, 9)   # -12 -> -3
        self.assertEqual(plain.ft_historical_overdue_days, 3)     # -6 -> -3
        self.assertEqual(self.t_closed.ft_historical_overdue_days, 7)
        self.assertEqual(no_end.ft_historical_overdue_days, 3)    # -5 -> -2
        self.assertEqual(self.t_overdue.ft_historical_overdue_days, 0)

        # The board reads the backfilled figures.
        data = self._data(project_id=self.amc.id, include_closed=True)
        self.assertEqual(self._row(data, tracked)['overdue_days'], 9)
        self.assertEqual(self._row(data, tracked)['original_deadline'], self._day(-12))
        self.assertEqual(self._row(data, plain)['overdue_days'], 3)

        # Running it all again changes nothing.
        post_init_hook(self.env)
        self.assertEqual(tracked.pwf_original_deadline, self._noon_utc(-12))
        self.assertEqual(tracked.ft_historical_overdue_days, 9)
        self.assertEqual(backfill_historical_overdue(self.env), 0)

    # ------------------------------------------------------------------
    # access
    # ------------------------------------------------------------------
    def test_amc_manager_can_read_the_board(self):
        Dashboard = self.Dashboard.with_user(self.amc_manager)
        ids = [p['id'] for p in Dashboard.get_filter_options()['projects']]
        self.assertIn(self.amc.id, ids)
        self.assertNotIn(self.general.id, ids)
        data = Dashboard.get_dashboard_data({'project_id': self.amc.id})
        self._assert_kpis_match_rows(data)
        self.assertFalse([r for r in data['rows'] if r['project_id'] != self.amc.id])
