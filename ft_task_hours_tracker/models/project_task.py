import logging
import math
from datetime import datetime, time, timedelta

import pytz

from odoo import models, fields, api, _
from odoo.fields import Domain

from odoo.addons.bt_project_customization.models.project_task import (
    COMPLETED_STAGE_NAMES,
)

_logger = logging.getLogger(__name__)

# A task whose Deadline (local calendar day) lies MORE than this many days
# before today is treated as abandoned: the daily cron moves it to its
# project's Completed stage (once — see ft_auto_completed). Time is then
# refused only because the task is completed; reopening it lifts that.
FT_OVERDUE_AUTO_COMPLETE_DAYS = 30
# Tasks handled between two commits of the auto-complete cron.
FT_AUTO_COMPLETE_BATCH_SIZE = 100

# Map a job-position name (lower-cased, stripped) to an hours bucket.
# Any position whose name starts with "trainee" is classified as 'trainee'.
FT_JOB_BUCKET_MAP = {
    'software developer': 'dev',
    'technical lead': 'dev',
    'software tester': 'qa',
    'testing lead': 'qa',
    'project manager': 'pm',
    'project cordinator': 'pm',
    'project coordinator': 'pm',
    'business analyst': 'ba',
}
FT_BUCKETS = ('dev', 'qa', 'pm', 'ba', 'trainee')


class ProjectTask(models.Model):
    _inherit = 'project.task'

    # The task's own stage_id is the TASK stage (Planned / Working / …). This is
    # the stage of the PROJECT it belongs to (General / Discovery / Development
    # / …), so both can be shown side by side in the task list.
    # Stored, not just related: a non-stored related column cannot be sorted or
    # grouped in a list view, which is most of the point of having it there.
    ft_project_stage_id = fields.Many2one(
        related='project_id.stage_id',
        string='Project Stage',
        store=True,
        readonly=True,
        index=True,
    )

    ft_total_hours_taken = fields.Float(
        string='Total Hours Taken',
        compute='_compute_ft_total_hours_taken',
        store=True,
        readonly=True,
        help='Mirrors the standard Hours Spent (effective_hours) for this task.',
    )
    ft_hours_exceeded = fields.Boolean(
        string='Exceeds Time Limit',
        compute='_compute_ft_total_hours_taken',
        store=True,
        help='True when Total Hours Taken exceeds the global task time limit.',
    )
    ft_allow_billable = fields.Boolean(
        related='project_id.allow_billable',
        string='Is Billable Project',
        store=False,
    )
    ft_billing_status = fields.Selection(
        [
            ('non_billed', 'Non Billed'),
            ('billed', 'Billed'),
            ('rejected', 'Rejected'),
        ],
        string='Billing Status',
        default='non_billed',
        required=True,
        tracking=True,
        help='Whether the work on this task is Non Billed, Billed, or was '
             'Rejected for billing. New tasks start as Non Billed.',
    )
    # Billable Hours follows Actual Hours until somebody edits it, and then
    # stops. Without that stickiness the override would be pointless: the next
    # timesheet line logged against the task would silently reset the figure
    # back to Actual Hours and the correction would be lost.
    #
    # The manual value is kept in its own column rather than read back off this
    # field, because a compute that reads the field it is computing recurses.
    ft_billable_hours = fields.Float(
        string='Billable Hours',
        compute='_compute_ft_billable_hours',
        inverse='_inverse_ft_billable_hours',
        store=True,
        readonly=False,
        help='Hours that can be billed. Defaults to Actual Hours; edit it to '
             'override, after which it no longer follows Actual Hours.',
    )
    ft_billable_hours_manual = fields.Boolean(
        string='Billable Hours Overridden',
        default=False,
        copy=False,
        help='Technical: set once Billable Hours has been edited by hand.',
    )
    ft_billable_hours_override = fields.Float(
        string='Billable Hours (manual value)',
        copy=False,
        help='Technical: the hand-entered Billable Hours, preserved so later '
             'timesheet entries cannot overwrite it.',
    )
    ft_non_billable_hours = fields.Float(
        string='Non Billable Hours',
        compute='_compute_ft_non_billable_hours',
        store=True,
        readonly=True,
        help='Actual Hours minus Billable Hours.',
    )
    # store=False (computed live, like the project-level fields) so historical
    # tasks always reflect the employee's CURRENT job position. Stored values
    # would freeze at whatever was first computed and never refresh.
    ft_dev_hours = fields.Float(
        string='Dev Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Software Developer / Technical Lead employees.',
    )
    ft_qa_hours = fields.Float(
        string='QA Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Software Tester / Testing Lead employees.',
    )
    ft_pm_hours = fields.Float(
        string='PM Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Project Manager / Project Coordinator employees.',
    )
    ft_ba_hours = fields.Float(
        string='BA Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by Business Analyst employees.',
    )
    ft_trainee_hours = fields.Float(
        string='Trainee Hours',
        compute='_compute_ft_job_hours',
        store=False,
        readonly=True,
        help='Hours logged on this task by any Trainee job position.',
    )
    ft_dev_hours_exceeded = fields.Boolean(
        string='Dev Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when Dev Hours exceeds the task time limit.',
    )
    ft_qa_hours_exceeded = fields.Boolean(
        string='QA Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when QA Hours exceeds the task time limit.',
    )
    ft_pm_hours_exceeded = fields.Boolean(
        string='PM Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when PM Hours exceeds the task time limit.',
    )
    ft_ba_hours_exceeded = fields.Boolean(
        string='BA Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when BA Hours exceeds the task time limit.',
    )
    ft_trainee_hours_exceeded = fields.Boolean(
        string='Trainee Hours Exceeded',
        compute='_compute_ft_job_hours',
        store=False,
        help='True when Trainee Hours exceeds the task time limit.',
    )
    # Not stored: the value changes every day without the record changing, so
    # a stored column would be stale by the next morning. Computed on read in
    # the reader's timezone instead. The search method makes it filterable;
    # sorting a list on it is not possible (non-stored).
    ft_task_age = fields.Integer(
        string='Age (Days)',
        compute='_compute_ft_task_age',
        search='_search_ft_task_age',
        store=False,
        readonly=True,
        help='Whole calendar days since the task was created, counted in '
             'your timezone. 0 on the day of creation.',
    )
    # Set by _cron_ft_auto_complete_overdue_tasks when it moves the task to
    # Completed, and never reset. The cron skips flagged tasks, so a task a
    # user reopens after auto-completion stays open (and takes time again)
    # instead of being closed again the next morning.
    ft_auto_completed = fields.Boolean(
        string='Auto-completed (overdue)',
        copy=False,
        readonly=True,
        help='Set when the daily overdue cron moved this task to Completed '
             'because its Deadline had passed more than 30 days earlier. A '
             'task flagged this way is never auto-completed again, so once '
             'it is reopened it stays open and timesheets can be logged on '
             'it.',
    )

    @api.model
    def _ft_job_bucket(self, job):
        """Classify a job position into one of dev/qa/pm/ba/trainee by its name.
        Returns False for any other (or empty) job position.

        Read the job name with sudo: hr.job is restricted to HR officers, but
        regular project users still need their timesheet hours bucketed."""
        if not job:
            return False
        name = (job.sudo().name or '').strip().lower()
        if not name:
            return False
        if name.startswith('trainee'):
            return 'trainee'
        return FT_JOB_BUCKET_MAP.get(name, False)

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.employee_id.job_id')
    def _compute_ft_job_hours(self):
        # Classify by the EMPLOYEE's current job position rather than a stored
        # value, so historical lines map correctly and recompute when the
        # employee's job position changes. Mirrors the project-level compute.
        time_limit = float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )
        for task in self:
            totals = dict.fromkeys(FT_BUCKETS, 0.0)
            for line in task.timesheet_ids:
                # hr.employee.job_id is delegated through the HR-restricted
                # version_id field in Odoo 19. Normal project users may read
                # timesheets but not that HR version, so elevate only the job
                # lookup used for classification.
                bucket = self._ft_job_bucket(line.employee_id.sudo().job_id)
                if bucket:
                    totals[bucket] += line.unit_amount
            task.ft_dev_hours = totals['dev']
            task.ft_qa_hours = totals['qa']
            task.ft_pm_hours = totals['pm']
            task.ft_ba_hours = totals['ba']
            task.ft_trainee_hours = totals['trainee']
            task.ft_dev_hours_exceeded = time_limit > 0 and totals['dev'] > time_limit
            task.ft_qa_hours_exceeded = time_limit > 0 and totals['qa'] > time_limit
            task.ft_pm_hours_exceeded = time_limit > 0 and totals['pm'] > time_limit
            task.ft_ba_hours_exceeded = time_limit > 0 and totals['ba'] > time_limit
            task.ft_trainee_hours_exceeded = time_limit > 0 and totals['trainee'] > time_limit

    @api.depends('ft_total_hours_taken', 'ft_billable_hours_manual',
                 'ft_billable_hours_override')
    def _compute_ft_billable_hours(self):
        """Track Actual Hours, unless the figure has been overridden by hand.

        Every branch assigns: a stored compute that leaves a record untouched
        raises "compute method failed to assign".
        """
        for task in self:
            task.ft_billable_hours = (
                task.ft_billable_hours_override if task.ft_billable_hours_manual
                else task.ft_total_hours_taken
            )

    def _inverse_ft_billable_hours(self):
        """Remember a hand-entered figure and stop following Actual Hours."""
        for task in self:
            task.ft_billable_hours_override = task.ft_billable_hours
            task.ft_billable_hours_manual = True

    @api.depends('ft_total_hours_taken', 'ft_billable_hours')
    def _compute_ft_non_billable_hours(self):
        """Whatever of the logged time is not being billed.

        Left as a plain subtraction, so entering Billable Hours above Actual
        Hours shows as a negative rather than being quietly clamped to zero and
        hiding the mistake.
        """
        for task in self:
            task.ft_non_billable_hours = (
                task.ft_total_hours_taken - task.ft_billable_hours)

    @api.depends('effective_hours')
    def _compute_ft_total_hours_taken(self):
        for task in self:
            task.ft_total_hours_taken = task.effective_hours
            # Whole-task total is no longer treated as over-limit. Only the
            # per-role (Dev / QA / PM / BA / Trainee) 16h limits apply, so the
            # task's combined total across roles is never flagged as exceeded.
            task.ft_hours_exceeded = False

    # ------------------------------------------------------------------
    # Task age
    # ------------------------------------------------------------------
    @api.model
    def _ft_local_midnight_utc(self, day):
        """Naive UTC datetime at which local calendar ``day`` starts.

        Local = the environment's timezone (context tz, else the user's, else
        UTC), the same one ``fields.Date.context_today`` and ``_ft_local_date``
        read, so domains built from it agree with the computed values.
        """
        tz = self.env.tz
        local = tz.localize(datetime.combine(day, time.min))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    @api.depends('create_date')
    @api.depends_context('tz', 'uid')
    def _compute_ft_task_age(self):
        today = fields.Date.context_today(self)
        for task in self:
            created = task._ft_local_date(task.create_date)
            task.ft_task_age = max((today - created).days, 0) if created else 0

    def _search_ft_task_age(self, operator, value):
        """Translate an age condition into a create_date range.

        age >= n  <=>  created on/before local day (today - n)
                  <=>  create_date <  start of local day (today - n + 1)
        age <= n  <=>  create_date >= start of local day (today - n)
        """
        today = fields.Date.context_today(self)

        def day_start(days_ago):
            return self._ft_local_midnight_utc(today - timedelta(days=days_ago))

        if operator == 'in':
            ages = {int(v) for v in value if v not in (False, None)}
            if not ages:
                return Domain.FALSE
            return Domain.OR([
                Domain('create_date', '>=', day_start(age))
                & Domain('create_date', '<', day_start(age - 1))
                for age in ages
            ])
        if operator not in ('<', '<=', '>', '>=') or value in (False, None):
            return NotImplemented
        if operator == '>':
            operator, value = '>=', math.floor(value) + 1
        elif operator == '<':
            operator, value = '<=', math.ceil(value) - 1
        elif operator == '>=':
            value = math.ceil(value)
        else:
            value = math.floor(value)
        if operator == '>=':
            return Domain('create_date', '<', day_start(value - 1))
        return Domain('create_date', '>=', day_start(value))

    # ------------------------------------------------------------------
    # Long-overdue tasks: one-time auto-completion
    # ------------------------------------------------------------------
    def _ft_is_long_overdue(self):
        """True when the Deadline's local day is more than
        FT_OVERDUE_AUTO_COMPLETE_DAYS days before today (local)."""
        self.ensure_one()
        deadline = self._ft_local_date(self.date_deadline)
        if not deadline:
            return False
        today = fields.Date.context_today(self)
        return (today - deadline).days > FT_OVERDUE_AUTO_COMPLETE_DAYS

    @api.model
    def _ft_long_overdue_cutoff(self):
        """UTC instant such that ``date_deadline < cutoff`` is exactly
        ``_ft_is_long_overdue()`` in the current timezone.

        Overdue by more than N days = local deadline day <= today - (N + 1)
        = deadline strictly before local midnight starting day today - N.
        """
        today = fields.Date.context_today(self)
        return self._ft_local_midnight_utc(
            today - timedelta(days=FT_OVERDUE_AUTO_COMPLETE_DAYS))

    @api.model
    def _ft_cron_tz_env(self):
        """Give a cron (run as OdooBot, which has no timezone) a calendar.

        Without one, "today" and the deadline's day would be read in UTC while
        users see them in their own zone. Falls back to the company's
        timezone, then to the main administrator's.
        """
        tz = (self.env.context.get('tz') or self.env.user.tz
              or self.env.company.partner_id.tz)
        if not tz:
            admin = self.env.ref('base.user_admin', raise_if_not_found=False)
            tz = admin and admin.sudo().tz
        return self.with_context(tz=tz) if tz else self

    def _ft_completed_stage_for_project(self, cache):
        """The project's own Completed stage, or an empty recordset.

        A stage named in COMPLETED_STAGE_NAMES that is attached to the task's
        project (project_ids) and is not a personal stage; lowest sequence
        wins if a project somehow carries several. Archived stages are not
        candidates. ``cache`` maps project id -> stage across one cron run.
        """
        self.ensure_one()
        project = self.project_id
        if project.id not in cache:
            Stage = self.env['project.task.type'].with_context(lang='en_US')
            cache[project.id] = Stage.search([
                ('name', 'in', list(COMPLETED_STAGE_NAMES)),
                ('user_id', '=', False),
                ('project_ids', 'in', project.ids),
            ], order='sequence, id', limit=1)
        return cache[project.id]

    def _ft_auto_complete_long_overdue(self, final_ids, stage_cache):
        """Move one long-overdue task to Completed. Returns 'done',
        'skipped' or 'failed'; never raises."""
        self.ensure_one()
        task = self
        # Re-checked per task: the candidate list may be stale by now (a user
        # completed it, moved the deadline, cancelled it...).
        if (not task.exists() or not task.active or not task.project_id
                or task.ft_auto_completed
                or task.stage_id.id in final_ids
                or task.state == '1_canceled'
                or not task._ft_is_long_overdue()):
            return 'skipped'
        stage = task._ft_completed_stage_for_project(stage_cache)
        if not stage:
            _logger.warning(
                "Auto-complete overdue tasks: project %s (id %s) has no "
                "Completed stage; task %s (id %s) left in stage %r",
                task.project_id.display_name, task.project_id.id,
                task.name, task.id, task.stage_id.name)
            return 'skipped'
        deadline = task._ft_local_date(task.date_deadline)
        try:
            with self.env.cr.savepoint():
                task.with_context(ft_auto_complete_overdue=True).write(
                    {'stage_id': stage.id, 'ft_auto_completed': True})
                task.message_post(
                    body=_(
                        "Automatically moved to %(stage)s: the deadline "
                        "(%(deadline)s) passed more than %(days)s days ago. "
                        "Timesheets can no longer be logged on this task "
                        "unless it is reopened.",
                        stage=stage.name,
                        deadline=deadline,
                        days=FT_OVERDUE_AUTO_COMPLETE_DAYS,
                    ),
                    subtype_xmlid='mail.mt_note',
                )
        except Exception:  # noqa: BLE001 - one bad task must not stop the run
            _logger.exception(
                "Auto-complete overdue tasks: could not complete task %s "
                "(id %s)", task.name, task.id)
            return 'failed'
        return 'done'

    @api.model
    def _cron_ft_auto_complete_overdue_tasks(
            self, batch_size=FT_AUTO_COMPLETE_BATCH_SIZE):
        """Daily: complete every task more than 30 days past its Deadline.

        Runs as superuser (sudo) on purpose. The only stage-move guards on a
        plain ``stage_id`` write are bt_project_customization's
        _check_planned_stage_write and _check_user_story_stage_move, which
        restrict *which person* may make a move (e.g. only QA may sign a User
        Story off from Testing) and both exempt env.su. The cron is not a
        person, so those checks have nothing to judge. Everything else in
        the write chain still runs: date_end / state=1_done / Completed By
        (OdooBot) / work end stamps, chatter tracking of the stage change.

        Sweeps every match, so tasks that were already overdue when this was
        installed are caught on the first run. Each task is completed at most
        once: the move sets ``ft_auto_completed`` and flagged tasks are left
        out of the search, so a user who reopens one (to log more time on it)
        is not overruled by the next run. Commits every ``batch_size``
        tasks through the cron progress API; if the run's time budget is
        exhausted, the remaining count makes Odoo reschedule it right away.
        Each task is written inside its own savepoint, so one failure is
        logged and the rest of the batch carries on.
        """
        Task = self.sudo()._ft_cron_tz_env()
        final_ids = Task._ft_final_stage_ids()
        domain = [
            ('project_id', '!=', False),
            ('is_template', '=', False),
            ('date_deadline', '!=', False),
            ('date_deadline', '<', Task._ft_long_overdue_cutoff()),
            ('stage_id', 'not in', final_ids),
            ('state', '!=', '1_canceled'),
            ('ft_auto_completed', '=', False),
        ]
        task_ids = Task.search(domain, order='date_deadline, id').ids
        in_cron = bool(self.env.context.get('cron_id'))
        IrCron = self.env['ir.cron']
        if in_cron:
            IrCron._commit_progress(remaining=len(task_ids))
        counts = {'done': 0, 'skipped': 0, 'failed': 0}
        stage_cache = {}
        pending = task_ids
        while pending:
            batch, pending = pending[:batch_size], pending[batch_size:]
            for task in Task.browse(batch):
                outcome = task._ft_auto_complete_long_overdue(
                    final_ids, stage_cache)
                counts[outcome] += 1
            if in_cron:
                time_left = IrCron._commit_progress(
                    len(batch), remaining=len(pending))
                if pending and time_left <= 0:
                    break
        _logger.info(
            "Auto-complete overdue tasks: %s candidate(s); %s completed, "
            "%s skipped, %s failed, %s left for the next run",
            len(task_ids), counts['done'], counts['skipped'],
            counts['failed'], len(pending))
        return counts
