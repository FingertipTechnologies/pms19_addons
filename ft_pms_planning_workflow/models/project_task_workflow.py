# -*- coding: utf-8 -*-
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from odoo.addons.bt_project_customization.models.project_task import (
    PROJECT_COORDINATOR_JOB_NAMES,
    TESTER_JOB_NAMES,
)

PWF_TESTING_JOB_NAMES = set(TESTER_JOB_NAMES) | set(PROJECT_COORDINATOR_JOB_NAMES)

# PT-10: a Testing task is at most one week of work.
PWF_TESTING_MAX_HOURS = 40.0

# Context key under which the single-week checks of a Testing task are
# deferred while ft_sprint_management re-syncs the Week from the deadline
# (that happens AFTER the ORM validated the constraints of the inner
# create/write). The value is a per-process random token, so a client cannot
# switch the checks off by putting the key into an RPC context.
_PWF_DEFER_WEEK_KEY = 'pwf_defer_testing_week_check'
_PWF_DEFER_WEEK_TOKEN = secrets.token_hex(16)
_PWF_WEEK_FIELDS = {'task_type', 'sprint_id', 'date_deadline', 'project_id'}


def pwf_testing_hours_exceeded(total):
    return float_compare(total, PWF_TESTING_MAX_HOURS, precision_digits=2) > 0


class ProjectTask(models.Model):
    _inherit = 'project.task'

    task_type = fields.Selection(
        selection_add=[('testing', 'Testing')],
        ondelete={'testing': 'set default'},
    )

    # ------------------------------------------------------------------
    # Testing task: assignees must be QA or Project Coordinator
    # ------------------------------------------------------------------
    @api.model
    def _pwf_testing_allowed_users(self, users):
        """Subset of ``users`` allowed on a Testing task.

        Decided from the users' own job / group data, never from the current
        user, so it is correct when the constraint runs as superuser.
        """
        if not users:
            return users
        employees = self.env['hr.employee'].sudo().search([('user_id', 'in', users.ids)])
        by_job = {
            emp.user_id.id for emp in employees
            if (emp.job_id.name or '').strip().lower() in PWF_TESTING_JOB_NAMES
        }
        qa_group = self.env.ref('bt_project_customization.group_qa_group',
                                raise_if_not_found=False)
        in_group = set(qa_group.sudo().all_user_ids.ids) if qa_group else set()
        return users.filtered(lambda u: u.id in by_job or u.id in in_group)

    @api.constrains('task_type', 'user_ids')
    def _check_pwf_testing_assignees(self):
        for task in self.filtered(lambda t: t.task_type == 'testing'):
            not_allowed = task.user_ids - self._pwf_testing_allowed_users(task.user_ids)
            if not_allowed:
                raise ValidationError(_(
                    "A Testing task can be assigned only to QA (Software Tester, "
                    "Junior Software Tester, Testing Lead) or a Project "
                    "Coordinator.\n\nTask: %(task)s\nNot allowed: %(users)s",
                    task=task.name or '',
                    users=', '.join(not_allowed.mapped('name')),
                ))

    # ------------------------------------------------------------------
    # PT-10 Testing task: <= 40 h estimated / logged, single week
    # ------------------------------------------------------------------
    def _pwf_week_check_deferred(self):
        return self.env.context.get(_PWF_DEFER_WEEK_KEY) == _PWF_DEFER_WEEK_TOKEN

    def _pwf_testing_logged_hours(self):
        """{task_id: summed timesheet hours} for these tasks (sudo, from DB)."""
        if not self.ids:
            return {}
        groups = self.env['account.analytic.line'].sudo()._read_group(
            [('task_id', 'in', self.ids)], ['task_id'], ['unit_amount:sum'])
        return {task.id: total or 0.0 for task, total in groups}

    @api.constrains('task_type', 'estimated')
    def _check_pwf_testing_hours(self):
        testing = self.filtered(lambda t: t.task_type == 'testing')
        if not testing:
            return
        for task in testing:
            if pwf_testing_hours_exceeded(task.estimated or 0.0):
                raise ValidationError(_(
                    "A Testing task can be estimated at most %(cap)s hours.\n\n"
                    "Task: %(task)s\nEstimated: %(est)s h",
                    cap=PWF_TESTING_MAX_HOURS, task=task.name or '',
                    est=round(task.estimated, 2)))
        logged = testing._pwf_testing_logged_hours()
        for task in testing:
            total = logged.get(task.id, 0.0)
            if pwf_testing_hours_exceeded(total):
                raise ValidationError(_(
                    "A Testing task can have at most %(cap)s hours of "
                    "timesheets.\n\nTask: %(task)s\nLogged: %(total)s h",
                    cap=PWF_TESTING_MAX_HOURS, task=task.name or '',
                    total=round(total, 2)))

    @api.constrains('task_type', 'sprint_id', 'date_deadline', 'project_id')
    def _check_pwf_testing_week(self):
        if self._pwf_week_check_deferred():
            # Re-run by create()/write() below once the Week is synced.
            return
        self._pwf_check_testing_week()

    def _pwf_check_testing_week(self):
        """A Testing task lives in exactly one Week (Mon-Sun).

        Once it has a deadline or timesheets it must have a Week, and the
        local deadline must fall inside that Week. Timesheet dates are not
        restricted to the Week.
        Tasks without a project are left alone: ft_sprint_management never
        assigns them a Week.
        """
        testing = self.sudo().filtered(
            lambda t: t.task_type == 'testing' and t.project_id)
        if not testing:
            return
        Line = self.env['account.analytic.line'].sudo()
        with_lines = {
            task.id for (task,) in Line._read_group(
                [('task_id', 'in', testing.ids)], ['task_id'])}
        for task in testing:
            week = task.sprint_id
            if not week:
                if task.date_deadline or task.id in with_lines:
                    raise ValidationError(_(
                        "A Testing task with a deadline or timesheets must be "
                        "planned in a Week.\n\nTask: %(task)s",
                        task=task.name or ''))
                continue
            start, end = week.start_date, week.end_date
            if task.date_deadline:
                day = task._ft_local_date(task.date_deadline)
                if not (start <= day <= end):
                    raise ValidationError(_(
                        "A Testing task must be due within its Week.\n\n"
                        "Task: %(task)s\nWeek: %(week)s (%(start)s - %(end)s)\n"
                        "Deadline: %(day)s",
                        task=task.name or '', week=week.display_name,
                        start=start, end=end, day=day))

    # ------------------------------------------------------------------
    # Locked projects accept no new tasks
    # ------------------------------------------------------------------
    def _pwf_raise_if_locked(self, project_ids):
        project_ids = {pid for pid in project_ids if pid}
        if not project_ids:
            return
        locked = self.env['project.project'].sudo().browse(project_ids).exists() \
            .filtered('pwf_locked')
        if locked:
            raise UserError(_(
                "Project '%s' is locked: no new tasks can be added. Ask an "
                "Administrator to unlock it.",
                ', '.join(locked.mapped('display_name'))))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            default_project = self.env.context.get('default_project_id')
            project_ids = set()
            parent_ids = set()
            for vals in vals_list:
                project_ids.add(vals.get('project_id') or (
                    default_project if 'project_id' not in vals else False))
                if not vals.get('project_id') and vals.get('parent_id'):
                    parent_ids.add(vals['parent_id'])
            if parent_ids:
                project_ids |= set(self.sudo().browse(parent_ids).project_id.ids)
            self._pwf_raise_if_locked(project_ids)
        if self._pwf_week_check_deferred():
            return super().create(vals_list)
        # ft_sprint_management assigns the Week from the deadline only after
        # the ORM create (and its constraints) ran: check the Week afterwards.
        tasks = super(ProjectTask, self.with_context(
            **{_PWF_DEFER_WEEK_KEY: _PWF_DEFER_WEEK_TOKEN})).create(vals_list)
        tasks = tasks.with_env(self.env)
        tasks._pwf_check_testing_week()
        return tasks

    def write(self, vals):
        if not self.env.su and vals.get('project_id'):
            moving = self.filtered(lambda t: t.project_id.id != vals['project_id'])
            if moving:
                self._pwf_raise_if_locked({vals['project_id']})
        if self._pwf_week_check_deferred() or not (_PWF_WEEK_FIELDS & set(vals)):
            return super().write(vals)
        # Same as create(): a new deadline re-syncs the Week after the ORM
        # write, so the single-week rule is checked once both are settled.
        res = super(ProjectTask, self.with_context(
            **{_PWF_DEFER_WEEK_KEY: _PWF_DEFER_WEEK_TOKEN})).write(vals)
        self._pwf_check_testing_week()
        return res
