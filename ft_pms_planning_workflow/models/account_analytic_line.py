# -*- coding: utf-8 -*-
from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

from .project_task_workflow import (
    PWF_TESTING_MAX_HOURS,
    pwf_testing_hours_exceeded,
)


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    def _pwf_projects_from_vals(self, vals):
        """Projects a create/write ``vals`` points the line(s) at."""
        Project = self.env['project.project'].sudo()
        if vals.get('project_id'):
            return Project.browse(vals['project_id'])
        if vals.get('task_id'):
            return self.env['project.task'].sudo().browse(vals['task_id']).project_id
        return Project

    def _pwf_raise_if_locked(self, projects):
        locked = projects.sudo().exists().filtered('pwf_locked')
        if locked:
            raise UserError(_(
                "Project '%s' is locked: timesheets cannot be logged or "
                "changed. Ask an Administrator to unlock it.",
                ', '.join(locked.mapped('display_name'))))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            projects = self.env['project.project'].sudo()
            for vals in vals_list:
                projects |= self._pwf_projects_from_vals(vals)
            self._pwf_raise_if_locked(projects)
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            self._pwf_raise_if_locked(
                self.sudo().project_id | self._pwf_projects_from_vals(vals))
        return super().write(vals)

    # ------------------------------------------------------------------
    # PT-10 Testing task: <= 40 h logged
    # ------------------------------------------------------------------
    @api.constrains('task_id', 'unit_amount')
    def _check_pwf_testing_task_timesheets(self):
        tasks = self.sudo().task_id.filtered(lambda t: t.task_type == 'testing')
        if not tasks:
            return
        logged = tasks._pwf_testing_logged_hours()
        for task in tasks:
            total = logged.get(task.id, 0.0)
            if pwf_testing_hours_exceeded(total):
                these = sum(self.sudo().filtered(
                    lambda l, t=task: l.task_id == t).mapped('unit_amount'))
                raise ValidationError(_(
                    "A Testing task can have at most %(cap)s hours of "
                    "timesheets.\n\nTask: %(task)s\nAlready logged: %(other)s h"
                    "\nThis entry: %(these)s h\nTotal would be: %(total)s h",
                    cap=PWF_TESTING_MAX_HOURS, task=task.name or '',
                    other=round(total - these, 2), these=round(these, 2),
                    total=round(total, 2)))
        # A Testing task with timesheets must be planned in a Week.
        tasks._pwf_check_testing_week()
