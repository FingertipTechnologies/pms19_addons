"""Backend of the Project Status planner and the Task (week) Planner.

The two client actions ('ft_pms_project_planner', 'ft_pms_task_planner') draw
plain JSON built here, so every rule — the colour thresholds, the range
semantics, the allocation of planned effort, the task categories — lives in
Python and is unit tested.

The small pure helpers are module level on purpose: they take plain values
and return plain values, so tests can exercise the boundaries without any
records.
"""
import calendar
from collections import defaultdict
from datetime import date, timedelta

from babel.dates import format_date as babel_format_date
from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import babel_locale_parse, get_lang

from odoo.addons.ft_sprint_management.models.sprint import WEEK_STAGES
from odoo.addons.ft_sprint_management.models.week_utils import (
    hours_to_hhmm, local_day_bounds, monday_of, sunday_of, week_label,
)

DEFAULT_RANGE = 'next_60'
CUSTOM_RANGE = 'custom'
MAX_CUSTOM_DAYS = 180
RANGE_SIZES = (5, 10, 15, 30, 60)
RANGE_PREFIXES = ('next', 'last', 'range')
FIXED_RANGES = ('this_week', 'this_month', 'this_quarter')

# Hours per day.  v < 4 grey; 4 <= v < 6 yellow; 6 <= v <= 8 green; v > 8 red.
EFFORT_LOW = 4.0
EFFORT_OK = 6.0
EFFORT_HIGH = 8.0

# Planned effort of a task is spread over the Mon-Fri of its week.
WORKING_DAYS_PER_WEEK = 5

AVG_STATES = [
    ('ok', 'Normal'),
    ('no_end_date', 'No End Date'),
    ('overdue', 'Overdue'),
    ('exhausted', 'Budget Exhausted'),
    ('no_estimate', 'No Estimate'),
]

TASK_CATEGORIES = ('overdue', 'not_started', 'working', 'completed')
CATEGORY_ORDER = {name: index for index, name in enumerate(TASK_CATEGORIES)}

STATUS_FILTERS = ('open', 'completed', 'all')
DEFAULT_STATUS_FILTER = 'open'

DEFAULT_WEEK_COUNT = 6
MAX_WEEK_COUNT = 26


# ----------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------
def effort_color(value):
    """Colour key of a day's hours. ``None`` (no data) is 'none', not grey."""
    if value is None:
        return 'none'
    if value < EFFORT_LOW:
        return 'grey'
    if value < EFFORT_OK:
        return 'yellow'
    if value <= EFFORT_HIGH:
        return 'green'
    return 'red'


def _to_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return fields.Date.to_date(value)
    except (TypeError, ValueError):
        return None


def resolve_range(range_key, today, date_from=None, date_to=None):
    """(date_from, date_to, normalised_key) for a range key, both inclusive.

    next_N  = today .. today+N-1
    last_N  = today-N+1 .. today
    range_N = today-N .. today+N
    this_week Mon-Sun, this_month, this_quarter (calendar quarter).
    custom  = date_from .. date_to (swapped when reversed, at most
              MAX_CUSTOM_DAYS days long); missing/invalid dates fall back.
    Anything unknown falls back to DEFAULT_RANGE.
    """
    key = range_key or DEFAULT_RANGE
    if key == CUSTOM_RANGE:
        start, end = _to_date(date_from), _to_date(date_to)
        if not (start and end):
            return resolve_range(DEFAULT_RANGE, today)
        if end < start:
            start, end = end, start
        end = min(end, start + timedelta(days=MAX_CUSTOM_DAYS - 1))
        return start, end, key
    if key == 'this_week':
        return monday_of(today), sunday_of(today), key
    if key == 'this_month':
        last = calendar.monthrange(today.year, today.month)[1]
        return today.replace(day=1), today.replace(day=last), key
    if key == 'this_quarter':
        first_month = 3 * ((today.month - 1) // 3) + 1
        last_month = first_month + 2
        last = calendar.monthrange(today.year, last_month)[1]
        return (date(today.year, first_month, 1),
                date(today.year, last_month, last), key)
    prefix, _sep, size = key.partition('_')
    if prefix in RANGE_PREFIXES and size.isdigit() and int(size) in RANGE_SIZES:
        n = int(size)
        if prefix == 'next':
            return today, today + timedelta(days=n - 1), key
        if prefix == 'last':
            return today - timedelta(days=n - 1), today, key
        return today - timedelta(days=n), today + timedelta(days=n), key
    return resolve_range(DEFAULT_RANGE, today)


def working_days_between(d1, d2):
    """Number of Mon-Fri days from ``d1`` to ``d2``, both inclusive."""
    if not d1 or not d2 or d2 < d1:
        return 0
    total_days = (d2 - d1).days + 1
    weeks, remainder = divmod(total_days, 7)
    count = weeks * 5
    for offset in range(remainder):
        if (d1 + timedelta(days=weeks * 7 + offset)).weekday() < 5:
            count += 1
    return count


def compute_avg_daily_effort(estimated, spent, end_date, today):
    """(value, state) of the hours per working day a project still needs.

    remaining = estimated - spent; working days = Mon-Fri from today to the
    end date inclusive (an end date of today on a weekend counts as 1).
    """
    estimated = estimated or 0.0
    remaining = estimated - (spent or 0.0)
    if not end_date:
        return 0.0, 'no_end_date'
    if estimated <= 0:
        return 0.0, 'no_estimate'
    if end_date < today:
        # Overdue: the whole remaining budget is "due today". Never negative.
        return round(max(remaining, 0.0), 2), 'overdue'
    if remaining <= 0:
        return 0.0, 'exhausted'
    days = working_days_between(today, end_date) or 1
    return round(remaining / days, 2), 'ok'


def week_working_days(monday):
    """The Mon-Fri dates of the week opened by ``monday``."""
    return [monday + timedelta(days=i) for i in range(WORKING_DAYS_PER_WEEK)]


def split_daily_hours(estimated, assignee_count):
    """Planned hours per assignee per working day of a task's week.

    The estimate is split equally between the assignees, then spread evenly
    over Mon-Fri. No assignees -> 0 (nobody carries the load).
    """
    if not assignee_count:
        return 0.0
    return (estimated or 0.0) / assignee_count / WORKING_DAYS_PER_WEEK


def initials_of(name):
    """"Ada Lovelace" -> "AL"; "Ada" -> "AD"; '' -> '?'."""
    words = [w for w in (name or '').replace('.', ' ').split() if w[:1].isalnum()]
    if not words:
        return '?'
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


def _ids(values):
    """Clean a list of ids coming from the client."""
    if isinstance(values, (int, str)):
        values = [values]
    return [int(v) for v in (values or []) if v]


class FtPmsPlanner(models.AbstractModel):
    _name = 'ft.pms.planner'
    _description = 'PMS Planner Backend'

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------
    @api.model
    def _pwf_fmt(self, day, pattern):
        locale = babel_locale_parse(get_lang(self.env).code)
        return babel_format_date(day, pattern, locale=locale)

    @api.model
    def _pwf_accessible_projects(self):
        """Active, non-template projects the user can read (closed included)."""
        return self.env['project.project'].search(
            [('is_template', '=', False)], order='name, id')

    @api.model
    def _pwf_task_base_domain(self, project_ids=None, pm_ids=None,
                              resource_ids=None):
        domain = [
            ('project_id', '!=', False),
            ('project_id.is_template', '=', False),
            ('project_id.active', '=', True),
        ]
        if project_ids:
            domain.append(('project_id', 'in', project_ids))
        if pm_ids:
            domain.append(('project_id.user_id', 'in', pm_ids))
        if resource_ids:
            domain.append(('user_ids', 'in', resource_ids))
        return domain

    @api.model
    def _pwf_scheduled_domain(self, date_from, date_to):
        """Tasks whose allocated week overlaps [date_from, date_to].

        Allocated week = sprint_id; without one, the week of the deadline (so
        the deadline bounds are widened to the Monday/Sunday around the range).
        """
        low = local_day_bounds(self.env, monday_of(date_from))
        high = local_day_bounds(self.env, sunday_of(date_to), end_of_day=True)
        return [
            '|',
            '&', ('sprint_start_date', '<=', date_to),
                 ('sprint_end_date', '>=', date_from),
            '&', ('sprint_id', '=', False),
            '&', ('date_deadline', '>=', low),
                 ('date_deadline', '<=', high),
        ]

    @api.model
    def _pwf_task_monday(self, task):
        if task.sprint_start_date:
            return task.sprint_start_date
        if task.date_deadline:
            return monday_of(task._ft_local_date(task.date_deadline))
        return None

    @api.model
    def _pwf_user_option(self, user):
        return {'id': user.id, 'name': user.name or '',
                'initials': initials_of(user.name)}

    @api.model
    def _pwf_options(self, project_ids=None, resource_ids=None,
                     accessible=None):
        """Cascading filter options.

        projects: projects having tasks assigned to the selected resources
                  (all accessible projects when none is selected);
        resources: users assigned to tasks of the selected projects (all
                  internal users when no project is selected);
        pms: PMs of every accessible project.
        Selected values are always kept in their own option list.
        """
        Task = self.env['project.task']
        Users = self.env['res.users']
        project_ids = project_ids or []
        resource_ids = resource_ids or []
        if accessible is None:
            accessible = self._pwf_accessible_projects()

        projects = accessible
        if resource_ids:
            groups = Task._read_group(
                [('project_id', 'in', accessible.ids),
                 ('user_ids', 'in', resource_ids)],
                ['project_id'], [])
            keep = {project.id for (project,) in groups} | set(project_ids)
            projects = accessible.filtered(lambda p: p.id in keep)

        if project_ids:
            groups = Task._read_group(
                [('project_id', 'in', project_ids), ('user_ids', '!=', False)],
                ['user_ids'], [])
            user_ids = {user.id for (user,) in groups if user} | set(resource_ids)
            resources = Users.browse(sorted(user_ids)).exists()
        else:
            resources = Users.search([('share', '=', False)])
            if resource_ids:
                resources |= Users.browse(resource_ids).exists()
        resources = resources.sorted(lambda u: (u.name or '', u.id))
        pms = accessible.mapped('user_id').sorted(lambda u: (u.name or '', u.id))
        return {
            'projects': [{'id': p.id, 'name': p.display_name,
                          'initials': initials_of(p.name)} for p in projects],
            'pms': [self._pwf_user_option(u) for u in pms],
            'resources': [self._pwf_user_option(u) for u in resources],
        }

    @api.model
    def _pwf_legend(self):
        return [
            {'color': 'grey', 'label': _('Below 4 h')},
            {'color': 'yellow', 'label': _('4 h to under 6 h')},
            {'color': 'green', 'label': _('6 h to 8 h')},
            {'color': 'red', 'label': _('Above 8 h')},
            {'color': 'none', 'label': _('No planned work')},
        ]

    # ------------------------------------------------------------------
    # 1. Project Status (project planner)
    # ------------------------------------------------------------------
    @api.model
    def _pwf_allocate(self, tasks, days_in_range, only_users=None):
        """{project_id: {day: {user_id: hours}}} of planned effort.

        Each task's estimate is split equally between its assignees and
        spread evenly over the Mon-Fri of its allocated week; weekends never
        carry load. ``only_users`` keeps only those users' shares.
        """
        plan = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        for task in tasks:
            users = task.user_ids
            monday = self._pwf_task_monday(task)
            if not users or not monday:
                continue
            share = split_daily_hours(task.estimated, len(users))
            for day in week_working_days(monday):
                if day not in days_in_range:
                    continue
                for user in users:
                    if only_users is not None and user.id not in only_users:
                        continue
                    plan[task.project_id.id][day][user.id] += share
        return plan

    @api.model
    def get_project_planner_data(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)
        date_from, date_to, range_key = resolve_range(
            filters.get('range_key'), today,
            filters.get('date_from'), filters.get('date_to'))
        project_ids = _ids(filters.get('project_ids'))
        pm_ids = _ids(filters.get('pm_ids'))
        resource_ids = _ids(filters.get('resource_ids'))
        mode = 'employee' if filters.get('mode') == 'employee' else 'cumulative'
        Task = self.env['project.task']
        Project = self.env['project.project']
        status_filter = (
            'completed'
            if filters.get('status_filter') == 'completed'
            else 'all'
        )

        # "Completed" toggle (same rule as the Task list "Closed" filter and
        # the Task Planner): only tasks in a final stage feed the bars, the
        # employee rows and the unscheduled count; projects without such a
        # task in the range drop out. Collision load stays the TOTAL workload.
        status_domain = []
        if status_filter == 'completed':
            status_domain = [('stage_id', 'in', Task._ft_final_stage_ids())]

        days = []
        day = date_from
        while day <= date_to:
            days.append(day)
            day += timedelta(days=1)
        days_in_range = set(days)
        scheduled = self._pwf_scheduled_domain(date_from, date_to)

        # --- 1st search: the visible plan (normal record rules) ------------
        tasks = Task.search(
            self._pwf_task_base_domain(project_ids, pm_ids, resource_ids)
            + [('user_ids', '!=', False)] + scheduled + status_domain)
        plan = self._pwf_allocate(
            tasks, days_in_range,
            only_users=set(resource_ids) if resource_ids else None)

        shown_ids = set(tasks.project_id.ids)
        if project_ids:
            shown_ids |= set(project_ids)
        project_domain = [('id', 'in', list(shown_ids)),
                          ('is_template', '=', False)]
        if pm_ids:
            project_domain.append(('user_id', 'in', pm_ids))
        projects = Project.search(project_domain, order='name, id')

        # --- unscheduled tasks (no week, no deadline), one grouped query ---
        unscheduled = {}
        if projects:
            groups = Task._read_group(
                self._pwf_task_base_domain(projects.ids, None, resource_ids)
                + [('sprint_id', '=', False), ('date_deadline', '=', False)]
                + status_domain,
                ['project_id'], ['__count'])
            unscheduled = {project.id: count for project, count in groups}

        # --- 2nd search: collision totals across ALL projects ----------------
        load = {}
        readable_names = {}
        users = self.env['res.users']
        if mode == 'employee':
            user_ids = set()
            for by_day in plan.values():
                for per_user in by_day.values():
                    user_ids.update(per_user)
            users = self.env['res.users'].browse(sorted(user_ids))
            if user_ids:
                load, readable_names = self._pwf_collision_load(
                    user_ids, scheduled, days_in_range)

        avg_values = projects._pwf_avg_daily_effort_values(today)

        days_payload = [{
            'date': fields.Date.to_string(d),
            'day': str(d.day),
            'weekday': self._pwf_fmt(d, 'EEE'),
            'month': self._pwf_fmt(d, 'MMM'),
            'is_today': d == today,
            'is_weekend': d.weekday() >= 5,
            'week_label': week_label(d),
        } for d in days]

        projects_payload = []
        for project in projects:
            avg_value, avg_state = avg_values.get(project.id, (0.0, 'no_end_date'))
            by_day = plan.get(project.id, {})
            row = {
                'id': project.id,
                'name': project.display_name,
                'pm': ({'id': project.user_id.id, 'name': project.user_id.name,
                        'initials': initials_of(project.user_id.name)}
                       if project.user_id else False),
                'avg_daily_effort': (
                    avg_value if avg_state in ('ok', 'overdue') else None),
                'avg_state': avg_state,
                'unscheduled_count': unscheduled.get(project.id, 0),
                'cells': [self._pwf_cumulative_cell(d, by_day.get(d))
                          for d in days],
            }
            if mode == 'employee':
                row_user_ids = set()
                for per_user in by_day.values():
                    row_user_ids.update(per_user)
                row_users = users.filtered(
                    lambda u: u.id in row_user_ids).sorted(
                        lambda u: (u.name or '', u.id))
                row['employees'] = [{
                    'id': user.id,
                    'user_id': user.id,
                    'name': user.name or '',
                    'initials': initials_of(user.name),
                    'cells': [
                        self._pwf_employee_cell(
                            d, project.id,
                            (by_day.get(d) or {}).get(user.id),
                            load.get(user.id, {}).get(d, {}),
                            readable_names)
                        for d in days
                    ],
                } for user in row_users]
            projects_payload.append(row)

        return {
            'range_key': range_key,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'today': fields.Date.to_string(today),
            'days': days_payload,
            'projects': projects_payload,
            'options': self._pwf_options(project_ids, resource_ids),
            'legend': self._pwf_legend(),
        }

    @api.model
    def _pwf_collision_load(self, user_ids, scheduled, days_in_range):
        """({user_id: {day: {project_id: hours}}}, {project_id: name}).

        sudo: a user's TOTAL load must count every project, including the
        ones the reader cannot open. Only hours leave this method; names are
        given for projects the reader can read, the rest are reported as
        "Other projects" by the caller.
        """
        tasks = self.env['project.task'].sudo().search(
            [('project_id', '!=', False),
             ('project_id.is_template', '=', False),
             ('project_id.active', '=', True),
             ('user_ids', 'in', list(user_ids))] + scheduled)
        alloc = self._pwf_allocate(tasks, days_in_range, only_users=user_ids)
        load = defaultdict(lambda: defaultdict(dict))
        for project_id, by_day in alloc.items():
            for day, per_user in by_day.items():
                for user_id, hours in per_user.items():
                    load[user_id][day][project_id] = hours
        readable = self.env['project.project'].with_context(
            active_test=False).search([('id', 'in', list(alloc))])
        return load, {p.id: p.display_name for p in readable}

    @api.model
    def _pwf_cell(self, day, value, kind, tooltip, **extra):
        cell = {
            'date': fields.Date.to_string(day),
            'value': value,
            'kind': kind,
            'color': effort_color(value),
            'tooltip': tooltip,
        }
        cell.update(extra)
        return cell

    @api.model
    def _pwf_cumulative_cell(self, day, per_user):
        """Average planned hours per allocated resource on one project/day."""
        label = self._pwf_fmt(day, 'EEE d MMM')
        if day.weekday() >= 5 or not per_user:
            return self._pwf_cell(
                day, None, 'none', _('%s: no planned work', label),
                total=None, resources=0)
        total = sum(per_user.values())
        loaded = sum(1 for hours in per_user.values() if hours > 0)
        # Only 0-estimate tasks that day: allocated, but for 0 h.
        value = round(total / loaded, 2) if loaded else 0.0
        return self._pwf_cell(day, value, 'planned', _(
            '%(day)s: %(avg)s h per resource (%(total)s h planned for '
            '%(people)s)',
            day=label, avg=hours_to_hhmm(value), total=hours_to_hhmm(total),
            people=loaded), total=round(total, 2), resources=loaded)

    @api.model
    def _pwf_employee_cell(self, day, project_id, hours, user_load,
                           readable_names):
        """One user's planned hours on one project/day.

        value = hours on this project; colour = the user's TOTAL planned
        hours across all projects that day (collision).
        """
        label = self._pwf_fmt(day, 'EEE d MMM')
        if day.weekday() >= 5 or hours is None:
            return self._pwf_cell(
                day, None, 'none', _('%s: no planned work', label),
                total=None, other_projects=[], collision=False)
        value = round(hours, 2)
        others = defaultdict(float)
        other_label = _('Other projects')
        for other_id, other_hours in (user_load or {}).items():
            if other_id == project_id or not other_hours:
                continue
            others[readable_names.get(other_id) or other_label] += other_hours
        total = round(max(sum((user_load or {}).values()), hours), 2)
        other_projects = [
            {'name': name, 'hours': round(h, 2)}
            for name, h in sorted(others.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        loaded_projects = {
            pid for pid, h in (user_load or {}).items() if h > 0}
        if value > 0:
            loaded_projects.add(project_id)
        collision = len(loaded_projects) > 1
        tooltip = _('%(day)s: %(hours)s h on this project, %(total)s h in total',
                    day=label, hours=hours_to_hhmm(value),
                    total=hours_to_hhmm(total))
        cell = self._pwf_cell(day, value, 'planned', tooltip, total=total,
                              other_projects=other_projects,
                              collision=collision)
        cell['color'] = effort_color(total)
        return cell

    # ------------------------------------------------------------------
    # 2. Task (week) planner
    # ------------------------------------------------------------------
    @api.model
    def _pwf_task_category(self, task, today, final_ids):
        """Exactly one of TASK_CATEGORIES, by the task's actual stage.

        completed: stage in _ft_final_stage_ids.
        overdue: not completed, local deadline < today.
        not_started: stage bucket 'planned' (the Planned stage, or any stage
          outside the PMS week stages — as Week._board_status treats it).
        working: any other open stage.
        """
        if task.stage_id.id in final_ids:
            return 'completed'
        deadline = task._ft_local_date(task.date_deadline)
        if deadline and deadline < today:
            return 'overdue'
        stage = (task.stage_id.with_context(lang='en_US').name or '').strip().lower()
        bucket = stage if stage in WEEK_STAGES else 'planned'
        if bucket == 'planned':
            return 'not_started'
        return 'working'

    @api.model
    def _pwf_status_filter(self, filters):
        status = filters.get('status_filter')
        if status in STATUS_FILTERS:
            return status
        # Legacy client: show_completed=True meant "everything".
        if filters.get('show_completed'):
            return 'all'
        return DEFAULT_STATUS_FILTER

    @api.model
    def get_task_planner_data(self, filters=None):
        filters = filters or {}
        today = fields.Date.context_today(self)
        Week = self.env['qa_testapp.sprint']
        Task = self.env['project.task']

        project_id = filters.get('project_id') or False
        pm_ids = _ids(filters.get('pm_ids'))
        resource_ids = _ids(filters.get('resource_ids'))
        status_filter = self._pwf_status_filter(filters)
        focus = _to_date(filters.get('focus_date'))
        week_offset = int(filters.get('week_offset') or 0)
        week_count = int(filters.get('week_count') or DEFAULT_WEEK_COUNT)
        week_count = max(1, min(week_count, MAX_WEEK_COUNT))

        # Start at the current (or focus) week, then the upcoming ones.
        anchor = monday_of(focus or today)
        first = anchor + timedelta(weeks=week_offset)
        mondays = [first + timedelta(weeks=i) for i in range(week_count)]
        weeks = Week._ensure_weeks(set(mondays)).sorted('start_date')

        project = self.env['project.project']
        if project_id:
            project = project.browse(int(project_id)).exists()
            project.check_access('read')

        domain = self._pwf_task_base_domain(
            [project.id] if project else None, pm_ids, resource_ids)
        domain.append(('sprint_id', 'in', weeks.ids))
        tasks = Task.search(domain)

        final_ids = set(Task._ft_final_stage_ids())
        by_week = defaultdict(list)
        for task in tasks:
            by_week[task.sprint_id.id].append(task)

        weeks_payload = []
        for week in weeks:
            rows = []
            total = completed_total = actual_total = 0.0
            for task in by_week.get(week.id, []):
                category = self._pwf_task_category(task, today, final_ids)
                estimated = task.estimated or 0.0
                total += estimated
                actual_total += task.effective_hours or 0.0
                if category == 'completed':
                    completed_total += estimated
                visible = (
                    status_filter == 'all'
                    or (status_filter == 'completed') == (category == 'completed'))
                if visible:
                    rows.append((category, task))
            rows.sort(key=lambda item: self._pwf_task_sort_key(*item))
            open_total = total - completed_total
            start, end = week.start_date, week.end_date or sunday_of(week.start_date)
            name = week.name or week_label(start)
            weeks_payload.append({
                'id': week.id,
                'name': name,
                'label': '%s · %s – %s' % (
                    name, self._pwf_fmt(start, 'dd MMM'),
                    self._pwf_fmt(end, 'dd MMM yyyy')),
                'start': fields.Date.to_string(start),
                'end': fields.Date.to_string(end),
                'is_current': start <= today <= end,
                'contains_focus': bool(focus) and start <= focus <= end,
                'tasks': [self._pwf_task_payload(task, category, today)
                          for category, task in rows],
                'totals': {
                    'estimated': round(total, 2),
                    'open': round(open_total, 2),
                    'completed': round(completed_total, 2),
                    'actual': round(actual_total, 2),
                    'estimated_hhmm': hours_to_hhmm(total),
                    'open_hhmm': hours_to_hhmm(open_total),
                    'completed_hhmm': hours_to_hhmm(completed_total),
                    'actual_hhmm': hours_to_hhmm(actual_total),
                },
            })

        return {
            'project': ({'id': project.id, 'name': project.display_name}
                        if project else False),
            'status_filter': status_filter,
            'weeks': weeks_payload,
            'options': self._pwf_options(
                [project.id] if project else [], resource_ids),
        }

    @api.model
    def _pwf_task_sort_key(self, category, task):
        deadline = task._ft_local_date(task.date_deadline)
        return (
            CATEGORY_ORDER[category],
            deadline is None,
            deadline or date.max,
            -int(task.priority or '0'),
            task.id,
        )

    @api.model
    def _pwf_task_payload(self, task, category, today):
        deadline = task._ft_local_date(task.date_deadline)
        return {
            'id': task.id,
            'name': task.name,
            'project': task.project_id.display_name or '',
            'project_id': task.project_id.id,
            'module': task.module_id.display_name if task.module_id else '',
            'stage': task.stage_id.display_name or '',
            'category': category,
            'assignees': [{'id': u.id, 'name': u.name,
                           'initials': initials_of(u.name)}
                          for u in task.user_ids],
            'deadline': fields.Date.to_string(deadline) if deadline else False,
            'deadline_label': task._board_deadline(today)['deadline'],
            'estimated': task.estimated or 0.0,
            'actual': task.effective_hours or 0.0,
            'estimated_hhmm': hours_to_hhmm(task.estimated or 0.0),
            'actual_hhmm': hours_to_hhmm(task.effective_hours or 0.0),
            'priority': int(task.priority or '0'),
        }

    # ------------------------------------------------------------------
    # 3. Move a task to another week
    # ------------------------------------------------------------------
    @api.model
    def _pwf_deadline_text(self, task, value):
        day = task._ft_local_date(value) if value else None
        return self._pwf_fmt(day, 'dd MMM yyyy') if day else _('none')

    @api.model
    def move_task_week(self, task_id, target_week_id, reason=False):
        # The reason is optional: stored stripped, or False when not given.
        reason = (reason or '').strip() or False
        task = self.env['project.task'].browse(int(task_id)).exists()
        if not task:
            raise UserError(_('The task no longer exists.'))
        task.check_access('write')
        target = self.env['qa_testapp.sprint'].browse(int(target_week_id)).exists()
        if not target:
            raise UserError(_('The target week no longer exists.'))
        source = task.sprint_id
        if source == target:
            raise UserError(_('The task is already allocated to %s.', target.name))

        deadline_before = task.date_deadline
        # sudo read: the log is not readable by every task writer.
        first_move = (not task.pwf_original_deadline
                      and not task.sudo().pwf_week_move_ids)
        vals = {'sprint_id': target.id}
        if first_move and deadline_before:
            vals['pwf_original_deadline'] = deadline_before
        # Normal ft_sprint_management write: the deadline follows the week
        # (target Sunday 23:59 local). The flag stops the generic deadline
        # log (task_week_move.py) from duplicating the row created below.
        task.with_context(pwf_skip_deadline_log=True).write(vals)
        new_deadline = task.date_deadline

        # sudo: the log is read-only for everyone (no create ACL); the access
        # check above is what authorises the move.
        self.env['ft.pms.task.week.move'].sudo().create({
            'task_id': task.id,
            'from_week_id': source.id or False,
            'to_week_id': target.id,
            'reason': reason,
            'user_id': self.env.user.id,
            'moved_on': fields.Datetime.now(),
            'deadline_at_move': deadline_before,
            'new_deadline': new_deadline,
        })
        body = Markup('%s<br/>%s') % (
            _('Week allocation moved from %(src)s to %(dst)s.',
              src=source.name or _('no week'), dst=target.name),
            _('Deadline: %(old)s → %(new)s',
              old=self._pwf_deadline_text(task, deadline_before),
              new=self._pwf_deadline_text(task, new_deadline)),
        )
        if reason:
            body += Markup('<br/><b>%s</b> %s') % (_('Reason:'), escape(reason))
        task.message_post(body=body, subtype_xmlid='mail.mt_note')
        return {'ok': True}
