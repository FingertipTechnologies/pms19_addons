from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, new_test_user, tagged

from odoo.addons.ft_pms_planning_workflow.models.planner import (
    compute_avg_daily_effort, effort_color, initials_of, resolve_range,
    split_daily_hours, week_working_days, working_days_between,
)
from odoo.addons.ft_sprint_management.models.week_utils import (
    local_day_bounds, monday_of,
)

# A Tuesday.
TODAY = date(2026, 10, 13)


@tagged('post_install', '-at_install')
class TestPlannerHelpers(TransactionCase):

    def test_effort_color_boundaries(self):
        self.assertEqual(effort_color(None), 'none')
        self.assertEqual(effort_color(0.0), 'grey')
        self.assertEqual(effort_color(3.99), 'grey')
        self.assertEqual(effort_color(4), 'yellow')
        self.assertEqual(effort_color(5.99), 'yellow')
        self.assertEqual(effort_color(6), 'green')
        self.assertEqual(effort_color(8), 'green')
        self.assertEqual(effort_color(8.01), 'red')

    def test_resolve_range(self):
        def check(key, start, end):
            date_from, date_to, _key = resolve_range(key, TODAY)
            self.assertEqual((date_from, date_to), (start, end), key)

        check('next_5', TODAY, date(2026, 10, 17))
        check('next_15', TODAY, date(2026, 10, 27))
        check('next_60', TODAY, TODAY + timedelta(days=59))
        check('last_5', date(2026, 10, 9), TODAY)
        check('last_30', TODAY - timedelta(days=29), TODAY)
        check('range_15', date(2026, 9, 28), date(2026, 10, 28))
        check('this_week', date(2026, 10, 12), date(2026, 10, 18))
        check('this_month', date(2026, 10, 1), date(2026, 10, 31))
        check('this_quarter', date(2026, 10, 1), date(2026, 12, 31))
        self.assertEqual(
            resolve_range('this_quarter', date(2026, 2, 3))[:2],
            (date(2026, 1, 1), date(2026, 3, 31)))
        # Unknown / missing keys fall back to next_60 (the default).
        self.assertEqual(resolve_range('bogus', TODAY),
                         (TODAY, TODAY + timedelta(days=59), 'next_60'))
        self.assertEqual(resolve_range(None, TODAY)[2], 'next_60')
        self.assertEqual(resolve_range('next_7', TODAY)[2], 'next_60')

    def test_resolve_custom_range(self):
        self.assertEqual(
            resolve_range('custom', TODAY, '2026-10-01', '2026-10-05'),
            (date(2026, 10, 1), date(2026, 10, 5), 'custom'))
        # Reversed bounds are swapped.
        self.assertEqual(
            resolve_range('custom', TODAY, date(2026, 10, 5), date(2026, 10, 1)),
            (date(2026, 10, 1), date(2026, 10, 5), 'custom'))
        # At most 180 days.
        start, end, key = resolve_range('custom', TODAY, '2026-01-01', '2027-12-31')
        self.assertEqual((start, end, key),
                         (date(2026, 1, 1), date(2026, 1, 1) + timedelta(days=179),
                          'custom'))
        # Missing / invalid bounds fall back to the default range.
        self.assertEqual(resolve_range('custom', TODAY, False, '2026-10-05')[2],
                         'next_60')
        self.assertEqual(resolve_range('custom', TODAY, 'nope', '2026-10-05')[2],
                         'next_60')

    def test_working_days(self):
        self.assertEqual(working_days_between(date(2026, 10, 12), date(2026, 10, 18)), 5)
        self.assertEqual(working_days_between(date(2026, 10, 17), date(2026, 10, 18)), 0)
        self.assertEqual(working_days_between(date(2026, 10, 12), date(2026, 10, 12)), 1)
        self.assertEqual(working_days_between(date(2026, 10, 13), date(2026, 10, 23)), 9)
        self.assertEqual(working_days_between(date(2026, 10, 12), date(2026, 10, 25)), 10)
        self.assertEqual(working_days_between(date(2026, 10, 18), date(2026, 10, 12)), 0)
        self.assertEqual(working_days_between(None, date(2026, 10, 12)), 0)

    def test_allocation_helpers(self):
        self.assertEqual(split_daily_hours(20, 1), 4.0)
        self.assertEqual(split_daily_hours(10, 2), 1.0)
        self.assertEqual(split_daily_hours(10, 0), 0.0)
        days = week_working_days(date(2026, 10, 12))
        self.assertEqual(days[0], date(2026, 10, 12))
        self.assertEqual(days[-1], date(2026, 10, 16))
        self.assertTrue(all(d.weekday() < 5 for d in days))
        self.assertEqual(initials_of('Ada Lovelace'), 'AL')
        self.assertEqual(initials_of('Ada Byron Lovelace'), 'AL')
        self.assertEqual(initials_of('Ada'), 'AD')
        self.assertEqual(initials_of(''), '?')

    def test_avg_daily_effort_cases(self):
        self.assertEqual(compute_avg_daily_effort(100, 10, False, TODAY),
                         (0.0, 'no_end_date'))
        self.assertEqual(compute_avg_daily_effort(100, 40, date(2026, 10, 10), TODAY),
                         (60.0, 'overdue'))
        self.assertEqual(compute_avg_daily_effort(10, 12, date(2026, 10, 30), TODAY),
                         (0.0, 'exhausted'))
        self.assertEqual(compute_avg_daily_effort(0, 0, date(2026, 10, 30), TODAY),
                         (0.0, 'no_estimate'))
        # Tue 13 .. Fri 23 Oct = 9 working days; 80 h remaining.
        self.assertEqual(compute_avg_daily_effort(100, 20, date(2026, 10, 23), TODAY),
                         (round(80 / 9, 2), 'ok'))
        # Ends today, today a Saturday: 0 working days counts as 1.
        saturday = date(2026, 10, 17)
        self.assertEqual(compute_avg_daily_effort(10, 4, saturday, saturday),
                         (6.0, 'ok'))


@tagged('post_install', '-at_install')
class TestPlannerRecords(TransactionCase):
    """Fixtures (all in the current week, Mon-Fri spread):

    Project P (PM admin):
      t_working   user A        20 h  Working    -> A 4 h/day
      t_shared    users A + B   10 h  Planned    -> A 1 h/day, B 1 h/day
      t_completed user B         5 h  Completed  -> B 1 h/day
    => P per day: A 5 h, B 2 h; total 7 h, 2 resources, avg 3.5 h.
    Project Q (PM user B):
      q_task      user A        15 h  Working    -> A 3 h/day
    => A's total per day: 8 h (green), collision P + Q.
    Project R (Closed stage):
      r_task      user B         5 h            -> B 1 h/day
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Planner = cls.env['ft.pms.planner']
        cls.today = fields.Date.context_today(cls.Planner)
        cls.Week = cls.env['qa_testapp.sprint']
        cls.this_monday = monday_of(cls.today)
        cls.week_prev, cls.week_cur, cls.week_next, cls.week_after = (
            cls.Week._ensure_weeks({cls.this_monday + timedelta(weeks=i)})
            for i in (-1, 0, 1, 2))

        TaskType = cls.env['project.task.type']
        cls.st_planned = TaskType.create({'name': 'Planned', 'sequence': 1})
        cls.st_working = TaskType.create({'name': 'Working', 'sequence': 2})
        cls.st_completed = TaskType.create(
            {'name': 'Completed', 'sequence': 9, 'fold': True})
        stages = (cls.st_planned | cls.st_working | cls.st_completed).ids

        cls.user_a = new_test_user(
            cls.env, login='pwf_planner_a', name='Alice Anders',
            groups='base.group_user,project.group_project_user')
        cls.user_b = new_test_user(
            cls.env, login='pwf_planner_b', name='Bob Brown',
            groups='base.group_user,project.group_project_user')
        cls.emp_a = cls.env['hr.employee'].create(
            {'name': 'Alice Anders', 'user_id': cls.user_a.id})

        cls.module = cls.env['cus.module'].create({'name': 'PWF Test Module'})

        def project(name, pm):
            return cls.env['project.project'].create({
                'name': name,
                'ft_project_type': 'general',
                'allow_billable': False,
                'allow_timesheets': True,
                'user_id': pm.id,
                'date': cls.today + timedelta(days=20),
                'type_ids': [(6, 0, stages)],
            })

        cls.project = project('PWF Planner Project P', cls.env.user)
        cls.project_q = project('PWF Planner Project Q', cls.user_b)
        cls.project_r = project('PWF Planner Project R (closed)', cls.env.user)

        # sudo: fixtures only — skips the PMS creation gates (deadline in the
        # future, single User Story assignee, ...) that are not under test.
        Task = cls.env['project.task'].sudo()

        def task(name, proj, stage, week, estimated, users,
                 priority='0', task_type='internal_call'):
            return Task.create({
                'name': name,
                'project_id': proj.id,
                'module_id': cls.module.id,
                'stage_id': stage.id,
                'sprint_id': week.id if week else False,
                'estimated': estimated,
                'priority': priority,
                'task_type': task_type,
                'user_ids': [(6, 0, users.ids)],
            }).with_env(cls.env)

        cls.t_working = task('PWF working task in this week', cls.project,
                             cls.st_working, cls.week_cur, 20.0, cls.user_a)
        cls.t_shared = task('PWF planned shared task this week', cls.project,
                            cls.st_planned, cls.week_cur, 10.0,
                            cls.user_a | cls.user_b)
        cls.t_completed = task('PWF completed task in this week', cls.project,
                               cls.st_completed, cls.week_cur, 5.0, cls.user_b)
        cls.t_overdue = task('PWF overdue task in last week', cls.project,
                             cls.st_working, cls.week_prev, 2.0, cls.user_a)
        cls.q_task = task('PWF task on project Q', cls.project_q,
                          cls.st_working, cls.week_cur, 15.0, cls.user_a)
        cls.r_task = task('PWF task on closed project R', cls.project_r,
                          cls.st_working, cls.week_cur, 5.0, cls.user_b)

        closed = cls.env['project.project.stage'].create(
            {'name': 'Closed', 'sequence': 999})
        # sudo: skip the stage gates; only "closed projects still show" is
        # under test.
        cls.project_r.sudo().write({'stage_id': closed.id})

        cls.env['account.analytic.line'].create({
            'name': 'PWF planner test entry',
            'project_id': cls.project.id,
            'task_id': cls.t_working.id,
            'employee_id': cls.emp_a.id,
            'date': cls.today,
            'unit_amount': 2.5,
        })

    # -- helpers -----------------------------------------------------------
    def _data(self, **filters):
        values = {
            'range_key': 'custom',
            'date_from': fields.Date.to_string(self.this_monday),
            'date_to': fields.Date.to_string(self.this_monday + timedelta(days=6)),
        }
        values.update(filters)
        return self.Planner.get_project_planner_data(values)

    def _row(self, data, project=None):
        project = project or self.project
        rows = [p for p in data['projects'] if p['id'] == project.id]
        self.assertEqual(len(rows), 1, project.name)
        return rows[0]

    def _absent(self, data, project):
        return not [p for p in data['projects'] if p['id'] == project.id]

    # -- project level ---------------------------------------------------
    def test_project_avg_fields(self):
        project = self.project
        expected = compute_avg_daily_effort(
            project.estimated, project.effective_hours, project.date, self.today)
        self.assertEqual(
            (project.pwf_avg_daily_effort, project.pwf_avg_effort_state),
            expected)
        self.assertEqual(
            project._pwf_avg_daily_effort_values(self.today)[project.id],
            expected)

    # -- project status: planned effort ------------------------------------
    def test_default_range_is_next_60(self):
        data = self.Planner.get_project_planner_data({})
        self.assertEqual(data['range_key'], 'next_60')
        self.assertEqual(len(data['days']), 60)
        self.assertEqual(data['date_from'], fields.Date.to_string(self.today))

    def test_custom_range_payload(self):
        data = self._data()
        self.assertEqual(data['range_key'], 'custom')
        self.assertEqual(len(data['days']), 7)
        self.assertEqual(data['days'][0]['date'],
                         fields.Date.to_string(self.this_monday))
        self.assertEqual([d['is_weekend'] for d in data['days']],
                         [False] * 5 + [True] * 2)

    def test_cumulative_average_per_resource(self):
        row = self._row(self._data())
        self.assertNotIn('employees', row)
        for cell in row['cells'][:5]:
            self.assertEqual(cell['kind'], 'planned')
            self.assertEqual(cell['total'], 7.0)       # 5 (A) + 2 (B)
            self.assertEqual(cell['resources'], 2)
            self.assertEqual(cell['value'], 3.5)       # 7 / 2
            self.assertEqual(cell['color'], 'grey')

    def test_weekend_has_no_load(self):
        data = self._data(mode='employee')
        row = self._row(data)
        for cell in row['cells'][5:]:
            self.assertIsNone(cell['value'])
            self.assertEqual(cell['color'], 'none')
            self.assertEqual(cell['kind'], 'none')
        for employee in row['employees']:
            for cell in employee['cells'][5:]:
                self.assertIsNone(cell['value'])

    def test_previous_week_not_spread_into_range(self):
        # t_overdue lives in last week: it must not reach this week's days.
        data = self._data(resource_ids=[self.user_a.id], mode='employee')
        emp = next(e for e in self._row(data)['employees']
                   if e['user_id'] == self.user_a.id)
        self.assertEqual(emp['cells'][0]['value'], 5.0)

    def test_assignee_split_and_collision(self):
        data = self._data(mode='employee')
        row = self._row(data)
        by_user = {e['user_id']: e for e in row['employees']}
        self.assertEqual(set(by_user), {self.user_a.id, self.user_b.id})
        emp_a, emp_b = by_user[self.user_a.id], by_user[self.user_b.id]
        self.assertEqual(emp_a['id'], self.user_a.id)
        self.assertEqual(emp_a['initials'], 'AA')
        self.assertEqual(emp_b['name'], 'Bob Brown')

        monday_a = emp_a['cells'][0]
        self.assertEqual(monday_a['value'], 5.0)     # 4 (own) + 1 (half of 10/5)
        self.assertEqual(monday_a['total'], 8.0)     # + 3 h on project Q
        self.assertEqual(monday_a['color'], 'green')  # colour = total
        self.assertTrue(monday_a['collision'])
        self.assertEqual(monday_a['other_projects'],
                         [{'name': self.project_q.display_name, 'hours': 3.0}])

        monday_b = emp_b['cells'][0]
        self.assertEqual(monday_b['value'], 2.0)     # 1 (shared) + 1 (completed)
        self.assertEqual(monday_b['total'], 3.0)     # + 1 h on closed project R
        self.assertTrue(monday_b['collision'])

        # Q's row for A: value is Q only, colour still A's total.
        q_a = next(e for e in self._row(data, self.project_q)['employees']
                   if e['user_id'] == self.user_a.id)
        self.assertEqual(q_a['cells'][0]['value'], 3.0)
        self.assertEqual(q_a['cells'][0]['color'], 'green')

    def test_collision_other_projects_hidden_names(self):
        # A reader who cannot open project Q still sees A's total, but Q is
        # reported as "Other projects".
        reader = new_test_user(
            self.env, login='pwf_planner_c', name='Carol Clark',
            groups='base.group_user,project.group_project_user')
        self.project.privacy_visibility = 'employees'
        self.project_q.privacy_visibility = 'followers'
        data = self.Planner.with_user(reader).get_project_planner_data({
            'range_key': 'custom',
            'date_from': fields.Date.to_string(self.this_monday),
            'date_to': fields.Date.to_string(self.this_monday + timedelta(days=4)),
            'project_ids': [self.project.id],
            'mode': 'employee',
        })
        emp_a = next(e for e in self._row(data)['employees']
                     if e['user_id'] == self.user_a.id)
        cell = emp_a['cells'][0]
        self.assertEqual(cell['total'], 8.0)
        names = [o['name'] for o in cell['other_projects']]
        if self.project_q.with_user(reader).has_access('read'):
            self.assertEqual(names, [self.project_q.display_name])
        else:
            self.assertEqual(names, ['Other projects'])

    def test_closed_project_included(self):
        data = self._data()
        row = self._row(data, self.project_r)
        self.assertEqual(row['cells'][0]['value'], 1.0)

    def test_filters(self):
        # Project filter.
        data = self._data(project_ids=[self.project_q.id])
        self.assertTrue(self._absent(data, self.project))
        self._row(data, self.project_q)

        # PM filter = project.user_id.
        data = self._data(pm_ids=[self.user_b.id])
        self.assertTrue(self._absent(data, self.project))
        self._row(data, self.project_q)

        # Resource filter = task assignment; only that user's load counts.
        data = self._data(resource_ids=[self.user_b.id])
        self.assertTrue(self._absent(data, self.project_q))
        cell = self._row(data)['cells'][0]
        self.assertEqual((cell['value'], cell['resources']), (2.0, 1))

        # A selected project without allocation in range is still shown.
        empty = self.env['project.project'].create({
            'name': 'PWF Planner Empty Project',
            'ft_project_type': 'general',
        })
        data = self._data(project_ids=[empty.id])
        row = self._row(data, empty)
        self.assertTrue(all(c['value'] is None for c in row['cells']))

    def test_options_cascade(self):
        data = self._data(project_ids=[self.project_q.id])
        resource_ids = {r['id'] for r in data['options']['resources']}
        self.assertEqual(resource_ids, {self.user_a.id})
        self.assertTrue(all('initials' in r for r in data['options']['resources']))

        data = self._data(resource_ids=[self.user_b.id])
        project_ids = {p['id'] for p in data['options']['projects']}
        self.assertIn(self.project.id, project_ids)
        self.assertIn(self.project_r.id, project_ids)
        self.assertNotIn(self.project_q.id, project_ids)

        data = self._data()
        project_ids = {p['id'] for p in data['options']['projects']}
        self.assertTrue({self.project.id, self.project_q.id,
                         self.project_r.id} <= project_ids)
        self.assertIn(self.user_b.id, {p['id'] for p in data['options']['pms']})

    def test_unscheduled_count(self):
        unscheduled = self.env['project.task'].sudo().create({
            'name': 'PWF unscheduled task no week',
            'project_id': self.project.id,
            'module_id': self.module.id,
            'estimated': 3.0,
            'task_type': 'internal_call',
            'user_ids': [(6, 0, self.user_a.ids)],
        })
        self.assertFalse(unscheduled.sprint_id)
        self.assertFalse(unscheduled.date_deadline)
        row = self._row(self._data())
        self.assertEqual(row['unscheduled_count'], 1)
        self.assertEqual(row['cells'][0]['total'], 7.0)

    def test_task_without_week_uses_deadline_week(self):
        task = self.env['project.task'].sudo().create({
            'name': 'PWF deadline only task next week',
            'project_id': self.project.id,
            'module_id': self.module.id,
            'estimated': 5.0,
            'task_type': 'internal_call',
            'user_ids': [(6, 0, self.user_b.ids)],
            'date_deadline': local_day_bounds(
                self.env, self.week_next.start_date + timedelta(days=2)),
        })
        task.with_context(ft_skip_week_sync=True).write({'sprint_id': False})
        data = self._data(
            date_from=fields.Date.to_string(self.week_next.start_date),
            date_to=fields.Date.to_string(self.week_next.start_date
                                          + timedelta(days=4)),
            project_ids=[self.project.id])
        cell = self._row(data)['cells'][0]
        self.assertEqual((cell['value'], cell['resources']), (1.0, 1))

    # -- task planner ------------------------------------------------------
    def _week(self, data, week):
        return next(w for w in data['weeks'] if w['id'] == week.id)

    def test_task_planner_starts_at_current_week(self):
        data = self.Planner.get_task_planner_data(
            {'project_id': self.project.id})
        self.assertEqual(data['project']['id'], self.project.id)
        self.assertEqual(data['status_filter'], 'open')
        self.assertEqual(len(data['weeks']), 6)
        self.assertEqual(data['weeks'][0]['id'], self.week_cur.id)
        self.assertTrue(data['weeks'][0]['is_current'])

        data = self.Planner.get_task_planner_data({
            'project_id': self.project.id,
            'focus_date': fields.Date.to_string(self.week_next.start_date),
        })
        self.assertEqual(data['weeks'][0]['id'], self.week_next.id)
        self.assertTrue(data['weeks'][0]['contains_focus'])

        data = self.Planner.get_task_planner_data(
            {'project_id': self.project.id, 'week_offset': -1})
        self.assertEqual(data['weeks'][0]['id'], self.week_prev.id)
        prev = self._week(data, self.week_prev)
        self.assertEqual([t['category'] for t in prev['tasks']], ['overdue'])

    def test_task_categories_by_stage_and_status_filter(self):
        def ids(status, **extra):
            data = self.Planner.get_task_planner_data(dict(
                {'project_id': self.project.id, 'status_filter': status}, **extra))
            return [(t['id'], t['category'])
                    for t in self._week(data, self.week_cur)['tasks']]

        self.assertEqual(ids('all'), [
            (self.t_shared.id, 'not_started'),
            (self.t_working.id, 'working'),
            (self.t_completed.id, 'completed'),
        ])
        self.assertEqual(ids('open'), [
            (self.t_shared.id, 'not_started'),
            (self.t_working.id, 'working'),
        ])
        self.assertEqual(ids('completed'), [(self.t_completed.id, 'completed')])
        # Legacy flag still understood.
        self.assertEqual(len(ids(None, show_completed=True)), 3)
        self.assertEqual(len(ids(None)), 2)

    def test_task_totals_include_actual(self):
        for status in ('open', 'completed', 'all'):
            data = self.Planner.get_task_planner_data(
                {'project_id': self.project.id, 'status_filter': status})
            totals = self._week(data, self.week_cur)['totals']
            self.assertEqual(totals['estimated'], 35.0, status)
            self.assertEqual(totals['open'], 30.0, status)
            self.assertEqual(totals['completed'], 5.0, status)
            self.assertEqual(totals['actual'], 2.5, status)
            self.assertEqual(totals['estimated_hhmm'], '35:00')
            self.assertEqual(totals['actual_hhmm'], '02:30')

        # Resource filter narrows the totals.
        data = self.Planner.get_task_planner_data(
            {'project_id': self.project.id, 'resource_ids': [self.user_b.id]})
        totals = self._week(data, self.week_cur)['totals']
        self.assertEqual(totals['estimated'], 15.0)
        self.assertEqual(totals['completed'], 5.0)

    def test_task_ordering_within_category(self):
        later = self.env['project.task'].sudo().create({
            'name': 'PWF second planned task this week',
            'project_id': self.project.id,
            'module_id': self.module.id,
            'stage_id': self.st_planned.id,
            'sprint_id': self.week_cur.id,
            'estimated': 1.0,
            'priority': '1',
        })
        data = self.Planner.get_task_planner_data(
            {'project_id': self.project.id})
        cur = self._week(data, self.week_cur)
        ids = [t['id'] for t in cur['tasks'] if t['category'] == 'not_started']
        # Same deadline (week Sunday): higher priority first.
        self.assertEqual(ids, [later.id, self.t_shared.id])

    # -- move ---------------------------------------------------------------
    def test_move_without_reason(self):
        task = self.t_shared
        # No reason argument at all.
        result = self.Planner.move_task_week(task.id, self.week_next.id)
        self.assertEqual(result, {'ok': True})
        self.assertEqual(task.sprint_id, self.week_next)
        # A blank reason is accepted and stored as empty.
        self.Planner.move_task_week(task.id, self.week_after.id, '   ')
        self.assertEqual(task.sprint_id, self.week_after)
        self.assertEqual(len(task.pwf_week_move_ids), 2)
        self.assertFalse(any(task.pwf_week_move_ids.mapped('reason')))
        self.assertTrue(task.pwf_original_deadline)
        self.assertFalse(any('Reason:' in (m.body or '') for m in task.message_ids))

    def test_move_same_week_rejected(self):
        with self.assertRaises(UserError):
            self.Planner.move_task_week(
                self.t_shared.id, self.week_cur.id, 'No change')

    def test_move_changes_deadline_and_sets_original_once(self):
        task = self.t_shared
        original = task.date_deadline
        self.assertTrue(original)
        result = self.Planner.move_task_week(
            task.id, self.week_next.id, '  Client asked to defer  ')
        self.assertEqual(result, {'ok': True})
        self.assertEqual(task.sprint_id, self.week_next)
        expected = task._deadline_for_week(self.week_next)
        self.assertEqual(task.date_deadline, expected)
        self.assertEqual(task.pwf_original_deadline, original)

        log = task.pwf_week_move_ids
        self.assertEqual(len(log), 1)
        self.assertEqual(log.from_week_id, self.week_cur)
        self.assertEqual(log.to_week_id, self.week_next)
        self.assertEqual(log.reason, 'Client asked to defer')
        self.assertEqual(log.deadline_at_move, original)
        self.assertEqual(log.new_deadline, expected)
        self.assertEqual(log.user_id, self.env.user)
        self.assertTrue(any('Client asked to defer' in (m.body or '')
                            for m in task.message_ids))

        # Still found in its new week by the planner.
        data = self.Planner.get_task_planner_data(
            {'project_id': self.project.id, 'status_filter': 'all'})
        self.assertIn(task.id, [t['id'] for t in
                                self._week(data, self.week_next)['tasks']])

        # Second move: original deadline is never overwritten.
        self.Planner.move_task_week(task.id, self.week_after.id, 'Again')
        self.assertEqual(task.date_deadline,
                         task._deadline_for_week(self.week_after))
        self.assertEqual(task.pwf_original_deadline, original)
        self.assertEqual(len(task.pwf_week_move_ids), 2)
        self.assertEqual(task.pwf_week_move_ids[0].deadline_at_move, expected)

    def test_move_testing_task_with_timesheets_outside_target_allowed(self):
        testing = self.env['project.task'].sudo().create({
            'name': 'PWF testing task this week',
            'project_id': self.project.id,
            'module_id': self.module.id,
            'stage_id': self.st_working.id,
            'sprint_id': self.week_cur.id,
            'estimated': 4.0,
            'task_type': 'testing',
        })
        self.env['account.analytic.line'].sudo().create({
            'name': 'PWF testing entry',
            'project_id': self.project.id,
            'task_id': testing.id,
            'employee_id': self.emp_a.id,
            'date': self.week_cur.start_date,
            'unit_amount': 1.0,
        })
        # Timesheets outside the target week no longer block the move.
        self.Planner.move_task_week(testing.id, self.week_next.id)
        self.assertEqual(testing.sprint_id, self.week_next)
        self.assertEqual(len(testing.pwf_week_move_ids), 1)
