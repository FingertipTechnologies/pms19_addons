import logging
from datetime import datetime, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Map hr.job (position) names -> role bucket. Mirrors the classification used by
# ft_task_hours_tracker so the dashboard counts roles the same way the rest of
# the PMS does. Matching is done on the lower-cased job name.
ROLE_BUCKETS = {
    'software developer': 'dev',
    'technical lead': 'dev',
    'software tester': 'qa',
    'testing lead': 'qa',
    'project manager': 'pm',
    'project cordinator': 'pm',   # legacy typo present in source data
    'project coordinator': 'pm',
    'business analyst': 'ba',
}

# Project stages that do not represent active delivery work: "General" is the
# intake bucket, "Hold" is paused and "Closed" is finished. Everything else is
# in-flight and counts towards Active Projects.
#
# Matched by stage NAME rather than id because project.project.stage rows are
# created per database, so the ids differ between staging and production. The
# older `status` selection on bt_project_customization is NOT used here: it is
# NULL on every project, which made the previous `status not in ('closed',)`
# filter a no-op that counted closed projects as active.
INACTIVE_STAGE_NAMES = ('General', 'Hold', 'Closed')

# Stage holding projects under an annual maintenance contract.
AMC_STAGE_NAME = 'AMC'

# Stages whose projects are hidden from the Project Performance table until the
# matching toggle beside its search box is ticked. One toggle per stage rather
# than one for all three: they are hidden for different reasons and are wanted
# back at different times, so somebody reviewing AMC renewals should not have to
# pull 128 Closed projects onto the screen to do it.
#
# Keys are the flag names the client toggles; values are the stage names. Order
# is the order the toggles render in, so it is kept deliberate rather than
# alphabetical — Closed first because it is by far the largest bucket.
#
# Deliberately NOT the same set as INACTIVE_STAGE_NAMES: Hold is absent here,
# because a paused project is still delivery work somebody has to chase, whereas
# AMC is present, because a maintenance contract has no delivery performance to
# measure. The table is about how delivery is going, so these three are noise by
# default rather than being removed outright — hence toggles, not a filter.
PERF_HIDDEN_STAGE_GROUPS = {
    'closed': 'Closed',
    'amc': AMC_STAGE_NAME,
    'general': 'General',
}

# Project whose task time is reported as Standup Hours. Matched by name for the
# same reason stages are: the project id differs between databases.
STANDUP_PROJECT_NAME = 'Fingertip Standup'

# task_type values (bt_project_customization) that count as meetings.
INTERNAL_MEETING_TYPE = 'internal_call'
EXTERNAL_MEETING_TYPE = 'external_call'

# Sentinel the person picker can carry instead of an hr.employee id. A string,
# so it can never collide with a real id.
#
# UNASSIGNED means records with nobody on them. Real for tasks (2,947 active ones
# carry no assignee); in Hours Utilisation it correctly reports 0, a timesheet
# line always recording who booked it.
#
# There used to be a second sentinel, NONE, needed only because the sections
# carried TWO pickers whose different meanings had to be reconciled. Collapsing
# them into one made it redundant: "that PM's own records" is now simply picking
# the PM.
FILTER_UNASSIGNED = 'unassigned'

# The Open Tasks breakdown in Tasks Summary. "Open" on its own says only "not
# finished", which covers 5,201 tasks in every state from untouched to blocked —
# the split is what makes it actionable.
#
# Matched on the stage NAME, lower-cased, because stage rows are created per
# project and the ids differ everywhere. Each entry is (key, label, matcher):
# an exact-name tuple, or a substring for buckets whose stages are named
# inconsistently — "Client Dependencies", "Dependencies from Client" and
# "Dependency from Telephony Vendor" are all the same thing to a reader.
#
# These four do NOT cover every open stage (Post sales, Sandbox Review, Presales
# and friends sit outside them, as do tasks with no stage at all), which is why
# _tasks_summary_values also reports the remainder. Without it the four cards
# would silently fall 251 short of Open Tasks.
OPEN_STAGE_BUCKETS = (
    ('planned', 'exact', ('planned',)),
    ('working', 'exact', ('working',)),
    ('testing', 'exact', ('testing',)),
    ('dependency', 'contains', ('dependenc',)),
)

# A consistent, professional palette reused across charts.
PALETTE = [
    '#4F46E5', '#06B6D4', '#10B981', '#F59E0B', '#EF4444',
    '#8B5CF6', '#EC4899', '#14B8A6', '#F97316', '#3B82F6',
    '#84CC16', '#A855F7',
]


class FtProjectDashboard(models.TransientModel):
    _name = 'ft.project.dashboard'
    _description = 'FT Project Dashboard data provider'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _scope_leaves_via_project(self, filters=None):
        """The header's Project / Manager / Status leaves, for a model holding
        ``project_id``.

        Every timesheet-line and task query on the board runs through here, so
        the one set of pickers in the header scopes the whole dashboard
        identically instead of each section deciding for itself.

        ``manager_id`` is a res.users id — project.project.user_id, the Project
        Manager on the project form — and narrows the board to the projects that
        person runs. It is a PROJECT-level scope, not a people filter: it does
        not care who booked the time, only whose projects it was booked on. The
        Resource picker inside each section is what narrows by person, and the
        two compose.
        """
        filters = filters or {}
        leaves = []
        if filters.get('project_id'):
            leaves.append(('project_id', '=', int(filters['project_id'])))
        if filters.get('manager_id'):
            leaves.append(('project_id.user_id', '=', int(filters['manager_id'])))
        if filters.get('stage_id'):
            leaves.append(('project_id.stage_id', '=', int(filters['stage_id'])))
        return leaves

    def _scope_leaves_on_project(self, filters=None):
        """The same leaves expressed on ``project.project`` itself."""
        filters = filters or {}
        leaves = []
        if filters.get('project_id'):
            leaves.append(('id', '=', int(filters['project_id'])))
        if filters.get('manager_id'):
            leaves.append(('user_id', '=', int(filters['manager_id'])))
        if filters.get('stage_id'):
            leaves.append(('stage_id', '=', int(filters['stage_id'])))
        return leaves

    def _ts_domain(self, date_from, date_to, filters=None):
        """Domain for timesheet lines (account.analytic.line) within range."""
        domain = [('project_id', '!=', False)]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain + self._scope_leaves_via_project(filters)

    def _worked_employee_ids(self, filters=None, date_from=None, date_to=None):
        """Ids of employees who booked time on the scoped project(s) in range.

        ``None`` when the header carries no Project/Status scope, meaning "do not
        narrow" — distinct from an empty list, which means "nobody worked on it".

        Timesheet lines rather than task assignees, for two reasons. Retrieval:
        ``employee_id`` and ``project_id`` are both indexed columns on
        account.analytic.line, so this is a single read_group with no
        many2many join through project_task_user_rel and no res.users ->
        hr.employee mapping afterwards. Meaning: booked hours are already what
        the rest of this board treats as the evidence that somebody worked on
        something — the Resource Status table says so explicitly. The trade-off
        is that a person assigned to a task who has logged no time does not
        count as having worked on it, which is the intended reading of "worked".
        """
        scope = self._scope_leaves_via_project(filters)
        if not scope:
            return None
        domain = [('project_id', '!=', False)] + scope
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return [
            group['employee_id'][0]
            for group in self.env['account.analytic.line'].read_group(
                domain, ['employee_id'], ['employee_id'], lazy=False)
            if group.get('employee_id')
        ]

    def _role_employee_ids(self, filters=None, date_from=None, date_to=None):
        """Active-employee ids grouped by role bucket (via job position).

        Returns the ids, not just a count, so a KPI card can open exactly the
        employees behind its number — the drill-down can't drift from the count
        because both come from this one classification.

        With a Project or Status chosen in the header, the buckets are narrowed
        to the people who actually booked time on those projects inside the
        selected period, so the headcount cards answer "who worked on this" and
        not "how many of these does the company employ". Unscoped they keep the
        company-wide meaning they have always had.

        Still limited to ACTIVE employees either way: the cards are a headcount,
        and including leavers would make the drill-down list — which filters out
        archived records by default — shorter than the number it was opened from.
        """
        worked_ids = self._worked_employee_ids(filters, date_from, date_to)
        domain = [('active', '=', True)]
        if worked_ids is not None:
            domain.append(('id', 'in', worked_ids))

        buckets = {'dev': [], 'qa': [], 'pm': [], 'ba': [], 'trainee': [], 'other': []}
        for emp in self.env['hr.employee'].search_read(domain, ['job_id']):
            job = emp.get('job_id')
            name = (job[1] if job else '').strip().lower()
            if name.startswith('trainee'):
                buckets['trainee'].append(emp['id'])
            else:
                buckets[ROLE_BUCKETS.get(name, 'other')].append(emp['id'])
        return buckets

    def _role_counts(self, filters=None, date_from=None, date_to=None):
        """Count active employees per role bucket via their job position."""
        return {
            k: len(v)
            for k, v in self._role_employee_ids(filters, date_from, date_to).items()
        }

    def _stage_ids_named(self, names):
        """Resolve project stage names to ids.

        Domains are built on ids rather than on ``stage_id.name`` because the
        stage name is a translated (jsonb) column, and comparing it inside a
        domain is both slower and language-dependent. Archived stages are
        included: a project can still sit in one.
        """
        return self.env['project.project.stage'].with_context(
            active_test=False).search([('name', 'in', list(names))]).ids

    def _active_project_domain(self, filters=None):
        """Projects counted as active: not General, not Hold, not Closed.

        ``not in`` on a many2one also matches rows with no stage set, so a
        project that has never been staged still counts as active rather than
        silently disappearing from the figure.

        The header's Status picker is ANDed on top, so choosing an inactive
        stage such as Closed legitimately reads 0 here — the card counts active
        projects, and none of them are Closed.
        """
        return [
            ('active', '=', True),
            ('stage_id', 'not in', self._stage_ids_named(INACTIVE_STAGE_NAMES)),
        ] + self._scope_leaves_on_project(filters)

    def _amc_project_domain(self, filters=None):
        """Projects sitting in the AMC stage."""
        return [
            ('active', '=', True),
            ('stage_id', 'in', self._stage_ids_named((AMC_STAGE_NAME,))),
        ] + self._scope_leaves_on_project(filters)

    def _implementation_project_domain(self, filters=None):
        """Active projects still being implemented: Active Projects minus AMC.

        AMC is ongoing maintenance rather than delivery work, so it is reported
        on its own card and excluded here. This keeps the two cards additive:
        Active Projects == Implementation Projects + AMC Projects.
        """
        return [
            ('active', '=', True),
            ('stage_id', 'not in',
             self._stage_ids_named(INACTIVE_STAGE_NAMES + (AMC_STAGE_NAME,))),
        ] + self._scope_leaves_on_project(filters)

    def _hours_base_domain(self, filters=None):
        """Everything the Hours Utilisation filters imply EXCEPT the task leaf.

        Split out so the section can measure task-attached time and task-less
        project time through the identical range, scope and people filters —
        otherwise the two would be narrowed differently and could not be added
        together to reconcile against Project Performance's Actual Hrs.
        """
        filters = filters or {}
        domain = []
        if filters.get('date_from'):
            domain.append(('date', '>=', filters['date_from']))
        if filters.get('date_to'):
            domain.append(('date', '<=', filters['date_to']))
        domain += self._scope_leaves_via_project(filters)

        # One picker, one meaning: the hours this person booked.
        #
        # There used to be two — PM and Developer — and they meant different
        # things. PM was "projects this person MANAGES", so it swept in her whole
        # team (2,541 h across 24 people on one project where her own share was
        # 560 h), while Developer was "the person who booked it". Two look-alike
        # dropdowns answering different questions, plus None and Unassigned
        # sentinels to reconcile them, was not something anyone could read off
        # the screen. Picking a name now simply means that person's own work,
        # which is what a person filter means everywhere else.
        #
        # The old "everything happening on a PM's projects" view is not lost —
        # that is the header's Project picker, which scopes the whole board.
        person_id = filters.get('person_id')
        if person_id == FILTER_UNASSIGNED:
            # Always 0 here in practice: a timesheet line records who booked it.
            # Offered anyway so the picker reads the same in both sections, and
            # so an orphaned line would be visible rather than quietly lost.
            domain.append(('employee_id', '=', False))
        elif person_id:
            domain.append(('employee_id', '=', int(person_id)))
        return domain

    def _hours_filter_domain(self, filters=None):
        """Timesheet lines attached to a TASK, for the section's filters.

        Every role and activity figure is built from this one domain, so the
        cards can never disagree with each other about what is being counted.
        With no filters it is simply "every line attached to a task", which is
        exactly what the task form's Dev/QA/PM/BA Hours fields sum.
        """
        return [('task_id', '!=', False)] + self._hours_base_domain(filters)

    def _non_task_hours_domain(self, filters=None):
        """Timesheet lines booked on a PROJECT but against no task.

        These hours are real spend and appear in Project Performance's Actual
        Hrs, but no task-field sum can ever see them — which is precisely why
        that column and Task Hour Totals' Actual Hours used to differ with
        nothing on screen to explain the gap. Reported on their own card so the
        two reconcile: task hours + non-task hours == the project total.

        They also cannot carry a billing status, there being no task to hold
        one, so they are deliberately absent from Billable / Billed.
        """
        return [
            ('task_id', '=', False),
            ('project_id', '!=', False),
        ] + self._hours_base_domain(filters)

    def _role_hours(self, domain):
        """Dev / QA / PM / BA hours for the given timesheet-line domain.

        Aggregated from the lines rather than read off ``ft_dev_hours`` and
        friends because those task fields are whole-task totals with no date
        dimension — they cannot answer "Developer Hours in July". Grouping the
        lines by employee and bucketing by job position reproduces exactly what
        those fields compute (verified equal to the task-field sum when no
        filter is applied), while staying sliceable by date, project and person.

        Archived employees are included: their past hours still show on the
        task form, so dropping them would make the cards disagree with it.
        """
        AAL = self.env['account.analytic.line']
        groups = AAL.read_group(domain, ['unit_amount:sum'], ['employee_id'])

        emp_ids = [g['employee_id'][0] for g in groups if g.get('employee_id')]
        # sudo: hr.job is readable only by HR officers, but every project user
        # still needs their hours bucketed.
        bucket_by_emp = {}
        for emp in self.env['hr.employee'].sudo().with_context(
                active_test=False).search_read([('id', 'in', emp_ids)], ['job_id']):
            job = emp.get('job_id')
            name = (job[1] if job else '').strip().lower()
            bucket_by_emp[emp['id']] = (
                'trainee' if name.startswith('trainee')
                else ROLE_BUCKETS.get(name, 'other')
            )

        totals = dict.fromkeys(('dev', 'qa', 'pm', 'ba', 'trainee', 'other'), 0.0)
        for group in groups:
            emp = group.get('employee_id')
            if not emp:
                continue
            totals[bucket_by_emp.get(emp[0], 'other')] += group.get('unit_amount') or 0.0
        return totals

    def _activity_hours(self, domain):
        """Standup and meeting hours for the given timesheet-line domain.

        Built from the same lines as the role split so both halves of the
        section always answer the same question. Meeting Hours is internal +
        external, keeping the three meeting figures additive.

        Standup and Meeting can overlap: a task in the Standup project that is
        also typed as a call counts in both. They are two views of the same
        time, not a partition.
        """
        AAL = self.env['account.analytic.line']

        def total(extra):
            return sum(
                group['unit_amount']
                for group in AAL.read_group(domain + extra, ['unit_amount:sum'], [])
                if group.get('unit_amount')
            )

        internal = total([('task_id.task_type', '=', INTERNAL_MEETING_TYPE)])
        external = total([('task_id.task_type', '=', EXTERNAL_MEETING_TYPE)])
        return {
            'standup': total([('project_id.name', '=', STANDUP_PROJECT_NAME)]),
            'internal_meeting': internal,
            'external_meeting': external,
            'meeting': internal + external,
        }

    def _hours_utilisation_values(self, filters=None):
        """The Hours Utilisation figures for a set of filters.

        The role cards are a PARTITION of the hours booked in the period, which is
        why `trainee_hours` and `unclassified_hours` exist: _role_hours has always
        bucketed trainees and anyone whose job position is not in ROLE_BUCKETS,
        but nothing displayed those two buckets, so the four visible cards
        silently fell short of the period's real total.

        The invariant this establishes, and the one the Project Performance table
        is reconciled against:

            dev + pm + qa + ba + trainee + unclassified + non_task
                == Actual Hrs in Project Performance

        both sides being "hours booked in the selected period", under the same
        project/stage/people scope. It holds whatever the filters are.

        Note this is NOT the same population as `th_actual_hours` in
        _task_hours_summary_values, which sums whole-task totals over tasks
        CREATED in the period. The two coincide only when every task in scope was
        also created in the period, and the cards say so.
        """
        domain = self._hours_filter_domain(filters)
        role = self._role_hours(domain)
        activity = self._activity_hours(domain)
        AAL = self.env['account.analytic.line']
        non_task = sum(
            group['unit_amount']
            for group in AAL.read_group(
                self._non_task_hours_domain(filters), ['unit_amount:sum'], [])
            if group.get('unit_amount')
        )
        return {
            'dev_hours': round(role['dev'], 2),
            'pm_hours': round(role['pm'], 2),
            'qa_hours': round(role['qa'], 2),
            'ba_hours': round(role['ba'], 2),
            'trainee_hours': round(role['trainee'], 2),
            # Whoever is left: a job position that is not one of the recognised
            # delivery roles, or none at all. Reported separately from trainees
            # rather than lumped in with them, because they are not the same
            # thing and the numbers are not close — 4,451 h of trainee time
            # against 9,471 h unclassified, nearly all of it booked by people
            # with no Job Position set.
            #
            # The card is hidden when this is zero, so it disappears of its own
            # accord once HR fills those positions in. It exists at all so
            # dev + pm + qa + ba + trainee + unclassified accounts for every
            # booked hour; without it the row silently fell short.
            'unclassified_hours': round(role['other'], 2),
            'standup_hours': round(activity['standup'], 2),
            'meeting_hours': round(activity['meeting'], 2),
            'internal_meeting_hours': round(activity['internal_meeting'], 2),
            'external_meeting_hours': round(activity['external_meeting'], 2),
            # Project time booked against no task. Bridges the last of the gap to
            # Project Performance's Actual Hrs.
            'non_task_hours': round(non_task, 2),
        }

    @api.model
    def get_hours_utilisation(self, filters=None):
        """Recompute just the Hours Utilisation cards for its own PM / Developer.

        ``filters`` arrives as the header's range and scope with the section's
        own two dropdowns merged in, so this narrows the same window the rest of
        the board is showing rather than answering a second one.

        Rebuilt server-side because the browser only ever holds totals, and no
        amount of client-side filtering can turn a total into a subset.
        """
        return self._hours_utilisation_values(filters)

    # ------------------------------------------------------------------
    # Tasks Summary
    # ------------------------------------------------------------------
    @staticmethod
    def _date_leaves(field, date_from, date_to):
        """Range leaves for a Datetime field bounded by two calendar dates.

        ``create_date`` and ``date_deadline`` are both Datetimes, so an upper
        bound of the bare date would cut the closing day off at midnight and
        drop everything recorded during it.
        """
        leaves = []
        if date_from:
            leaves.append((field, '>=', str(date_from) + ' 00:00:00'))
        if date_to:
            leaves.append((field, '<=', str(date_to) + ' 23:59:59'))
        return leaves

    def _task_scope_domain(self, filters=None):
        """The non-date part of the Tasks Summary filters.

        Kept apart from the dates because each card anchors on a different
        date — created on ``create_date``, due on ``date_deadline``, completed
        on the completion date — while project / stage / people apply to all of
        them identically.

        PM and Dev match different fields here (project manager vs assignee), so
        unlike the Hours filters they AND together and stay meaningful.
        """
        filters = filters or {}
        domain = self._scope_leaves_via_project(filters)

        # One picker, matching Hours Utilisation: tasks this person is assigned
        # to. See _hours_base_domain for why the PM / Developer pair went away.
        #
        # The picker carries hr.employee ids but tasks reference res.users, so
        # the pick is resolved through the employee's linked user. An employee
        # with no user matches nothing rather than being ignored — silently
        # dropping the leaf would show totals that look unfiltered.
        person_id = filters.get('person_id')
        if person_id == FILTER_UNASSIGNED:
            # Tasks nobody is on. Unlike the hours side this is a real subset —
            # 2,947 active tasks in the production data carry no assignee.
            domain.append(('user_ids', '=', False))
        elif person_id:
            user = self.env['hr.employee'].sudo().browse(int(person_id)).user_id
            domain.append(('user_ids', 'in', user.ids) if user else ('id', '=', 0))
        return domain

    def _open_stage_bucket_ids(self):
        """``{bucket: [stage ids]}`` for the Open Tasks breakdown.

        Bucketed in Python off one search rather than with a domain per bucket:
        the stage name is a translated jsonb column, so comparing it inside a
        domain is slower and language-dependent, and a substring match is not
        expressible there at all. Archived stages are included — a task can
        still sit in one.
        """
        buckets = {key: [] for key, _mode, _pat in OPEN_STAGE_BUCKETS}
        for stage in self.env['project.task.type'].with_context(
                active_test=False).search([]):
            name = (stage.name or '').strip().lower()
            for key, mode, patterns in OPEN_STAGE_BUCKETS:
                hit = (name in patterns if mode == 'exact'
                       else any(p in name for p in patterns))
                if hit:
                    buckets[key].append(stage.id)
                    # First matching bucket wins, so a stage can never be
                    # counted twice and the breakdown stays a partition.
                    break
        return buckets

    def _tasks_summary_values(self, filters=None):
        """The eight Tasks Summary figures for a set of filters.

        Completed / on-timeline / missed all come from project.task's own
        delivery helpers — the single definition of "delivered" and "on time"
        for the whole PMS — so these cards can never disagree with the On-Time
        Delivery card in Project Summary.
        """
        filters = filters or {}
        Task = self.env['project.task']
        scope = self._task_scope_domain(filters)
        date_from, date_to = filters.get('date_from'), filters.get('date_to')

        created = scope + self._date_leaves('create_date', date_from, date_to)
        # Due = the deadline has arrived or passed AND the task is not finished,
        # i.e. work that should already have been delivered and has not been.
        #
        # A snapshot of today, deliberately NOT filtered by the header's range,
        # for the same reason Open Tasks and Open & Overdue are not: something
        # overdue today is overdue whatever window is being looked at. It used to
        # count deadlines falling INSIDE the selected range, which answered a
        # different question entirely — it included work already delivered on
        # time, and excluded anything overdue from before the range started.
        #
        # `<= today 23:59:59` rather than `< now()`, so a task due later today
        # counts as due. That is the one difference from Open & Overdue beside
        # it, which stays strictly past its deadline.
        today = fields.Date.context_today(self)
        due = Task._ft_open_domain(scope) + [
            ('date_deadline', '!=', False),
            ('date_deadline', '<=', str(today) + ' 23:59:59'),
        ]

        # Delivered tasks are fetched once and split here rather than asking for
        # counts and then re-searching for the drill-downs: the list a card
        # opens is then literally the recordset its number was taken from.
        delivered = Task.search(Task._ft_delivery_domain(scope, date_from, date_to))
        split = Task._ft_on_time_split(delivered)

        # A snapshot of now, like Open & Overdue: a task open today is open
        # whatever window is being looked at.
        open_domain = Task._ft_open_domain(scope)
        # Estimation is reported over the tasks CREATED in the window, so the
        # two add back up to Tasks Created.
        estimated = created + [('estimated', '>', 0)]
        not_estimated = created + [('estimated', '<=', 0)]

        # Open Tasks split by stage. A partition, so the buckets plus the
        # remainder add back up to Open Tasks exactly — and, like Open Tasks
        # itself, a snapshot of now rather than of the selected range.
        stage_buckets = self._open_stage_bucket_ids()
        bucketed_ids = [sid for ids in stage_buckets.values() for sid in ids]
        open_by_stage = {
            key: open_domain + [('stage_id', 'in', ids)]
            for key, ids in stage_buckets.items()
        }
        # Everything open that none of the four buckets claimed, including tasks
        # with no stage at all — 251 of them here, mostly unstaged. Reported so
        # the split cannot quietly fall short of the total it is splitting.
        open_by_stage['other'] = open_domain + [
            '|', ('stage_id', '=', False), ('stage_id', 'not in', bucketed_ids),
        ]

        counts = {
            'tasks_created': Task.search_count(created),
            'tasks_due': Task.search_count(due),
            'tasks_completed': len(delivered),
            'tasks_open': Task.search_count(open_domain),
            'tasks_estimated': Task.search_count(estimated),
            'tasks_not_estimated': Task.search_count(not_estimated),
            'tasks_on_timeline': len(split['on_time']),
            'tasks_missed_timeline': len(split['late']),
            'tasks_planned': Task.search_count(open_by_stage['planned']),
            'tasks_working': Task.search_count(open_by_stage['working']),
            'tasks_testing': Task.search_count(open_by_stage['testing']),
            'tasks_dependency': Task.search_count(open_by_stage['dependency']),
            'tasks_other_open': Task.search_count(open_by_stage['other']),
        }

        def action(name, domain):
            return {'res_model': 'project.task', 'name': name,
                    'domain': self._jsonify_domain(domain)}

        counts['actions'] = {
            'tasks_created': action('Tasks Created', created),
            'tasks_due': action('Tasks Due', due),
            'tasks_completed': action('Completed Tasks', [('id', 'in', delivered.ids)]),
            'tasks_open': action('Open Tasks', open_domain),
            'tasks_estimated': action('Estimated Tasks', estimated),
            'tasks_not_estimated': action('Not Estimated', not_estimated),
            # By id: on time is a calendar-day comparison done in Python, so
            # there is no domain that could express it.
            'tasks_on_timeline': action('Completed on Timeline',
                                        [('id', 'in', split['on_time'])]),
            'tasks_missed_timeline': action('Missed Timeline',
                                            [('id', 'in', split['late'])]),
            # The stage split opens the same lists its counts came from.
            'tasks_planned': action('Not Yet Started', open_by_stage['planned']),
            'tasks_working': action('In Progress', open_by_stage['working']),
            'tasks_testing': action('Testing', open_by_stage['testing']),
            'tasks_dependency': action('Dependency', open_by_stage['dependency']),
            'tasks_other_open': action('Other Open Tasks', open_by_stage['other']),
        }
        return counts

    @api.model
    def get_tasks_summary(self, filters=None):
        """Recompute just the Tasks Summary cards for its own filters."""
        return self._tasks_summary_values(filters)

    def _task_hours_summary_values(self, filters=None):
        """Billing-side hour totals read off the task records themselves.

        Every figure here is a stored column on project.task, so each is one
        SQL sum. This is deliberately task-centric: it answers "what do these
        tasks add up to", which is why it can report Billable, Non Billable and
        Billed — none of which exist on a timesheet line.

        These four cards render in the Hours Utilisation section, on their own
        row, because they are the only hour figures on the board that carry a
        billing dimension. They are NOT interchangeable with the role and
        activity cards above them: those count time BOOKED in the window, while
        these total tasks CREATED in it (the same scope as Tasks Summary). The
        row carries its own sub-heading for exactly that reason — the two halves
        will not tally when a date filter is on, and that is correct.

        Meeting / Internal Meeting / External Meeting used to be reported here
        too, duplicating the three identically-named cards that the Hours
        Utilisation role split already provides from the timesheet lines. The
        timesheet-based ones are kept because they answer the same date range as
        the rest of that section; these were dropped rather than shown twice
        with two different numbers under one label.

        ``th_estimated_hours`` IS kept, even though Project Summary also carries
        an Estimated Hours card, because estimation is tracked at both levels in
        this PMS and both are wanted on the board. The card here is titled
        "Estimated Hours (Task)" so the two are not read as one figure. Note the
        Project Summary card is currently NOT the project-level estimate — it
        sums this same task field with no date bound at all.
        """
        filters = filters or {}
        Task = self.env['project.task']
        base = self._task_scope_domain(filters) + self._date_leaves(
            'create_date', filters.get('date_from'), filters.get('date_to'))

        def total(field, extra=None):
            return sum(
                group[field]
                for group in Task.read_group(base + (extra or []), [field + ':sum'], [])
                if group.get(field)
            )

        return {
            'th_estimated_hours': round(total('estimated'), 2),
            'th_actual_hours': round(total('ft_total_hours_taken'), 2),
            'th_billable_hours': round(total('ft_billable_hours'), 2),
            'th_non_billable_hours': round(total('ft_non_billable_hours'), 2),
            # Billable hours on tasks marked Billed — the hours actually
            # invoiced, not merely invoiceable.
            'th_billed_hours': round(
                total('ft_billable_hours', [('ft_billing_status', '=', 'billed')]), 2),
        }

    @api.model
    def get_task_hours_summary(self, filters=None):
        """Recompute the task-hour totals row of Hours Utilisation.

        Still its own RPC rather than folded into ``get_hours_utilisation``
        because the two are computed off different models with different date
        anchors. The client calls both with the one filter payload and merges
        the results, so the section's single PM / Developer bar drives both.
        """
        return self._task_hours_summary_values(filters)

    @api.model
    def get_hours_filter_options(self):
        """Contents for every dropdown on the board.

        Projects and Stages feed the two pickers in the header, which scope the
        whole dashboard. Every active project is therefore offered: the list was
        previously narrowed to projects that already carry task time, which made
        sense for a Hours-only filter but leaves a project unselectable here even
        though the tables and charts below can report on it.
        """
        projects = sorted(
            ({'id': p['id'], 'name': p['name'] or ''}
             for p in self.env['project.project'].search_read(
                 [('active', '=', True)], ['name'])),
            key=lambda p: p['name'].lower())

        # Project Managers for the header picker: the res.users actually set as
        # Project Manager on an active project. Built from the projects rather
        # than from a job-position bucket, because this filter narrows by
        # project.user_id — offering someone who manages nothing would give a
        # dead entry that can only ever return an empty board.
        #
        # Sorted by name, and the project count rides along in the label so it is
        # obvious up front how much each pick will show.
        managers = []
        for group in self.env['project.project'].read_group(
                [('active', '=', True), ('user_id', '!=', False)],
                ['id'], ['user_id'], lazy=False):
            if group.get('user_id'):
                managers.append({
                    'id': group['user_id'][0],
                    'name': '%s — %s project(s)' % (group['user_id'][1],
                                                    group['__count']),
                    'sort': (group['user_id'][1] or '').lower(),
                })
        managers.sort(key=lambda m: m['sort'])
        for m in managers:
            m.pop('sort')

        # active_test=False to match _stage_ids_named: a project can still sit in
        # an archived stage, so leaving it out of the picker would make those
        # projects unreachable through the Status filter.
        stages = [
            {'id': s.id, 'name': s.name}
            for s in self.env['project.project.stage'].with_context(
                active_test=False).search([], order='sequence, name')
        ]

        # One list for the one person picker each section carries, replacing the
        # separate Project Managers and Developers lists. Every active employee
        # is offered, not just the delivery roles: 194 h in 2026 were booked by
        # people whose Job Position is unset, and narrowing by role would have
        # made them unfilterable. The picker is a search box, so a long list
        # costs nothing.
        #
        # The job title rides along in the label, which is what tells two people
        # with similar names apart now that the role is no longer implied by
        # which of two dropdowns you reached for.
        Employee = self.env['hr.employee'].sudo()
        resources = [
            {'id': e.id,
             'name': '%s — %s' % (e.name, e.job_id.name) if e.job_id else e.name}
            for e in Employee.search([('active', '=', True)], order='name')
        ]

        return {
            'projects': projects,
            'managers': managers,
            'stages': stages,
            'resources': resources,
        }

    @staticmethod
    def _jsonify_domain(domain):
        """Make a domain safe to send to the client.

        Server domains can carry a live ``datetime`` (the overdue cutoff is
        ``now()``); that is not JSON-serialisable, so stamp it to a string while
        leaving every other leaf untouched.
        """
        out = []
        for leaf in domain:
            if isinstance(leaf, (list, tuple)) and len(leaf) == 3:
                field, op, value = leaf
                if isinstance(value, datetime):
                    value = fields.Datetime.to_string(value)
                out.append((field, op, value))
            else:
                out.append(leaf)
        return out

    # ------------------------------------------------------------------
    # Public RPC entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, filters=None):
        """Return all KPI values and chart datasets for the dashboard.

        :param date_from/date_to: 'YYYY-MM-DD' strings (inclusive) or False.
        :param filters: ``{'project_id': id, 'stage_id': id}`` — the Project and
            Status pickers in the header. Either may be absent or empty.

        Every figure on the board answers this one date range and this one
        scope, the header being the only place either is chosen. The sections
        and tables used to carry date pickers of their own, which meant a range
        typed into a table was silently intersected with the header's — two
        answers to the same question on a single screen, and no way to tell
        which one a number came from. The one per-section picker that remains
        (Resource) only ever narrows this scope further.

        Open & Overdue is the one deliberate exception, here and in the tables:
        it stays a snapshot of now, because a task that is late today is late
        whatever window is being looked at.
        """
        return {
            'kpis': self._compute_kpis(date_from, date_to, filters),
            'tables': {
                'project_status': self._table_project_status(date_from, date_to, filters),
                'resource_status': self._table_resource_status(date_from, date_to, filters),
                'delivery': self._table_delivery(date_from, date_to, filters),
            },
            'charts': {
                'project_hours': self._chart_project_hours(date_from, date_to, filters),
                'billable': self._chart_billable(date_from, date_to, filters),
                'team_composition': self._chart_team_composition(
                    filters, date_from, date_to),
                'progress_trend': self._chart_progress_trend(date_from, date_to, filters),
            },
        }

    # ------------------------------------------------------------------
    # KPI cards
    # ------------------------------------------------------------------
    def _compute_kpis(self, date_from, date_to, filters=None):
        Project = self.env['project.project']
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        # The header's Project / Status scope, in the two shapes the queries
        # below need it.
        task_scope = self._scope_leaves_via_project(filters)

        active_project_domain = self._active_project_domain(filters)
        amc_project_domain = self._amc_project_domain(filters)
        implementation_project_domain = self._implementation_project_domain(filters)
        active_projects = Project.search_count(active_project_domain)
        amc_projects = Project.search_count(amc_project_domain)
        implementation_projects = Project.search_count(implementation_project_domain)

        ts_domain = self._ts_domain(date_from, date_to, filters)
        spent = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain, ['unit_amount:sum'], []) if g.get('unit_amount'))

        billable = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain + [('project_id.allow_billable', '=', True)],
            ['unit_amount:sum'], []) if g.get('unit_amount'))

        # Anchored on create_date like every other task figure on the board.
        # Without the date leaves this summed EVERY task ever, so the card read
        # the same 23,128 h whether the header said "Today" or covered thirty
        # years — and Remaining Hours below, being this minus a period-scoped
        # Hours Spent, came out at -44,085 h: an all-time budget less one
        # month's burn, which is not a quantity at all.
        estimated = sum(g['estimated'] for g in Task.read_group(
            [('project_id', '!=', False)] + task_scope
            + self._date_leaves('create_date', date_from, date_to),
            ['estimated:sum'], [])
            if g.get('estimated'))

        # Narrowed to whoever booked time on the scoped project(s) in the period
        # when the header carries a Project/Status pick; company-wide otherwise.
        role_ids = self._role_employee_ids(filters, date_from, date_to)
        roles = {k: len(v) for k, v in role_ids.items()}

        # First paint for the two filtered sections. These carry the header's
        # range and scope, exactly like every other card — they used to be
        # computed with NO filters at all, so on load the board showed all-time
        # figures under a header that said "This Month" and only started
        # agreeing with it once a section dropdown was touched.
        #
        # The task-hour totals are spread in alongside Hours Utilisation because
        # they now render as the third row of that section; the client refetches
        # both through the section's one filter bar.
        section_filters = dict(filters or {},
                               date_from=date_from, date_to=date_to)
        hours_utilisation = self._hours_utilisation_values(section_filters)
        tasks_summary = self._tasks_summary_values(section_filters)
        # Lifted out before the spread below: the payload has one shared
        # `actions` map, so leaving this key in place would collide with it and
        # the Tasks Summary cards would open nothing on first paint.
        task_actions = tasks_summary.pop('actions', {})
        task_hours_summary = self._task_hours_summary_values(section_filters)

        # On-time delivery for the selected period. The maths lives on
        # project.task so this and the project.project fields can never disagree
        # about what "delivered" or "on time" means.
        delivery = Task._ft_on_time_stats(
            task_scope, date_from=date_from, date_to=date_to)

        # Drill-down domains, built from the SAME queries as the numbers above so
        # the list a card opens always holds exactly the count it shows. Cards
        # backed by a sum (hours) or by nothing (N/A) are absent here on purpose.
        emp_action = lambda ids, name: {
            'res_model': 'hr.employee', 'name': name,
            'domain': [('id', 'in', ids)],
        }
        delivery_domain = Task._ft_delivery_domain(
            task_scope, date_from=date_from, date_to=date_to)
        actions = {
            # Served from the same domains as the counts above, so the list the
            # card opens always holds exactly the number the card shows.
            'active_projects': {
                'res_model': 'project.project', 'name': 'Active Projects',
                'domain': active_project_domain,
            },
            'amc_projects': {
                'res_model': 'project.project', 'name': 'AMC Projects',
                'domain': amc_project_domain,
            },
            'implementation_projects': {
                'res_model': 'project.project', 'name': 'Implementation Projects',
                'domain': implementation_project_domain,
            },
            # Hours Utilisation cards are read-only totals with no drill-down,
            # so they intentionally contribute no action here.
            'developers': emp_action(role_ids['dev'], 'Developers'),
            'testers': emp_action(role_ids['qa'], 'Testers'),
            'trainees': emp_action(role_ids['trainee'], 'Trainees'),
            'project_managers': emp_action(role_ids['pm'], 'Project Managers'),
            'tasks_delivered': {
                'res_model': 'project.task', 'name': 'Tasks Delivered',
                'domain': delivery_domain,
            },
            # The % is measured only over delivered tasks that HAVE a deadline,
            # so its drill-down is exactly that denominator.
            'on_time_delivery': {
                'res_model': 'project.task', 'name': 'Delivered (with deadline)',
                'domain': delivery_domain + [('date_deadline', '!=', False)],
            },
            'overdue_open_tasks': {
                'res_model': 'project.task', 'name': 'Open & Overdue',
                'domain': self._jsonify_domain(
                    Task._ft_overdue_open_domain(task_scope)),
            },
            # Tasks Summary drill-downs, built by _tasks_summary_values.
            **task_actions,
        }

        return {
            'active_projects': active_projects,
            'implementation_projects': implementation_projects,
            'amc_projects': amc_projects,
            'hours_spent': round(spent, 2),
            # Hours Utilisation (role + activity + task-hour rows) and Tasks
            # Summary, on first paint — both sections refetch through their own
            # filter bar once one is touched.
            **hours_utilisation,
            **task_hours_summary,
            **tasks_summary,
            'billable_hours': round(billable, 2),
            'developers': roles['dev'],
            'testers': roles['qa'],
            # Counted separately from Developers/Testers: trainees are detected
            # by a job position starting with "trainee", so they are never
            # folded into a delivery role bucket.
            'trainees': roles['trainee'],
            'project_managers': roles['pm'],
            'hours_estimated': round(estimated, 2),
            'hours_remaining': round(estimated - spent, 2),
            # None (not 0) when nothing measurable was delivered in the period,
            # so the card reads "N/A" rather than a 0% that looks like failure.
            'on_time_delivery': delivery['rate'],
            'tasks_delivered': delivery['completed'],
            # Snapshot of now, deliberately not period-filtered: it is the check
            # on the percentage above, which only ever counts work that finished.
            'overdue_open_tasks': delivery['overdue_open'],
            # No capacity/planning model installed yet -> shown as "N/A".
            'resource_need': None,
            'available_resources': None,
            # Per-card drill-down targets (see `actions` above).
            'actions': actions,
        }

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Tables (full-width)
    # ------------------------------------------------------------------
    @staticmethod
    def _iso_date(d):
        """Return an ISO 'YYYY-MM-DD' string (sortable), or '' when unset.

        The client formats these for display; ISO strings also sort
        chronologically as plain strings, which the table sorter relies on.
        """
        return fields.Date.to_string(d) if d else ''

    @staticmethod
    def _overlaps_period(start, end, date_from, date_to):
        """True when [start, end] overlaps the selected period.

        Open-ended dates count as overlapping: a project with no end date is
        still running, and one with no start date has no evidence it began
        after the period.
        """
        if date_from and end and fields.Date.to_string(end) < date_from:
            return False
        if date_to and start and fields.Date.to_string(start) > date_to:
            return False
        return True

    def _table_project_status(self, date_from=None, date_to=None, filters=None):
        """One row per active project with dates and estimated/actual hours.

        Estimated = sum of task.estimated for the project (all-time: an
                    estimate belongs to the whole project, not to a period).
        Actual    = hours logged (account.analytic.line.unit_amount) *within
                    the selected period*, so it lines up with the period's
                    KPI cards.
        Rows cover every active project with hours booked in the period, plus
        those whose start/end window overlaps it; projects with open-ended dates
        always show. Archived projects are excluded — 79 h across 8 of them in
        2026, deliberately left out of a performance table.

        Per project, this column reconciles exactly with the Hours Utilisation
        section: dev + pm + qa + ba + other + non_task == Actual Hrs.

        Every row carries ``hidden_group``: ``'closed'``, ``'amc'``, ``'general'``
        or ``False`` (see PERF_HIDDEN_STAGE_GROUPS). The client hides each group
        until that group's own toggle beside the search box is ticked, so the
        three can be brought back independently. Sending the group name rather
        than a plain boolean is what makes that possible without the browser
        having to know which stage names map to which toggle.

        The classification is decided HERE, resolved through _stage_ids_named
        like every other stage test in this module — which also means an archived
        stage and a translated stage name both still match.
        """
        Project = self.env['project.project']
        Task = self.env['project.task']
        AAL = self.env['account.analytic.line']

        est_by_proj = {}
        for g in Task.read_group(
                [('project_id', '!=', False)], ['estimated:sum'],
                ['project_id'], lazy=False):
            if g.get('project_id'):
                est_by_proj[g['project_id'][0]] = g.get('estimated') or 0.0
        act_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to, filters), ['unit_amount:sum'],
                ['project_id'], lazy=False):
            if g.get('project_id'):
                act_by_proj[g['project_id'][0]] = g.get('unit_amount') or 0.0

        # Hours booked in the period outrank the project's own dates, exactly as
        # in _table_resource_status: time logged against a project whose dates say
        # it was not running is still time that was spent, and dropping the row
        # made this table's Actual Hrs disagree with the timesheets and with the
        # Hours Utilisation cards. Two of the twelve busiest projects in 2026
        # (5,248 h and 1,071 h) had no row here at all for that reason.
        #
        # The date window still decides projects with nothing booked, where there
        # is no evidence either way and an undated project would otherwise appear
        # in every period.
        shown = Project.search(
            [('active', '=', True)] + self._scope_leaves_on_project(filters),
            order='name',
        ).filtered(
            lambda p: act_by_proj.get(p.id)
            or self._overlaps_period(
                p.date_start, p.date, date_from, date_to))

        # DE / OTD / RWR / DWD for every shown project in ONE search, from the
        # same helper project.project's own ft_* fields use. Those fields are
        # all-time, though, while this table is period-scoped — so the range is
        # passed through here instead of reading them, keeping these columns
        # consistent with the Actual Hrs beside them.
        stats_by_project = Task._ft_on_time_stats_by_project(
            shown.ids, date_from, date_to)
        # A project that delivered nothing in the period reads like an empty
        # recordset rather than a zero: rates come back None so the UI shows
        # "N/A" instead of a 0% that looks like failure.
        no_delivery = Task._ft_delivery_kpis(Task.browse())

        # stage id -> toggle group, resolved once rather than per row. One search
        # per group keeps the name matching inside _stage_ids_named, which is
        # what handles archived and translated stage names.
        group_by_stage_id = {}
        for group, stage_name in PERF_HIDDEN_STAGE_GROUPS.items():
            for stage_id in self._stage_ids_named((stage_name,)):
                group_by_stage_id[stage_id] = group

        # Two projects can carry the same name — "Johns Umbrella" and
        # "Product: Real estate Pre sales" each exist twice in production — and
        # two identical rows in a performance table are indistinguishable. Only
        # the repeats get a qualifier, so the common case stays clean.
        name_counts = {}
        for p in shown:
            name_counts[p.name or ''] = name_counts.get(p.name or '', 0) + 1

        def row_label(project):
            name = project.name or ''
            if name_counts.get(name, 0) < 2:
                return name
            # Customer first, since that is what actually tells them apart;
            # the id is the fallback when both share a customer or have none.
            partner = project.partner_id.name if project.partner_id else ''
            return '%s (%s)' % (name, partner or '#%s' % project.id)

        rows = []
        for p in shown:
            stats = stats_by_project.get(p.id) or no_delivery
            rows.append({
                'project': row_label(p),
                # Which toggle governs this row, or False for always-visible.
                # A project with no stage set is never hidden: a falsy stage_id
                # is not in the map, so unstaged work stays visible rather than
                # disappearing behind a toggle nobody would think to tick.
                'hidden_group': group_by_stage_id.get(p.stage_id.id, False),
                # Show the standard Kanban stage (the status bar on the project
                # form); the custom 'status' selection is unset on most projects.
                'status': p.stage_id.name or '',
                'start_date': self._iso_date(p.date_start),
                'uat_date': self._iso_date(p.uat_start_date),
                'end_date': self._iso_date(p.date),
                'estimated': round(est_by_proj.get(p.id, 0.0), 2),
                'actual': round(act_by_proj.get(p.id, 0.0), 2),
                # Same four measures as Resource Performance, per project.
                'de_rate': stats['efficiency_rate'],
                'otd_rate': stats['rate'],
                'rwr_rate': stats['rework_rate'],
                'dwd': stats['no_deadline'],
                # Kept alongside so a percentage drawn from two tasks is not
                # read as if it came from two hundred.
                'delivered': stats['completed'],
            })
        return rows

    def _table_delivery(self, date_from=None, date_to=None, filters=None):
        """One row per person: how much they delivered and how much was on time.

        Covers TLs and Developers (and everyone else) in one table, with the
        Role column carrying the employee's actual job position. That is
        deliberate: the dashboard's ROLE_BUCKETS map lumps 'technical lead' and
        'software developer' into the same 'dev' bucket, so bucketing here would
        make TLs and Developers indistinguishable — the very split that was
        asked for. The raw job name keeps them apart without disturbing the
        bucket counts the existing KPIs and the team pie depend on.

        A task with several assignees counts in full for each of them, matching
        _table_resource_status. So the column totals exceed the portfolio's task
        count; each row answers "how did this person's work land", not "who owns
        what share".
        """
        Task = self.env['project.task']
        Emp = self.env['hr.employee']
        task_scope = self._scope_leaves_via_project(filters)

        employees = Emp.search([('active', '=', True)])
        emp_by_user = {e.user_id.id: e for e in employees if e.user_id}

        # Delivered tasks in the period, attributed to each assignee. Ids are
        # collected and browsed once per employee; unioning recordsets in the
        # loop would rebuild the set on every step.
        delivered_ids = {}
        for task in Task.search(Task._ft_delivery_domain(
                task_scope, date_from=date_from, date_to=date_to)):
            for user in task.user_ids:
                emp = emp_by_user.get(user.id)
                if emp:
                    delivered_ids.setdefault(emp.id, []).append(task.id)
        delivered_by_emp = {
            emp_id: Task.browse(ids) for emp_id, ids in delivered_ids.items()
        }

        # Open + overdue right now, same attribution. One search, grouped in
        # Python, rather than a count per employee.
        overdue_by_emp = {}
        for task in Task.search(Task._ft_overdue_open_domain(task_scope)):
            for user in task.user_ids:
                emp = emp_by_user.get(user.id)
                if emp:
                    overdue_by_emp[emp.id] = overdue_by_emp.get(emp.id, 0) + 1

        # Every project participant gets a row, even with all-zero stats: a
        # resource who neither delivered nor is overdue is still a resource and
        # its absence reads as "not on the team". Participants = anyone assigned
        # to at least one project task. One search_read over task assignees
        # keeps it to a single query. Non-project staff (HR, sales, ...) never
        # appear because they are never a task assignee.
        participant_emp_ids = set()
        for t in Task.search_read(
                [('user_ids', '!=', False)] + task_scope, ['user_ids']):
            for uid in t.get('user_ids', []):
                emp = emp_by_user.get(uid)
                if emp:
                    participant_emp_ids.add(emp.id)

        emp_by_id = {e.id: e for e in employees}
        rows = []
        for emp_id in set(delivered_by_emp) | set(overdue_by_emp) | participant_emp_ids:
            emp = emp_by_id.get(emp_id)
            if not emp:
                continue
            # _ft_delivery_kpis rather than _ft_on_time_aggregate: it returns
            # the efficiency and rework figures too, from the same recordset, so
            # DE / OTD / RWR on a row are all measured over exactly the same
            # delivered tasks.
            stats = Task._ft_delivery_kpis(
                delivered_by_emp.get(emp_id, Task.browse()))
            rows.append({
                'employee': emp.name or '',
                'role': emp.job_id.name if emp.job_id else '',
                'delivered': stats['completed'],
                'on_time': stats['on_time'],
                'late': stats['late'],
                'no_deadline': stats['no_deadline'],
                'on_time_rate': stats['rate'],
                'overdue_open': overdue_by_emp.get(emp_id, 0),
                # Resource Performance columns.
                # DE  — (Estimated / Actual) x 100, target 90-110%.
                # OTD — (On time / Delivered with a deadline) x 100, target >=95%.
                # RWR — (Reopened / Delivered) x 100, target <=10%.
                # DWD — Delivered Without Deadline: tasks that carried no
                #       deadline and so could not be judged on time at all.
                #       It is the count OTD had to ignore, which is what makes
                #       a high OTD trustworthy or not.
                'de_rate': stats['efficiency_rate'],
                'otd_rate': stats['rate'],
                'rwr_rate': stats['rework_rate'],
                'dwd': stats['no_deadline'],
            })
        rows.sort(key=lambda r: r['employee'].lower())
        return rows

    def _table_resource_status(self, date_from=None, date_to=None, filters=None):
        """One row per (employee, project), grouped/sorted by employee name.

        Hours Spent    = timesheet hours the employee logged on the project
                         *within the selected period*.
        Estimated      = sum of task.estimated for the project's tasks assigned
                         to that employee (via task assignees -> employee).
        Days Left      = project End Date (project.date) - today.
        Role           = employee's Job Position.
        """
        AAL = self.env['account.analytic.line']
        Emp = self.env['hr.employee']
        Task = self.env['project.task']
        Project = self.env['project.project']

        # Employee lookups (id -> record, user_id -> employee id).
        employees = Emp.search([('active', '=', True)])
        emp_by_id = {e.id: e for e in employees}
        emp_by_user = {e.user_id.id: e.id for e in employees if e.user_id}

        # Project lookups.
        proj_by_id = {p.id: p for p in Project.search([])}

        # Hours spent per (employee, project) from timesheets.
        hours = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to, filters)
                + [('employee_id', '!=', False)],
                ['unit_amount:sum'], ['employee_id', 'project_id'], lazy=False):
            if g.get('employee_id') and g.get('project_id'):
                hours[(g['employee_id'][0], g['project_id'][0])] = \
                    g.get('unit_amount') or 0.0

        # One pass over assigned tasks yields both facts: the estimate per
        # (employee, project) and the full set of pairs the person is actually
        # on. ``assigned`` is what puts a resource on the table even with no
        # logged hours and no estimate — keying the rows off hours/estimates
        # alone hid anyone who had simply not booked time yet, which reads as
        # "not on the project" rather than "nothing logged".
        est = {}
        assigned = set()
        for t in Task.search_read(
                [('project_id', '!=', False), ('user_ids', '!=', False)]
                + self._scope_leaves_via_project(filters),
                ['project_id', 'user_ids', 'estimated']):
            proj_id = t['project_id'][0]
            estimated = t.get('estimated') or 0.0
            for uid in t.get('user_ids', []):
                emp_id = emp_by_user.get(uid)
                if not emp_id:
                    continue
                key = (emp_id, proj_id)
                assigned.add(key)
                if estimated:
                    est[key] = est.get(key, 0.0) + estimated

        today = fields.Date.context_today(self)
        rows = []
        for (emp_id, proj_id) in set(hours) | assigned:
            emp = emp_by_id.get(emp_id)
            proj = proj_by_id.get(proj_id)
            if not emp or not proj:
                continue
            # Hours booked in the period are evidence the work happened, and
            # outrank the project's own dates: time logged against a project
            # that officially closed last year is still time this person spent,
            # and silently dropping it made Hours Spent disagree with the
            # timesheets. The project window only decides pairs with nothing
            # booked, where an estimate carries no date of its own to judge by.
            if not hours.get((emp_id, proj_id)):
                # A date range was asked for, so nothing logged in it means the
                # person was not on this project then — drop the row rather than
                # print a line of zeros. Someone who had not joined yet, or was
                # on something else entirely, otherwise filled the table with
                # rows that answered "no" to the question being asked.
                # Project dates cannot stand in for this: most projects here
                # carry no start or end date at all, and _overlaps_period counts
                # an undated project as overlapping everything.
                if date_from or date_to:
                    continue
                # No range: the all-time view keeps assigned-but-unlogged pairs,
                # so a resource who simply has not booked time yet still reads
                # as being on the project.
                if not self._overlaps_period(
                        proj.date_start, proj.date, date_from, date_to):
                    continue
            days_left = (proj.date - today).days if proj.date else None
            rows.append({
                'employee': emp.name or '',
                'role': emp.job_id.name if emp.job_id else '',
                'project': proj.name or '',
                'status': proj.stage_id.name or '',
                # Project start date, exposed so the client can date-filter the
                # resource rows (they are otherwise timesheet-aggregated totals).
                'start_date': self._iso_date(proj.date_start),
                'days_left': days_left,
                'hours_spent': round(hours.get((emp_id, proj_id), 0.0), 2),
                'estimated': round(est.get((emp_id, proj_id), 0.0), 2),
            })
        rows.sort(key=lambda r: (r['employee'].lower(), r['project'].lower()))
        return rows

    def _chart_project_hours(self, date_from, date_to, filters=None):
        """Bar: estimated / spent / remaining per project.

        Estimated = the sum of the custom ``estimated`` field over the project's
                    tasks — the same source as the Estimated Hrs column in
                    Project Performance and the Estimated Hours KPI card, so all
                    three agree. A whole-project figure with no per-period
                    breakdown, so it stays the same across every filter.

                    NOT ``project.allocated_hours`` ("Estimated Time" on the
                    project form), which this chart used to read.
                    ft_task_hours_tracker hides the core Allocated Time block, so
                    nobody fills that field in: only 4 of 292 active projects
                    carry a non-zero value, against 50 projects holding 23,128h
                    of task-level estimates. The Estimated bar was therefore 0
                    and invisible on virtually every project, and because
                    Remaining is derived from it, that bar was forced to
                    max(0 - spend, 0) == 0 too — leaving Spent as the only bar on
                    the chart. _ft_efficiency_aggregate had already been moved off
                    allocated_hours for exactly this reason.
        Spent     = timesheet hours logged on the project *within the selected
                    period*, so the Spent bars follow the date filter.
        Remaining = max(Estimated - ALL-time spend, 0) — the budget still left
                    on the project, so it holds still while Spent moves with
                    the filter.

        Over Budget = max(ALL-time spend - Estimated, 0) — the mirror of
                    Remaining, so a project is never missing both bars. Remaining
                    is clamped at zero rather than going negative, which meant an
                    overrunning project showed no third bar at all and looked as
                    though the figure were missing; it was simply nothing left.
                    Exactly one of the two is non-zero for any given project.

        Remaining deliberately ignores the date filter. Estimated is a
        whole-project allocation, so subtracting one period's hours from it
        yielded a figure that was neither: a project with 50h allocated and 10h
        already burned in June still reported "50 remaining" whenever June sat
        outside the selected range, contradicting the 10h Actual Hours on the
        project form. A remaining budget is not a per-period quantity.
        """
        Project = self.env['project.project']
        Task = self.env['project.task']
        AAL = self.env['account.analytic.line']

        name_by_proj = {}
        for p in Project.search_read(
                self._scope_leaves_on_project(filters), ['name']):
            name_by_proj[p['id']] = p['name'] or ''

        # Estimated, from the tasks rather than the project's allocated_hours —
        # see the docstring. Same query shape as _table_project_status uses for
        # its Estimated Hrs column, so the chart and the table cannot disagree.
        est_by_proj = {}
        for g in Task.read_group(
                [('project_id', '!=', False)]
                + self._scope_leaves_via_project(filters),
                ['estimated:sum'], ['project_id'], lazy=False):
            if g.get('project_id'):
                est_by_proj[g['project_id'][0]] = g.get('estimated') or 0.0

        # Spent: the selected period only, so the orange bars follow the filter.
        spent_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(date_from, date_to, filters), ['unit_amount:sum'],
                ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        # Spend to date, ignoring the dates only — the basis for Remaining. The
        # header's project/status scope still applies, so the two totals can
        # differ by the period and nothing else.
        spent_all_by_proj = {}
        for g in AAL.read_group(
                self._ts_domain(None, None, filters), ['unit_amount:sum'],
                ['project_id']):
            proj = g.get('project_id')
            if proj:
                spent_all_by_proj[proj[0]] = g.get('unit_amount') or 0.0

        proj_ids = set(est_by_proj) | set(spent_by_proj)
        rows = []
        for pid in proj_ids:
            est = est_by_proj.get(pid, 0.0)
            spent = spent_by_proj.get(pid, 0.0)
            # Nothing to plot for a project with neither an estimate nor spend.
            if not est and not spent:
                continue
            name = name_by_proj.get(pid) or Project.browse(pid).display_name
            spent_all = spent_all_by_proj.get(pid, 0.0)
            # Mirror pair: budget left, or the overrun. Never both.
            remaining = max(est - spent_all, 0.0)
            over = max(spent_all - est, 0.0)
            rows.append((pid, name, est, spent, remaining, over))
        # Every project that has estimated or logged hours, biggest first. The
        # chart scrolls horizontally, so there is no cap on the project count.
        rows.sort(key=lambda r: (r[2] + r[3]), reverse=True)
        return {
            'labels': [r[1] for r in rows],
            'datasets': [
                {'label': 'Estimated', 'data': [round(r[2], 2) for r in rows], 'backgroundColor': '#4F46E5'},
                {'label': 'Spent', 'data': [round(r[3], 2) for r in rows], 'backgroundColor': '#F59E0B'},
                {'label': 'Remaining', 'data': [round(r[4], 2) for r in rows], 'backgroundColor': '#10B981'},
                {'label': 'Over Budget', 'data': [round(r[5], 2) for r in rows], 'backgroundColor': '#EF4444'},
            ],
            'meta': {'project_ids': [r[0] for r in rows]},
        }

    def _chart_billable(self, date_from, date_to, filters=None):
        """Bar: billable vs non-billable hours (by project allow_billable flag)."""
        AAL = self.env['account.analytic.line']
        ts_domain = self._ts_domain(date_from, date_to, filters)
        total = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain, ['unit_amount:sum'], []) if g.get('unit_amount'))
        billable = sum(g['unit_amount'] for g in AAL.read_group(
            ts_domain + [('project_id.allow_billable', '=', True)],
            ['unit_amount:sum'], []) if g.get('unit_amount'))
        non_billable = max(total - billable, 0.0)
        return {
            'labels': ['Billable', 'Non-Billable'],
            'datasets': [{
                'label': 'Hours',
                'data': [round(billable, 2), round(non_billable, 2)],
                'backgroundColor': ['#10B981', '#94A3B8'],
            }],
        }

    def _chart_team_composition(self, filters=None, date_from=None, date_to=None):
        """Pie: developers / testers / trainees / project managers.

        Takes the same scope as the headcount cards, or the pie would keep
        showing the whole company beside four cards reporting one project's team.
        """
        roles = self._role_counts(filters, date_from, date_to)
        return {
            'labels': ['Developers', 'Testers', 'Trainees', 'Project Managers'],
            'datasets': [{
                'data': [roles['dev'], roles['qa'], roles['trainee'], roles['pm']],
                'backgroundColor': ['#4F46E5', '#06B6D4', '#10B981', '#F59E0B'],
            }],
        }

    # Bucket sizes for the progress trend, picked from the span of the range so
    # the X axis never carries more labels than it can legibly show.
    TREND_DAY_SPAN = 31
    TREND_WEEK_SPAN = 120

    def _trend_bucket(self, days):
        """Return the bucket granularity to use for ``days`` (a sorted list)."""
        if not days:
            return 'day'
        span = (days[-1] - days[0]).days
        if span <= self.TREND_DAY_SPAN:
            return 'day'
        if span <= self.TREND_WEEK_SPAN:
            return 'week'
        return 'month'

    def _trend_bucket_key(self, day, bucket):
        """Collapse ``day`` onto the start of its bucket."""
        if bucket == 'week':
            return day - timedelta(days=day.weekday())
        if bucket == 'month':
            return day.replace(day=1)
        return day

    def _trend_bucket_span(self, start, end, bucket):
        """Every bucket key from ``start`` to ``end`` inclusive, in order.

        The trend used to plot only the buckets that happened to hold data, so a
        quiet day simply vanished and the bars either side sat next to each
        other. On a chart whose whole point is the shape over time that reads as
        continuous activity: July 2026 drew 28 bars for 31 days, hiding two idle
        Sundays and a dead Friday. Generating the full span instead means an idle
        bucket is drawn as the zero it is.
        """
        keys = []
        cur = self._trend_bucket_key(start, bucket)
        last = self._trend_bucket_key(end, bucket)
        while cur <= last:
            keys.append(cur)
            if bucket == 'day':
                cur = cur + timedelta(days=1)
            elif bucket == 'week':
                cur = cur + timedelta(days=7)
            else:
                # First of the next month, without dateutil.
                cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
        return keys

    def _trend_bucket_label(self, key, bucket):
        if bucket == 'week':
            return 'Wk of %s' % key.strftime('%d %b')
        if bucket == 'month':
            return key.strftime('%b %Y')
        return key.strftime('%d %b %Y')

    def _chart_progress_trend(self, date_from, date_to, filters=None):
        """Bar: hours logged and tasks completed per bucket within the range.

        Uses ``_read_group`` so each day is a real ``date`` object — sorting on
        those keeps the X axis chronological. (Grouping via ``read_group`` yields
        formatted labels like '03 Jul 2026' that sort alphabetically, which
        scrambled the timeline.)

        Days are then rolled up into day/week/month buckets depending on how
        long the selected range is. Plotting a full year day-by-day produced
        ~250 labels that Chart.js thinned to an arbitrary, uneven-looking subset
        ('01 Jan, 10 Jan, 19 Jan, ...'), which read as noise rather than a
        trend. Bucketing keeps every bar meaningful and every label round.
        """
        AAL = self.env['account.analytic.line']
        Task = self.env['project.task']

        def _as_date(d):
            return d.date() if isinstance(d, datetime) else d

        hours_by_day = {}
        for day, total in AAL._read_group(
                self._ts_domain(date_from, date_to, filters),
                ['date:day'], ['unit_amount:sum']):
            if day:
                hours_by_day[_as_date(day)] = round(total or 0.0, 2)

        tasks_by_day = {}
        try:
            # Bucketed off ft_completion_date through the shared delivery
            # domain, so this series counts exactly what the Tasks Delivered
            # card counts. It previously grouped `state = '1_done'` by
            # date_last_stage_update, which reported almost nothing: stages in
            # Odoo 18 do not set `state`, which is the whole reason
            # _ft_delivery_domain keys off the folded stage instead. Any project
            # whose workflow never writes state explicitly showed a flat zero
            # line beside a healthy Hours Logged series.
            for day, count in Task._read_group(
                    Task._ft_delivery_domain(
                        self._scope_leaves_via_project(filters),
                        date_from, date_to),
                    ['ft_completion_date:day'], ['__count']):
                if day:
                    tasks_by_day[_as_date(day)] = count
        except Exception as e:  # pragma: no cover - defensive against field/state drift
            _logger.warning('Progress-trend task series unavailable: %s', e)

        days = sorted(set(hours_by_day) | set(tasks_by_day))

        # The axis spans the range that was ASKED for, not the days that happen
        # to hold data, so idle buckets are plotted as zero instead of being
        # dropped and making the bars either side look adjacent. With no range
        # given there is nothing to span but the data itself.
        start = fields.Date.to_date(date_from) if date_from else (days[0] if days else None)
        end = fields.Date.to_date(date_to) if date_to else (days[-1] if days else None)
        if not start or not end or end < start:
            return {'labels': [], 'datasets': []}

        # Granularity from the requested span rather than the observed one, so
        # the bucket size does not change just because a quiet week happens to
        # sit at one end of the range.
        bucket = self._trend_bucket([start, end])

        hours_by_bucket = {}
        tasks_by_bucket = {}
        for day in days:
            key = self._trend_bucket_key(day, bucket)
            hours_by_bucket[key] = hours_by_bucket.get(key, 0.0) + hours_by_day.get(day, 0.0)
            tasks_by_bucket[key] = tasks_by_bucket.get(key, 0) + tasks_by_day.get(day, 0)

        keys = self._trend_bucket_span(start, end, bucket)
        return {
            'labels': [self._trend_bucket_label(k, bucket) for k in keys],
            'datasets': [
                {
                    'label': 'Hours Logged',
                    'data': [round(hours_by_bucket.get(k, 0.0), 2) for k in keys],
                    'backgroundColor': 'rgba(79,70,229,0.85)',
                    'borderColor': '#4F46E5', 'borderWidth': 1,
                    'borderRadius': 4, 'yAxisID': 'y',
                },
                {
                    'label': 'Tasks Completed',
                    'data': [tasks_by_bucket.get(k, 0) for k in keys],
                    'backgroundColor': 'rgba(16,185,129,0.85)',
                    'borderColor': '#10B981', 'borderWidth': 1,
                    'borderRadius': 4, 'yAxisID': 'y1',
                },
            ],
        }
