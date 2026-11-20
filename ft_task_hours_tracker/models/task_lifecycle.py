from odoo import api, fields, models
from odoo.addons.bt_project_customization.models.project_task import DEVELOPER_JOB_NAMES


def lifecycle_values(old, new, now, first_completed=False, first_development=False):
    """Audit actual stage entries only; first timestamps never move."""
    old, new = (old or '').strip().lower(), (new or '').strip().lower()
    if old == new:
        return {}
    values = {}
    if new == 'working':
        values['ft_working_start'] = now
        if old and old != 'planned':
            values['ft_last_reopen_date'] = now
    if new == 'testing':
        values['ft_testing_start'] = now
    if new == 'completed':
        values['ft_last_completed_date'] = now
        if not first_completed:
            values['ft_first_completed_date'] = now
    if old == 'working' and not first_development:
        values['ft_first_development_complete'] = now
    return values


class ProjectTaskLifecycle(models.Model):
    _inherit = 'project.task'

    ft_working_start = fields.Datetime('Working Start', readonly=True, copy=False, tracking=True)
    ft_testing_start = fields.Datetime('Testing Start', readonly=True, copy=False, tracking=True)
    ft_first_completed_date = fields.Datetime('First Completed Date', readonly=True, copy=False, tracking=True)
    ft_last_completed_date = fields.Datetime('Last Completed Date', readonly=True, copy=False, tracking=True)
    ft_first_development_complete = fields.Datetime('First Development Complete', readonly=True, copy=False, tracking=True)
    ft_last_reopen_date = fields.Datetime('Re-Open Date', readonly=True, copy=False, tracking=True)
    ft_bug_fix_hours = fields.Float(
        'Bug Fix Hours', compute='_compute_ft_bug_fix_hours', readonly=True,
        help='Development-role or Software Development department time entries created after '
             'First Development Complete. Entries dated before that day are excluded.')

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        now = fields.Datetime.now()
        for task in tasks:
            values = lifecycle_values(None, task.stage_id.name, now)
            if values:
                super(ProjectTaskLifecycle, task.sudo()).write(values)
        return tasks

    def write(self, vals):
        before = {t.id: t.stage_id.name for t in self} if 'stage_id' in vals else {}
        result = super().write(vals)
        if before:
            now = fields.Datetime.now()
            for task in self:
                values = lifecycle_values(
                    before[task.id], task.stage_id.name, now,
                    task.ft_first_completed_date, task.ft_first_development_complete)
                if values:
                    super(ProjectTaskLifecycle, task.sudo()).write(values)
        return result

    @api.depends('ft_first_development_complete', 'timesheet_ids.unit_amount',
                 'timesheet_ids.create_date', 'timesheet_ids.date',
                 'timesheet_ids.employee_id.job_id.name',
                 'timesheet_ids.employee_id.department_id.name')
    def _compute_ft_bug_fix_hours(self):
        for task in self:
            cutoff = task.ft_first_development_complete
            total = 0.0
            if cutoff:
                for line in task.timesheet_ids:
                    employee = line.employee_id.sudo()
                    job = (employee.job_id.name or '').strip().lower()
                    department = (employee.department_id.name or '').strip().lower()
                    eligible = job in DEVELOPER_JOB_NAMES or department == 'software development'
                    cutoff_day = fields.Datetime.context_timestamp(
                        task.with_context(tz=task.company_id.partner_id.tz or 'UTC'), cutoff).date()
                    if (eligible and line.create_date and line.create_date > cutoff
                            and line.date and line.date >= cutoff_day):
                        total += line.unit_amount
            task.ft_bug_fix_hours = total
