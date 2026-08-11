from datetime import datetime

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError

# Minimum number of characters required in a task title.
TASK_TITLE_MIN_LEN = 20

# Job positions (hr.job) allowed to create tasks. Matched on the lower-cased
# job name, mirroring the classification used elsewhere in the PMS.
TASK_CREATE_JOBS = {
    'technical lead',
    'project manager',
    'project coordinator',
    'project cordinator',   # legacy typo present in source data
}

# Task stage names that mean the work is delivered even when the Kanban "Folded
# in Kanban" flag was never ticked on the stage.
#
# `fold` is Odoo's own marker for a closed stage and remains the primary test,
# but it cannot be the only one. On the production database every delivery figure
# read zero, because 6,768 active tasks sat across 489 non-folded stages and NOT
# ONE task was in a folded stage — the 200 folded "Done" stages are unused
# per-project defaults. The workflow actually in use is Working / Completed /
# Planned / Testing, of which only Completed is final, and nobody had ticked
# Folded on it.
#
# Matching the name as well makes the metrics correct on a stage set whose fold
# flags were never maintained, while still honouring `fold` wherever it IS set.
# Ticking Folded on a stage therefore remains a supported way to mark it final —
# this is an addition, not a replacement.
COMPLETED_STAGE_NAMES = ('Completed',)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    estimated = fields.Float(string='Estimated')
    actual = fields.Float(string='Actual')
    ft_reopen_count = fields.Integer(
        string='Times Reopened',
        default=0,
        readonly=True,
        copy=False,
        tracking=True,
        help="How many times this task was moved back out of a Completed "
             "(folded) stage after having reached one. Drives the Rework Rate. "
             "Counted from the day this feature was installed onwards, so tasks "
             "reopened before then read 0.",
    )
    ft_rework_hours = fields.Float(
        string='Rework Hours',
        compute='_compute_ft_rework_hours',
        store=True,
        readonly=True,
        help="Time logged on this task after it was moved back out of a "
             "completed stage — the second round of effort on work that had "
             "already been delivered. Zero until the task is reopened at least "
             "once; earlier hours stay first-round work.",
    )
    ft_completion_date = fields.Datetime(
        string='Completion Date',
        compute='_compute_ft_completion_date',
        store=True,
        index=True,
        readonly=True,
        help="When this task was delivered — the single date every delivery "
             "metric is measured against. Falls back to the last stage change "
             "when Odoo's own date_end is missing, which happens to any task "
             "that entered a stage before that stage was marked Folded (Odoo "
             "clears date_end when the target stage is not folded). Empty while "
             "the task is open.",
    )
    module_id = fields.Many2one('cus.module',string="Module",required=True)
    wc_id = fields.Char(string='Wc Id')
    task_type = fields.Selection([
        ('user_story', 'User Story'),
        ('internal_call', 'Internal Call'),
        ('external_call', 'External Call'),
    ], string='Task Type', default='user_story', required=True)

    @api.model_create_multi
    def create(self, vals_list):
        # Only a Technical Lead, Project Manager or Project Coordinator may
        # create tasks. Superuser and system administrators bypass the check so
        # data imports, automation and mail-to-task keep working.
        self._check_task_create_permission()
        tasks = super().create(vals_list)
        # Run the required-field checks explicitly. @api.constrains alone is not
        # enough on create: Odoo validates only the fields PRESENT in the values,
        # so leaving estimated and date_deadline out entirely skipped both — a
        # task with no estimate at all sailed through while one explicitly set to
        # 0 was refused. Both methods still exempt superuser, so imports and
        # automation are unaffected.
        tasks._check_estimated_required()
        tasks._check_deadline_required()
        return tasks

    def write(self, vals):
        # Count reopens: a task leaving a delivered stage for an open one is
        # rework. Snapshot which records were in a final stage BEFORE the super()
        # call, because stage_id is what we are about to change.
        #
        # Uses the same _ft_final_stage_ids test as the delivery metrics rather
        # than raw `fold`, or a task moved out of Completed would not be counted
        # as reopened on a stage set whose fold flag is unticked — which is every
        # stage set in this database.
        if 'stage_id' not in vals:
            return super().write(vals)
        final_ids = set(self._ft_final_stage_ids())
        was_final = {t.id: t.stage_id.id in final_ids for t in self}
        res = super().write(vals)
        reopened = self.filtered(
            lambda t: was_final.get(t.id) and t.stage_id.id not in final_ids
        )
        for task in reopened:
            # sudo: the counter is readonly to users, and whoever drags the card
            # back may not have write access to a field they never edit directly.
            task.sudo().ft_reopen_count = task.ft_reopen_count + 1
        return res

    def _check_task_create_permission(self):
        if self.env.su or self.env.user.has_group('base.group_system'):
            return
        employee = self.env.user.employee_id
        job_name = (employee.job_id.name or '').strip().lower() if employee else ''
        if job_name not in TASK_CREATE_JOBS:
            raise UserError(_(
                "You are not allowed to create tasks. Only a Technical Lead, "
                "Project Manager or Project Coordinator can create tasks."
            ))

    # Estimate and deadline are required on every task from here on. They are
    # enforced as constraints rather than with `required=True` on the fields,
    # for two reasons that both matter:
    #
    #   estimated is a Float, so it is never NULL — it defaults to 0.0 and
    #       `required=True` would be satisfied by a zero, enforcing nothing. The
    #       real rule is "> 0", which only a constraint can express.
    #   date_deadline would take a NOT NULL column, and 6,936 of the 7,029 active
    #       tasks have no deadline — the upgrade would simply fail.
    #
    # A constraint also limits the blast radius on that legacy data: it fires on
    # create, and on write only when the field itself is being changed. Editing
    # an old task's description or moving its stage does not trip it, so the
    # backlog stays workable while everything new is complete.
    @api.constrains('estimated')
    def _check_estimated_required(self):
        # Superuser only: imports, migrations and scheduled jobs must not be
        # blocked. A plain administrator IS held to it, like task creation.
        if self.env.su:
            return
        for task in self:
            if task.estimated <= 0:
                raise ValidationError(_(
                    "Estimated time is required.\n\n"
                    "Task: %s\n\n"
                    "Enter how long this task is expected to take. Without it "
                    "the task cannot be counted in Delivery Efficiency, and it "
                    "lands in the Not Estimated figure on the dashboard."
                ) % (task.name or ''))

    @api.constrains('date_deadline')
    def _check_deadline_required(self):
        if self.env.su:
            return
        for task in self:
            if not task.date_deadline:
                raise ValidationError(_(
                    "Deadline is required.\n\n"
                    "Task: %s\n\n"
                    "Set the date this task is due. Without it the task can "
                    "never be judged on time or late — it is excluded from "
                    "On-Time Delivery and counted as Delivered Without Deadline."
                ) % (task.name or ''))

    @api.constrains('name')
    def _check_task_title_length(self):
        # #2 - Task title must be at least TASK_TITLE_MIN_LEN characters.
        for task in self:
            if task.name and len(task.name.strip()) < TASK_TITLE_MIN_LEN:
                raise ValidationError(_(
                    "Task title must be at least %s characters long."
                ) % TASK_TITLE_MIN_LEN)

    @api.depends('timesheet_ids.ft_is_rework', 'timesheet_ids.unit_amount')
    def _compute_ft_rework_hours(self):
        for task in self:
            task.ft_rework_hours = round(sum(
                line.unit_amount for line in task.timesheet_ids
                if line.ft_is_rework
            ), 2)

    @api.model
    def ft_get_final_stage_ids(self):
        """Public wrapper so the web client can ask which stages are final.

        The status-bar confirmation needs this: it used to decide "is this a
        completion?" from the item's own ``isFolded`` flag, which is False on
        every stage in this database, so the dialog never once appeared. Odoo
        refuses RPC to names beginning with an underscore, hence the wrapper
        rather than exposing _ft_final_stage_ids directly.
        """
        return self._ft_final_stage_ids()

    @api.model
    def _ft_final_stage_ids(self):
        """Ids of every task stage that counts as DELIVERED.

        THE single answer to "is this stage finished" for the whole PMS: folded
        stages, plus any stage named in COMPLETED_STAGE_NAMES whether or not
        somebody remembered to tick Folded.

        Resolved to ids rather than filtering on ``stage_id.name`` inside each
        domain, because the stage name is a translated (jsonb) column — comparing
        it in a domain is slower and answers differently per language, and the
        same reasoning already governs the project-stage lookups in
        ft_project_dashboard.

        Archived stages are included: a task can still sit in one, and leaving
        them out would make that work vanish from delivered and open alike.
        """
        return self.env['project.task.type'].with_context(
            active_test=False
        ).search([
            '|',
            ('fold', '=', True),
            ('name', 'in', list(COMPLETED_STAGE_NAMES)),
        ]).ids

    # stage_id.name is in the depends because the set of final stages now turns
    # on the name too: renaming a stage to or from "Completed" has to recompute
    # the tasks sitting in it, or their completion date would silently disagree
    # with what the metrics count.
    @api.depends('date_end', 'date_last_stage_update',
                 'stage_id.fold', 'stage_id.name')
    def _compute_ft_completion_date(self):
        """The delivery date, with a fallback for a missing ``date_end``.

        Odoo stamps ``date_end`` in ``update_date_end()`` only when ``stage_id``
        is written, and writes False whenever the target stage is not folded. So
        a task that entered Completed while that stage was still unfolded — the
        flag being ticked afterwards — sits in a folded stage forever with an
        empty date_end. Filtering delivery on date_end dropped exactly those
        tasks: not counted as delivered, and not counted as open either, because
        their stage IS folded. Silently invisible in both directions.

        ``date_last_stage_update`` is written by the same core code path on every
        stage change, so for those tasks it holds the moment they were completed.
        It is the fallback, not the primary: a reopened-then-reclosed task can
        have a later stage change than its date_end, and date_end is the more
        precise answer whenever it exists.

        Stored so it can be searched and date-ranged, and so that upgrading this
        module backfills every historical task in one recompute.
        """
        # Resolved once for the whole recordset: this compute runs over every
        # task in the database on upgrade.
        final_ids = set(self._ft_final_stage_ids())
        for task in self:
            task.ft_completion_date = (
                (task.date_end or task.date_last_stage_update)
                if task.stage_id.id in final_ids else False
            )

    # ------------------------------------------------------------------
    # On-Time Delivery
    #
    # THE single definition of "delivered" and "on time" for the whole PMS.
    # The project fields (project.project) and the dashboard both call these,
    # so an all-time figure on a project and a date-filtered figure on the
    # dashboard can never disagree about what they are counting.
    # ------------------------------------------------------------------
    @api.model
    def _ft_delivery_domain(self, extra=None, date_from=None, date_to=None):
        """Domain for DELIVERED tasks.

        Delivered = sits in a folded stage (Completed) and carries a completion
        date. A task reopened and closed again counts by its latest completion.

        Completion is read from ``ft_completion_date``, NOT raw ``date_end``:
        Odoo leaves date_end empty on any task that entered a stage before that
        stage was marked Folded, and filtering on it made those tasks vanish from
        the delivered count while their folded stage also kept them out of the
        open count. See ``_compute_ft_completion_date``.

        Keyed off the STAGE, not `state`. Stages do not set state in Odoo 18
        (see the note in views/project_task_views.xml), so counting state
        '1_done' would miss almost everything this DB actually completes.

        Cancelled work is excluded: "Cancelled" is a folded stage in some stage
        sets, and a cancelled task is not a delivery. `state` is only ever set to
        '1_canceled' deliberately, so it is safe as an exclusion even though it
        is unreliable as an inclusion.

        The date range filters on the completion date — i.e. what was DELIVERED
        in the period, not what was created in it.
        """
        dom = [
            ('stage_id', 'in', self._ft_final_stage_ids()),
            ('state', '!=', '1_canceled'),
            ('ft_completion_date', '!=', False),
        ]
        if date_from:
            dom.append(('ft_completion_date', '>=', str(date_from)))
        if date_to:
            # ft_completion_date is a Datetime; span the whole closing day.
            dom.append(('ft_completion_date', '<=', str(date_to) + ' 23:59:59'))
        return dom + (extra or [])

    @api.model
    def _ft_local_date(self, value):
        """A stored UTC value as a calendar date in the reader's timezone.

        Both the completion date and ``date_deadline`` are Datetimes held in UTC, so
        taking ``.date()`` straight off them would bucket work by the UTC day.
        For anything finished late in the local evening that is the WRONG day
        (20:00 UTC is already tomorrow in IST), which would mark on-time work
        late. Converting first puts both sides on the user's calendar.
        """
        if not value:
            return None
        if isinstance(value, datetime):
            return fields.Datetime.context_timestamp(self, value).date()
        return value

    @api.model
    def _ft_on_time_aggregate(self, tasks):
        """Aggregate a recordset of DELIVERED tasks into on-time figures.

        Tasks with no deadline cannot be judged, so they are excluded from the
        denominator and reported separately as ``no_deadline`` — counting them
        as on-time would hand a perfect score to any project that simply never
        sets deadlines.

        On time is judged by CALENDAR DAY, not to the minute. ``date_deadline``
        is a Datetime, so a deadline entered as a day is stored carrying a
        time-of-day; comparing the raw timestamps made a task finished at 13:12
        on its own due date "late" against a 13:00 stamp nobody chose. A
        deadline of the 23rd means end of the 23rd, so any completion on that
        date counts as on time.

        ``rate`` is None (not 0.0) when nothing measurable was delivered, so the
        UI shows "N/A" instead of a 0% that reads as a failure.
        """
        split = self._ft_on_time_split(tasks)
        on_time = len(split['on_time'])
        late = len(split['late'])
        completed = len(tasks)
        measurable = on_time + late
        return {
            'completed': completed,
            'measurable': measurable,
            'no_deadline': completed - measurable,
            'on_time': on_time,
            'late': late,
            'rate': round(on_time / measurable * 100, 2) if measurable else None,
        }

    @api.model
    def _ft_on_time_split(self, tasks):
        """DELIVERED tasks split into on-time and late ids.

        The judgement itself, factored out of ``_ft_on_time_aggregate`` so a
        dashboard card can open exactly the tasks behind its number. Counting
        and listing therefore run the same comparison — a drill-down cannot
        show a different set from the figure that was clicked.

        Tasks with no deadline appear in neither list: they cannot be judged.
        """
        on_time, late = [], []
        for task in tasks:
            if not task.date_deadline:
                continue
            if self._ft_local_date(task.ft_completion_date) <= self._ft_local_date(task.date_deadline):
                on_time.append(task.id)
            else:
                late.append(task.id)
        return {'on_time': on_time, 'late': late}

    @api.model
    def _ft_efficiency_aggregate(self, tasks):
        """Delivery Efficiency for a recordset of DELIVERED tasks.

        (Estimated / Actual) x 100. Target 90-110%: under 90 means the work took
        materially longer than estimated, over 110 means the estimate was padded.

        Only tasks carrying BOTH an estimate and logged time are counted. A task
        estimated at 8h with no timesheet would otherwise divide by zero, and a
        task with time logged but no estimate would drag the ratio toward zero
        while saying nothing about estimation quality. ``unestimated`` reports
        how much work was skipped, so a flattering ratio drawn from three tasks
        out of two hundred is visible rather than trusted.

        Estimated is the custom ``estimated`` field, NOT core ``allocated_hours``.
        ft_task_hours_tracker hides the core Allocated Time block from the task
        form, so ``allocated_hours`` is unreachable in this workflow and reading
        it made the whole metric permanently unmeasurable. ``estimated`` is the
        field the task form actually exposes. Actual stays ``effective_hours``
        (the stored sum of timesheet lines).
        """
        measurable = tasks.filtered(
            lambda t: t.estimated > 0 and t.effective_hours > 0
        )
        estimated = sum(measurable.mapped('estimated'))
        actual = sum(measurable.mapped('effective_hours'))
        return {
            'estimated_hours': round(estimated, 2),
            'actual_hours': round(actual, 2),
            'measurable': len(measurable),
            'unestimated': len(tasks) - len(measurable),
            # None, not 0.0, when nothing is measurable: 0% efficiency reads as
            # catastrophic, while the truth is that nobody estimated anything.
            'rate': round(estimated / actual * 100, 2) if actual else None,
        }

    @api.model
    def _ft_rework_aggregate(self, tasks):
        """Rework figures for a recordset of DELIVERED tasks.

        Two complementary measures, because "how often" and "how expensive" are
        different questions and a team can score well on one while failing the
        other:

          rate       (Tasks reopened / Total delivered) x 100. Target 10% or
                     below. Counts TASKS reopened at least once, not reopen
                     events, so one task bounced five times cannot push it past
                     100%.
          hours_rate (Rework hours / Total hours) x 100 — the share of effort
                     that went into redoing delivered work. A single task
                     reopened once but costing eighty hours barely moves the
                     count rate while dominating this one.

        Rework hours come from the per-line ft_is_rework flag, stamped when the
        time was entered, so they measure the effort that followed a reopen
        rather than everything ever logged on a task that was reopened later.
        """
        completed = len(tasks)
        reworked = len(tasks.filtered(lambda t: t.ft_reopen_count > 0))
        rework_hours = sum(tasks.mapped('ft_rework_hours'))
        total_hours = sum(tasks.mapped('effective_hours'))
        return {
            'completed': completed,
            'reworked': reworked,
            'rate': round(reworked / completed * 100, 2) if completed else None,
            'rework_hours': round(rework_hours, 2),
            # None rather than 0 when nothing was logged: 0% would read as "no
            # rework" when the truth is that there is nothing to measure.
            'hours_rate': (round(rework_hours / total_hours * 100, 2)
                           if total_hours else None),
        }

    @api.model
    def _ft_open_domain(self, extra=None):
        """Domain for OPEN tasks — the complement of ``_ft_delivery_domain``.

        Open = not in a folded stage, i.e. still somewhere in Planned / Working /
        Testing. Keyed off the stage for the same reason delivery is: stages do
        not set `state`, so "not in a closed state" would call almost everything
        open, including finished work.
        """
        # Written as the explicit complement of _ft_final_stage_ids rather than
        # `stage_id.fold = False`, so open and delivered stay exact opposites of
        # one another and no task can fall into both or neither.
        #
        # The stageless leaf is deliberate: a task with no stage at all used to be
        # counted as neither open nor delivered, because traversing an empty
        # many2one matches nothing — 173 active tasks were invisible to both
        # figures on the production restore. It is certainly not delivered, so it
        # is open.
        return [
            '|',
            ('stage_id', '=', False),
            ('stage_id', 'not in', self._ft_final_stage_ids()),
        ] + (extra or [])

    @api.model
    def _ft_overdue_open_domain(self, extra=None):
        """Domain for open tasks already past their deadline.

        The companion to the on-time rate, and the reason to trust it. The rate
        only looks at work that finished, so a task six months late and still
        open never appears in it — a team could score 100% by never closing its
        late work. This is what stops that hiding. It is a snapshot of now, so
        it is deliberately NOT filtered by the report's date range.
        """
        return self._ft_open_domain([
            ('date_deadline', '!=', False),
            ('date_deadline', '<', fields.Datetime.now()),
        ] + (extra or []))

    @api.model
    def _ft_overdue_open_count(self, extra=None):
        """Count of open, past-deadline tasks. See ``_ft_overdue_open_domain``."""
        return self.search_count(self._ft_overdue_open_domain(extra))

    @api.model
    def _ft_delivery_kpis(self, tasks):
        """All three delivery KPIs for one recordset of DELIVERED tasks.

        One place to add a fourth. Efficiency and rework keys are prefixed so
        they cannot collide with the on-time keys they are merged into.
        """
        stats = self._ft_on_time_aggregate(tasks)
        efficiency = self._ft_efficiency_aggregate(tasks)
        rework = self._ft_rework_aggregate(tasks)
        stats.update({
            'efficiency_rate': efficiency['rate'],
            'estimated_hours': efficiency['estimated_hours'],
            'actual_hours': efficiency['actual_hours'],
            'unestimated': efficiency['unestimated'],
            'rework_rate': rework['rate'],
            'reworked': rework['reworked'],
            'rework_hours': rework['rework_hours'],
            'rework_hours_rate': rework['hours_rate'],
        })
        return stats

    @api.model
    def _ft_on_time_stats(self, extra=None, date_from=None, date_to=None):
        """All delivery KPIs for any scope. See ``_ft_delivery_domain``."""
        tasks = self.search(self._ft_delivery_domain(extra, date_from, date_to))
        stats = self._ft_delivery_kpis(tasks)
        stats['overdue_open'] = self._ft_overdue_open_count(extra)
        return stats

    @api.model
    def _ft_on_time_stats_by_project(self, project_ids, date_from=None, date_to=None):
        """``{project_id: stats}`` — one search for the whole set, not one each."""
        tasks = self.search(self._ft_delivery_domain(
            [('project_id', 'in', list(project_ids))], date_from, date_to))
        # Group ids and browse once per project: repeatedly unioning recordsets
        # (recs |= task) rebuilds the set on every step.
        ids_by_project = {}
        for task in tasks:
            ids_by_project.setdefault(task.project_id.id, []).append(task.id)
        return {
            pid: self._ft_delivery_kpis(self.browse(ids))
            for pid, ids in ids_by_project.items()
        }

    @api.model
    def _ft_overdue_open_count_by_project(self, project_ids):
        """``{project_id: count}`` of open, past-deadline tasks. One query."""
        groups = self.read_group(
            self._ft_overdue_open_domain([('project_id', 'in', list(project_ids))]),
            ['id'], ['project_id'], lazy=False,
        )
        return {
            g['project_id'][0]: g['__count']
            for g in groups if g.get('project_id')
        }
