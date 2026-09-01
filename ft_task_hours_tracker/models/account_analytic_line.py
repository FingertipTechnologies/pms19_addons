import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    ft_trainee_id = fields.Many2one(
        'hr.employee',
        string='Trainee',
        readonly=True,
        copy=False,
        index=True,
        help="The employee who logged this time, recorded only when they held "
             "a Trainee job position AT THE TIME of entry. Empty for everybody "
             "else, so grouping on it lists each trainee by name and leaves "
             "all other time under None.",
    )

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(),
                    offset=0, limit=None, order=None):
        """Leave everybody else's time out when grouping by Trainee.

        ft_trainee_id is empty on every non-trainee line, so grouping on it
        produced a "None" bucket holding all 38,014 of them — a group that is
        not a trainee, dwarfs the real ones, and dragged the list's total to
        67,226 h when the question being asked was how much time the trainees
        spent. Filtering the domain rather than dropping the group afterwards
        keeps the group counts, the aggregates and the footer total consistent
        with each other, and it makes expanding a group show the same records
        it was counted from.

        Scoped to the groupby actually asking for trainees; nothing else in the
        PMS groups on this field, and reading or searching it is untouched.
        """
        if 'ft_trainee_id' in groupby:
            domain = Domain.AND([
                domain or [],
                [('ft_trainee_id', '!=', False)],
            ])
        return super()._read_group(
            domain, groupby, aggregates, having, offset, limit, order)

    def _ft_vals_trainee_employee(self, vals):
        """The employee behind ``vals``, but only if they are a trainee now.

        Returns an empty recordset for everyone else, which is what leaves
        non-trainee time out of the named groups.

        Employee resolution mirrors what Odoo does when the field is left out
        of the values: an explicit employee_id wins, otherwise the line belongs
        to user_id, otherwise to whoever is creating it.

        Delegates the classification to _ft_job_bucket so "what counts as a
        trainee" has exactly one definition across the PMS instead of a second
        copy here that could drift. That helper also reads the job name with
        sudo, which is what keeps this from raising an AccessError for users
        without HR rights — hr.job is readable only by HR officers.
        """
        employee_id = vals.get('employee_id')
        if employee_id:
            employee = self.env['hr.employee'].browse(employee_id)
        elif vals.get('user_id'):
            # sudo: booking time for somebody else must not depend on being
            # able to read their user record.
            employee = self.env['res.users'].sudo().browse(
                vals['user_id']).employee_id
        else:
            employee = self.env.user.employee_id
        if self._ft_line_bucket(employee) == 'trainee':
            return employee
        return self.env['hr.employee']

    @api.model
    def _ft_backfill_trainee_id(self, employees=None):
        """Stamp existing lines whose employee currently holds a Trainee job.

        Pass ``employees`` to scope the work to a specific hr.employee
        recordset — that is what makes it cheap enough to run from
        hr.employee.write every time somebody's job position changes. Left out,
        it sweeps every employee.

        Lives here rather than inside a single migration because the flag can
        only ever be backfilled from CURRENT job positions, and those get
        filled in gradually: the first upgrade ran against a database where
        nobody was mapped to a Trainee position yet and so had nothing to do.
        Every time HR maps another batch of employees, that batch's history
        needs picking up, and re-running an upgrade should not be the only way.

        Additive on purpose — it fills the field, never clears it. A line
        already stamped as trainee time keeps it even if that person has since
        been promoted, which is the whole point of freezing the value on entry.
        That also makes it safe to run as many times as you like.

        Raw SQL, mirroring the bt_project_customization migrations: this must
        not fire this model's write() guards, retrigger stored computes across
        28,500 rows, or write a mail.tracking row per line. The trainee job
        list still comes from _ft_job_bucket rather than being restated in SQL,
        so there is only one definition of "trainee" in the codebase.
        """
        if employees is not None and not employees:
            return 0

        Task = self.env['project.task']
        # sudo: hr.job is readable only by HR officers, and this runs from
        # hr.employee.write as whoever made the edit.
        # active_test=False: an archived job position still explains the hours
        # logged by whoever held it.
        trainee_job_ids = [
            job.id
            for job in self.env['hr.job'].sudo().with_context(
                active_test=False).search([])
            if Task._ft_job_bucket(job) == 'trainee'
        ]
        if not trainee_job_ids:
            _logger.info(
                "ft_trainee_id backfill: no Trainee job positions exist yet, "
                "nothing to stamp"
            )
            return 0

        query = """
            UPDATE account_analytic_line l
               SET ft_trainee_id = l.employee_id
              FROM hr_employee e
             WHERE l.employee_id = e.id
               AND e.job_id IN %s
               AND l.ft_trainee_id IS NULL
        """
        params = [tuple(trainee_job_ids)]
        if employees is not None:
            query += " AND l.employee_id IN %s"
            params.append(tuple(employees.ids))

        # Flush before the UPDATE. It reads hr_employee.job_id straight from
        # the table, but the caller that matters most — hr.employee.write —
        # has only just assigned it, and the ORM still holds that value in
        # cache with nothing written to the table yet. Unflushed, the
        # `e.job_id IN %s` test matched no rows at all: the hook stamped zero
        # lines and said so in the log, so a trainee's history stayed missing
        # from the Trainee group until the next module upgrade happened to run
        # the sweep below from a migration — a fresh transaction, where the
        # job position was already in the table, and so the only path that
        # ever actually worked.
        #
        # account.analytic.line is flushed for the mirror-image reason: lines
        # written earlier in this same transaction are not in the table yet
        # either, so the UPDATE would skip them, and a pending ft_trainee_id
        # would afterwards be flushed straight over the top of what it set.
        self.env['hr.employee'].flush_model(['job_id'])
        self.flush_model(['employee_id', 'ft_trainee_id'])

        self.env.cr.execute(query, params)
        count = self.env.cr.rowcount
        # The rows were changed behind the ORM's back.
        self.invalidate_model(['ft_trainee_id'])
        _logger.info(
            "ft_trainee_id backfill: stamped %s timesheet lines as trainee "
            "time across %s Trainee job positions",
            count, len(trainee_job_ids),
        )
        return count

    def _ft_check_task_not_completed(self, task):
        """Refuse time entry on a task sitting in a Completed (folded) stage.

        Time logged after delivery is what makes rework invisible: the hours
        land on a task that already counts as finished, so the extra effort
        never shows up as a reopen and the Rework Rate stays flattering. Making
        the person move the task back to Working first is what turns that
        second round of work into a counted reopen.

        Uses ``_ft_final_stage_ids`` — the one definition of "delivered" for the
        whole PMS — rather than testing ``stage_id.fold`` directly. That
        distinction is the entire reason this guard had never once fired: the
        production stage set has "Completed" UNFOLDED, so fold was False on every
        completed task, time went straight onto delivered work, nobody was ever
        made to reopen anything, and ft_reopen_count sat at 0 across all 7,028
        active tasks — leaving Rework Rate a permanent 0%.

        Superuser is exempt so imports, migrations and scheduled jobs are not
        blocked; a plain administrator is NOT, because admins log time too and
        exempting them would leave the rule unenforced for the people most
        likely to bypass it.
        """
        if self.env.su or not task:
            return
        if task.stage_id.id not in self.env['project.task']._ft_final_stage_ids():
            return
        raise UserError(_(
            'This task is completed — timesheets cannot be logged on it.\n\n'
            'Task: %s\n'
            'Stage: %s\n\n'
            'If more work is needed, move the task back to Working first. '
            'Reopening it that way is recorded as rework and counts towards '
            "the project's Rework Rate."
        ) % (task.name, task.stage_id.name))

    def _ft_check_task_required(self, project, task_id):
        """Refuse project time that is not booked against a task.

        Time on a project with no task is real spend that no task-level figure
        can ever see: it cannot carry an estimate, a billing status, or a role,
        and it is invisible to Delivery Efficiency and to every hours card that
        reads task fields. 1,356 lines — 3.4% of all project time, 1,825 h in
        2026 alone — had accumulated that way, which is exactly the Non-Task
        Hours figure on the dashboard.

        Applies to any line carrying a project, billable or not: the reason has
        nothing to do with invoicing. Analytic lines with no project at all are
        untouched, being accounting entries rather than timesheets.

        Superuser is exempt so imports and automation keep working; a plain
        administrator is not, for the same reason as the completed-task guard.
        """
        if self.env.su or not project or task_id:
            return
        raise UserError(_(
            'A task is required on timesheet entries.\n\n'
            'Project: %s\n\n'
            'Pick the task this time was spent on. Time booked on a project '
            'without a task cannot be estimated, billed, or attributed to a '
            'role, and it will not appear in any task-based report.'
        ) % (project.display_name,))

    def _get_task_time_limit(self):
        return float(
            self.env['ir.config_parameter'].sudo().get_param(
                'ft_task_hours_tracker.default_time_limit', default=0.0
            )
        )

    def _is_billable_project(self, project):
        return bool(project and project.allow_billable)

    def _check_single_entry_hours(self, unit_amount):
        time_limit = self._get_task_time_limit()
        if time_limit > 0 and unit_amount > time_limit:
            raise UserError(_(
                'A single timesheet entry cannot exceed %.2f hours.\n'
                'Please split your time into multiple entries.'
            ) % time_limit)

    # Job-position buckets shown on the task form (Dev / QA / PM / BA / Trainee).
    # The time limit applies to EACH bucket separately, mirroring the per-field
    # warning.
    _FT_BUCKET_LABELS = {
        'dev': 'Development',
        'qa': 'QA',
        'pm': 'Project Management',
        'ba': 'Business Analysis',
        'trainee': 'Trainee',
    }

    def _ft_line_bucket(self, employee):
        """Return the dev/qa/pm/ba/trainee bucket for a line's employee, or False.

        sudo on the employee: since 19.0 hr.employee delegates job_id to
        hr.version (_inherits), so reading it traverses hr.employee.version_id,
        which carries groups="hr.group_hr_user". A regular user logging their
        own time is not an HR officer, so the bare read raised AccessError.
        """
        return self.env['project.task']._ft_job_bucket(employee.sudo().job_id)

    def _ft_existing_bucket_hours(self, task, bucket, exclude_line=None):
        """Sum the hours already logged on `task` for the given job-position
        bucket, optionally excluding one line (the one being edited)."""
        total = 0.0
        ProjectTask = self.env['project.task']
        for line in task.timesheet_ids:
            if exclude_line and line.id and line.id == exclude_line.id:
                continue
            # Classify by the employee's current job position, consistent with
            # the task/project hour computes.
            if ProjectTask._ft_job_bucket(line.employee_id.sudo().job_id) == bucket:
                total += line.unit_amount
        return total

    def _check_department_time_limit(self, task, bucket, new_bucket_total):
        time_limit = self._get_task_time_limit()
        if task and bucket and time_limit > 0 and new_bucket_total > time_limit:
            label = self._FT_BUCKET_LABELS.get(bucket, bucket)
            raise UserError(_(
                '%s time limit reached!\n\n'
                'Task: %s\n'
                'Time Limit: %.2f hours\n\n'
                'You cannot log more %s hours as it would exceed the time limit. '
                'Please create a new task to continue the work.'
            ) % (label, task.name, time_limit, label))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Stamp the trainee from the employee's job position AT THE TIME OF
            # ENTRY, then leave it alone for good. Decided on creation rather
            # than computed from the employee later because it is a fact about
            # when the work happened: promoting a trainee next month must not
            # retroactively turn this month's training hours into ordinary
            # hours. Only the time they log after the promotion counts as
            # non-trainee. Same reasoning as ft_is_rework on this model.
            #
            # Set before the guards below, all of which `continue` past the
            # rest of the loop for non-project lines.
            if 'ft_trainee_id' not in vals:
                vals['ft_trainee_id'] = self._ft_vals_trainee_employee(vals).id
            # Runs before the billable-project guard below: a completed task
            # takes no more time whether or not its project is billable.
            if vals.get('task_id'):
                self._ft_check_task_not_completed(
                    self.env['project.task'].browse(vals['task_id']))
            project_id = vals.get('project_id')
            if not project_id:
                continue
            project = self.env['project.project'].browse(project_id)
            # Before the billable check below: a task is required on every
            # project line, whether or not the project is invoiced.
            self._ft_check_task_required(project, vals.get('task_id'))
            if not self._is_billable_project(project):
                continue
            if not (vals.get('name') or '').strip():
                raise UserError(_('Description is required. Please enter a description for the timesheet entry.'))
            unit_amount = vals.get('unit_amount') or 0.0
            if unit_amount <= 0:
                raise UserError(_('Time Spent is required. Please enter the hours spent for the timesheet entry.'))
            self._check_single_entry_hours(unit_amount)
            task_id = vals.get('task_id')
            if task_id:
                task = self.env['project.task'].browse(task_id)
                employee_id = vals.get('employee_id')
                employee = (
                    self.env['hr.employee'].browse(employee_id)
                    if employee_id else self.env.user.employee_id
                )
                bucket = self._ft_line_bucket(employee)
                if bucket:
                    existing = self._ft_existing_bucket_hours(task, bucket)
                    self._check_department_time_limit(task, bucket, existing + unit_amount)
        return super().create(vals_list)

    def write(self, vals):
        for line in self:
            # Editing the hours on a completed task, or moving a line onto one,
            # would get round the create-time guard.
            if 'unit_amount' in vals or 'task_id' in vals:
                self._ft_check_task_not_completed(
                    self.env['project.task'].browse(vals['task_id'])
                    if 'task_id' in vals else line.task_id)
            project = (
                self.env['project.project'].browse(vals['project_id'])
                if 'project_id' in vals
                else line.project_id
            )
            # Only when the link itself is being changed. Checking on every
            # write would make the 1,356 pre-existing task-less lines
            # uneditable, including just correcting their description.
            if 'task_id' in vals or 'project_id' in vals:
                self._ft_check_task_required(
                    project,
                    vals['task_id'] if 'task_id' in vals else line.task_id.id)
            if not self._is_billable_project(project):
                continue
            # Validate description only when it is being explicitly changed
            if 'name' in vals and not (vals.get('name') or '').strip():
                raise UserError(_('Description is required. Please enter a description for the timesheet entry.'))
            # Validate time only when it is being explicitly changed
            if 'unit_amount' in vals:
                unit_amount = vals.get('unit_amount') or 0.0
                if unit_amount <= 0:
                    raise UserError(_('Time Spent is required. Please enter the hours spent for the timesheet entry.'))
                self._check_single_entry_hours(unit_amount)
            # Re-check the department bucket limit when hours, task or employee change
            if 'unit_amount' in vals or 'task_id' in vals or 'employee_id' in vals:
                unit_amount = vals.get('unit_amount', line.unit_amount) or 0.0
                task = self.env['project.task'].browse(vals['task_id']) if 'task_id' in vals else line.task_id
                employee = (
                    self.env['hr.employee'].browse(vals['employee_id'])
                    if 'employee_id' in vals else line.employee_id
                )
                bucket = self._ft_line_bucket(employee)
                if task and bucket:
                    existing = self._ft_existing_bucket_hours(task, bucket, exclude_line=line)
                    self._check_department_time_limit(task, bucket, existing + unit_amount)
        return super().write(vals)
