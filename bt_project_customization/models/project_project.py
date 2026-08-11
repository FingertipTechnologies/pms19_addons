from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

# Job positions (hr.job names, lower-cased) allowed to change the project status.
PM_JOB_NAMES = ('project manager', 'project coordinator', 'project cordinator')


class InheritProjectProject(models.Model):
    _inherit = 'project.project'

    # The project-level counterpart of the task's `estimated` field: the sum of
    # every task's Estimated hours, the way Actual Hours (effective_hours) is the
    # sum of every timesheet. Stored so the project list can sort and group on it.
    # `tasks`, not `task_ids`: core filters task_ids to is_closed = False, which
    # would silently drop the estimate of every finished task.
    estimated = fields.Float(
        string='Estimated Time',
        compute='_compute_estimated',
        store=True,
        readonly=True,
        help='Sum of the Estimated hours of every task in this project, '
             'closed tasks included.',
    )

    architect_id = fields.Many2one('res.users', string='Architect')
    ba_id = fields.Many2one('res.users', string='BA')
    pm_id = fields.Many2one('res.users', string='PM')
    brd_approval_date = fields.Date(string='BRD Approval Date')
    brd_submission_date = fields.Date(string='BRD Submission Date')
    go_live_date = fields.Date(string='Go Live Date')
    # end_date = fields.Date(string='End Date')
    kick_start_meeting_date = fields.Date(string='Kick Start Meeting Date')
    sandbox_review_date = fields.Date(string='Sandbox Review Date')
    # start_date = fields.Date(string='Start Date')
    support_start_date = fields.Date(string='Support Start Date')
    uat_start_date = fields.Date(string='UAT Start Date')
    warranty_end_date = fields.Date(string='Warranty End Date')
    comments = fields.Text(string='Comments')
    development = fields.Text(string='Development')
    payment_terms = fields.Text(string='Payment Terms')
    payment_terms_id = fields.Many2one('account.payment.term',string='Payment Terms')
    user_name = fields.Char(string='User Name')
    password = fields.Char(string='Password')
    poc_email = fields.Char(string='POC Email')
    poc_mobile = fields.Char(string='POC Mobile')
    short_code = fields.Char(string='Short Code', help='Unique, case insensitive')
    hourly_billing_rate = fields.Monetary(string='Hourly Billing Rate', currency_field='currency_id')
    hourly_cost = fields.Monetary(string='Hourly Cost', currency_field='currency_id')
    hours_balance = fields.Float(string='Hours Balance')
    hours_est_pm = fields.Float(string='Hours Est PM')
    hours_est_qa = fields.Float(string='Hours Est QA')
    hours_est_dev = fields.Float(string='Hours Est Dev')
    hours_overflowed = fields.Float(string='Hours Overflowed')
    hours_spent_dev = fields.Float(string='Hours Spent Dev')
    hours_spent_pm = fields.Float(string='Hours Spent PM')
    hours_spent_qa = fields.Float(string='Hours Spent QA')
    stories = fields.Float(string='Stories')
    status = fields.Selection([
        ('discovery', 'Discovery'),
        ('development', 'Development'),
        ('sandbox_review', 'Sandbox Review'),
        ('regression_testing', 'Regression Testing'),
        ('deployment', 'Deployment'),
        ('data_upload', 'Data Upload'),
        ('user_acceptance', 'User Acceptance'),
        ('training', 'Training'),
        ('support', 'Support'),
        ('amc', 'AMC'),
        ('closed', 'Closed'),
        ('hold', 'Hold'),
    ], string='Status')
    sync_wc = fields.Boolean(string='Sync WC')
    wc_id = fields.Char(string='Wc Id')

    timesheet_count = fields.Float(
        string="Timesheet Hours",
        compute='_compute_timesheet_count'
    )

    def _compute_timesheet_count(self):
        for project in self:
            lines = self.env['account.analytic.line'].search([('project_id', '=', project.id)])
            project.timesheet_count = sum(lines.mapped('unit_amount'))

    # ------------------------------------------------------------------
    # On-Time Delivery (all-time; the dashboard shows the same figures per
    # period). The maths lives on project.task so the two can never drift.
    # ------------------------------------------------------------------
    ft_on_time_rate = fields.Float(
        string='On-Time Delivery (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        # Not 'group_operator' — deprecated in Odoo 18. Averaging a ratio across
        # projects would be wrong anyway (a 1-task project would weigh the same
        # as a 500-task one), so no aggregate is offered.
        aggregator=False,
        help="Share of delivered tasks that met their deadline, all-time. "
             "Target: 95% or above. Tasks delivered without a deadline are not "
             "counted either way — see Delivered Without Deadline. Reads 0 when "
             "nothing measurable has been delivered yet.",
    )
    ft_delivered_tasks = fields.Integer(
        string='Delivered Tasks',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Tasks that reached a Completed (folded) stage. Excludes cancelled.",
    )
    ft_on_time_tasks = fields.Integer(
        string='Delivered On Time',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks whose completion date was on or before the deadline.",
    )
    ft_late_tasks = fields.Integer(
        string='Delivered Late',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks whose completion date was after the deadline.",
    )
    ft_no_deadline_tasks = fields.Integer(
        string='Delivered Without Deadline',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks that had no deadline set, so they could not be "
             "judged on time. The On-Time Delivery percentage ignores these; a "
             "large number here means the percentage covers only a small slice "
             "of the work.",
    )
    ft_overdue_open_tasks = fields.Integer(
        string='Open & Overdue',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Tasks still open whose deadline has already passed. Read this "
             "alongside On-Time Delivery: the percentage only counts work that "
             "finished, so late work that never finishes is invisible to it.",
    )

    ft_efficiency_rate = fields.Float(
        string='Delivery Efficiency (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Estimated hours divided by actual hours across delivered tasks, "
             "as a percentage. Target: 90-110%. Below 90% the work is taking "
             "longer than estimated; above 110% the estimates are padded. Only "
             "tasks that have BOTH an estimate and logged time are counted — see "
             "Tasks Without an Estimate.",
    )
    ft_estimated_hours = fields.Float(
        string='Estimated Hours (Delivered)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Allocated hours on delivered tasks that also have logged time. "
             "The numerator of Delivery Efficiency.",
    )
    ft_actual_hours = fields.Float(
        string='Actual Hours (Delivered)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Timesheeted hours on the same tasks. The denominator of Delivery "
             "Efficiency.",
    )
    ft_unestimated_tasks = fields.Integer(
        string='Tasks Without an Estimate',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks left out of Delivery Efficiency because they had "
             "no estimate or no logged time. A large number here means the "
             "percentage covers only a small slice of the work.",
    )
    ft_rework_rate = fields.Float(
        string='Rework Rate (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Share of delivered tasks that were reopened at least once. "
             "Target: 10% or below. Counts tasks, not reopen events, so one task "
             "bounced repeatedly cannot push the rate past 100%. Only reopens "
             "since this feature was installed are counted.",
    )
    ft_reworked_tasks = fields.Integer(
        string='Reworked Tasks',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Delivered tasks that were moved back out of a Completed stage at "
             "least once.",
    )
    ft_rework_hours = fields.Float(
        string='Rework Hours',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        help="Time logged on delivered tasks after they were moved back out of "
             "a completed stage — the cost of redoing work that had already "
             "been called finished.",
    )
    ft_rework_hours_rate = fields.Float(
        string='Rework Hours (%)',
        compute='_compute_ft_delivery_stats',
        store=False,
        readonly=True,
        aggregator=False,
        help="Share of the effort on delivered tasks that went into rework. "
             "Answers a different question from Rework Rate beside it: that one "
             "counts how OFTEN work comes back, this one how much it COSTS. One "
             "task reopened once can be 2% of the count and half the hours.",
    )

    @api.depends('tasks.estimated')
    def _compute_estimated(self):
        for project in self:
            project.estimated = round(sum(project.tasks.mapped('estimated')), 2)

    # stage_id.name joins the depends for the same reason it is in
    # _compute_ft_completion_date's: whether a stage counts as delivered now
    # turns on its name as well as its fold flag.
    @api.depends('task_ids.ft_completion_date', 'task_ids.date_deadline',
                 'task_ids.stage_id.fold', 'task_ids.stage_id.name',
                 'task_ids.state',
                 'task_ids.estimated', 'task_ids.effective_hours',
                 'task_ids.ft_reopen_count', 'task_ids.ft_rework_hours')
    def _compute_ft_delivery_stats(self):
        Task = self.env['project.task']
        # Two queries for the whole set rather than two per project — this
        # compute runs for every row of the project list view.
        stats_by_project = Task._ft_on_time_stats_by_project(self.ids)
        overdue_by_project = Task._ft_overdue_open_count_by_project(self.ids)
        for project in self:
            stats = stats_by_project.get(project.id) or {}
            project.ft_delivered_tasks = stats.get('completed', 0)
            project.ft_on_time_tasks = stats.get('on_time', 0)
            project.ft_late_tasks = stats.get('late', 0)
            project.ft_no_deadline_tasks = stats.get('no_deadline', 0)
            # A Float cannot hold "no data", so an unmeasurable project reads 0.
            # ft_delivered_tasks / ft_no_deadline_tasks are what tell them apart.
            project.ft_on_time_rate = stats.get('rate') or 0.0
            project.ft_overdue_open_tasks = overdue_by_project.get(project.id, 0)
            # Same "a Float cannot hold no-data" caveat as the on-time rate:
            # ft_unestimated_tasks / ft_delivered_tasks tell 0% apart from
            # nothing-to-measure.
            project.ft_efficiency_rate = stats.get('efficiency_rate') or 0.0
            project.ft_estimated_hours = stats.get('estimated_hours', 0.0)
            project.ft_actual_hours = stats.get('actual_hours', 0.0)
            project.ft_unestimated_tasks = stats.get('unestimated', 0)
            project.ft_rework_rate = stats.get('rework_rate') or 0.0
            project.ft_reworked_tasks = stats.get('reworked', 0)
            project.ft_rework_hours = stats.get('rework_hours', 0.0)
            project.ft_rework_hours_rate = stats.get('rework_hours_rate') or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        # #3 - Only Administrators may create projects.
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise UserError(_("Only an Administrator can create projects."))
        return super().create(vals_list)

    def write(self, vals):
        # #4 - Only a Project Manager (by job position) or an Administrator
        # may change the project status/stage (the status bar = stage_id).
        if ('status' in vals or 'stage_id' in vals) and not self.env.su:
            user = self.env.user
            job = (user.employee_id.job_id.name or '').strip().lower() if user.employee_id else ''
            if job not in PM_JOB_NAMES and not user.has_group('base.group_system'):
                raise UserError(_("Only a Project Manager can change the project status."))
        if 'timesheet_ids' in vals:
            deduped = []
            for cmd in vals['timesheet_ids']:
                # cmd[0] == 0 means "create new record via O2M"
                if cmd[0] == 0:
                    cv = cmd[2] or {}
                    task_id = cv.get('task_id')
                    # Only deduplicate when the record came from a task save
                    # (task timesheets always carry a task_id)
                    if task_id:
                        domain = [
                            ('task_id', '=', task_id),
                            ('project_id', 'in', self.ids),
                        ]
                        # Add optional fields only when present in the command
                        # vals to avoid False-vs-'' mismatches causing missed hits
                        if cv.get('date'):
                            domain.append(('date', '=', cv['date']))
                        if cv.get('employee_id'):
                            domain.append(('employee_id', '=', cv['employee_id']))
                        if cv.get('unit_amount') is not None:
                            domain.append(('unit_amount', '=', cv['unit_amount']))
                        existing = self.env['account.analytic.line'].search(
                            domain, limit=1
                        )
                        if existing:
                            # Replace create with a plain link to the existing record
                            deduped.append((4, existing.id, 0))
                            continue
                deduped.append(cmd)
            vals['timesheet_ids'] = deduped
        return super().write(vals)

    def action_view_timesheets(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('hr_timesheet.timesheet_action_all')
        action['domain'] = [('project_id', '=', self.id)]
        action['context'] = {
            'default_project_id': self.id,
            'search_default_project_id': self.id,
            'group_by': [ 'jobposition_id', 'employee_id','task_id'],
        }
        return action


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    jobposition_id = fields.Many2one(
        'hr.job',
        string="Job Position",
        readonly=False,
    )
    module_id = fields.Many2one('cus.module',related='task_id.module_id',string='Module')
    project_status = fields.Many2one(
        'project.project.stage',
        string='Project Status', store=True, readonly=True,
        help='Snapshot of the project stage at the time the timesheet was created. '
             'Frozen after creation and only updates if the project itself is changed.',
    )

    @api.model_create_multi
    def create(self, vals_list):
        result_ids = []
        to_create = []
        for vals in vals_list:
            task_id = vals.get('task_id')
            project_id = vals.get('project_id')
            # When both task_id and project_id are present, the project form's
            # O2M widget can re-submit a task timesheet as a create command even
            # though the record already exists in the DB.  Detect and skip it.
            if task_id and project_id:
                domain = [
                    ('task_id', '=', task_id),
                    ('project_id', '=', project_id),
                ]
                if vals.get('date'):
                    domain.append(('date', '=', vals['date']))
                if vals.get('employee_id'):
                    domain.append(('employee_id', '=', vals['employee_id']))
                if vals.get('unit_amount') is not None:
                    domain.append(('unit_amount', '=', vals['unit_amount']))
                existing = self.search(domain, limit=1)
                if existing:
                    result_ids.append(existing.id)
                    continue
            if project_id and not vals.get('project_status'):
                project = self.env['project.project'].browse(project_id)
                if project.stage_id:
                    vals['project_status'] = project.stage_id.id
            to_create.append(vals)
        created = super().create(to_create) if to_create else self.browse()
        return self.browse(result_ids) | created

    def write(self, vals):
        # Only refresh project_status snapshot when the project itself changes
        if 'project_id' in vals:
            project = self.env['project.project'].browse(vals['project_id']) if vals['project_id'] else False
            vals['project_status'] = project.stage_id.id if project and project.stage_id else False
        return super().write(vals)

    @api.constrains('project_id', 'unit_amount')
    def _check_project_status_open(self):
        # #1 - No time entries when the project is Closed or On Hold. The PMS
        # tracks this via the project STAGE (stage_id, the status bar) and also
        # the custom `status` selection, so block on either.
        blocked_stage_names = ('closed', 'hold', 'on hold')
        for line in self:
            project = line.project_id
            if not project:
                continue
            stage_name = (project.stage_id.name or '').strip().lower()
            status_blocked = project.status in ('closed', 'hold')
            if stage_name in blocked_stage_names or status_blocked:
                label = project.stage_id.name if stage_name in blocked_stage_names \
                    else dict(project._fields['status'].selection).get(project.status, project.status)
                raise ValidationError(_(
                    "You cannot log time on project '%s' because it is %s."
                ) % (project.name, label))
    used_ai = fields.Boolean(string='Used AI')
    chat_link = fields.Char(string='Chat Link')
    reason = fields.Char(string='Reason')
    hours_saved = fields.Float(string='Hours Saved')
    challenges = fields.Text(string='Challenges')
    ai_time_impact = fields.Selection([
        ('0', '0'),
        ('15_mins', '15 mins'),
        ('30_mins', '30 mins'),
        ('1_hour', '1 hour'),
        ('2_hours', '2 hours'),
        ('3_hours', '3 hours'),
        ('5_hours', '5 hours'),
        ('8_plus_hours', '8+ hours'),
        ('more_time', 'More time taken'),
        ('na', 'N/A'),
    ], string='AI Time Impact')


    # @api.depends('employee_id.job_id')
    # def _compute_jobposition_id(self):
    #     """
    #     Compute: Sync from Employee -> Timesheet
    #     When the employee's job_id changes, update the timesheet jobposition_id.
    #     """
    #     for line in self:
    #         if line.employee_id and line._get_job_update_needed():
    #             line.jobposition_id = line.employee_id.job_id
    #         else:
    #             # Clear if no employee
    #             line.jobposition_id = False
    #
    # def _inverse_jobposition_id(self):
    #     """
    #     Inverse: Sync from Timesheet -> Employee
    #     When jobposition_id changes on the timesheet, update the employee's job_id.
    #     """
    #     for line in self:
    #         if line.employee_id and line._get_job_update_needed():
    #             line.employee_id.job_id = line.jobposition_id or False
    #
    # def _get_job_update_needed(self):
    #     """
    #     Helper method to check whether the timesheet job position
    #     and the employee's job position are different.
    #     This prevents infinite loops and unnecessary writes.
    #     """
    #     self.ensure_one()
    #     return self.employee_id and self.jobposition_id != self.employee_id.job_id

