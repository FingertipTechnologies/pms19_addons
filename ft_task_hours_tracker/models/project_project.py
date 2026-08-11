from odoo import models, fields, api


class ProjectProject(models.Model):
    _inherit = 'project.project'

    ft_has_exceeded_tasks = fields.Boolean(
        string='Has Tasks Exceeding Time Limit',
        compute='_compute_ft_has_exceeded_tasks',
        store=True,
        help='True when at least one task in this project exceeds the global time limit.',
    )
    # store=True is retained from the v19 branch; the v18 source uses store=False.
    ft_dev_hours = fields.Float(
        string='Dev Hours',
        compute='_compute_ft_job_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Software Developer / Technical Lead employees.',
    )
    ft_qa_hours = fields.Float(
        string='QA Hours',
        compute='_compute_ft_job_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Software Tester / Testing Lead employees.',
    )
    ft_pm_hours = fields.Float(
        string='PM Hours',
        compute='_compute_ft_job_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Project Manager / Project Coordinator employees.',
    )
    ft_ba_hours = fields.Float(
        string='BA Hours',
        compute='_compute_ft_job_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by Business Analyst employees.',
    )
    ft_trainee_hours = fields.Float(
        string='Trainee Hours',
        compute='_compute_ft_job_hours',
        store=True,
        readonly=True,
        help='Total hours logged on this project by any Trainee job position.',
    )

    @api.depends('task_ids.ft_hours_exceeded')
    def _compute_ft_has_exceeded_tasks(self):
        for project in self:
            project.ft_has_exceeded_tasks = any(project.task_ids.mapped('ft_hours_exceeded'))

    @api.depends('timesheet_ids.unit_amount', 'timesheet_ids.employee_id.job_id')
    def _compute_ft_job_hours(self):
        # Aggregate the project's timesheets into Dev / QA / PM / BA / Trainee
        # buckets, classified by the EMPLOYEE's current job position so old
        # hours map correctly and recompute when the job position changes.
        # Unlike tasks, the per-bucket time limit is NOT applied at project level.
        ProjectTask = self.env['project.task']
        for project in self:
            totals = dict.fromkeys(('dev', 'qa', 'pm', 'ba', 'trainee'), 0.0)
            for line in project.timesheet_ids:
                bucket = ProjectTask._ft_job_bucket(line.employee_id.job_id)
                if bucket:
                    totals[bucket] += line.unit_amount
            project.ft_dev_hours = totals['dev']
            project.ft_qa_hours = totals['qa']
            project.ft_pm_hours = totals['pm']
            project.ft_ba_hours = totals['ba']
            project.ft_trainee_hours = totals['trainee']
