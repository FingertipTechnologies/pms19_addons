from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .competency_utils import MAX_RATING, hr_emails, join_emails, send_competency_mail

# How many days ahead of its due date an open development action is chased.
DEVELOPMENT_REMINDER_DAYS = 3


class EmployeeDevelopmentPlan(models.Model):
    """What is being done about one competency gap.

    A plan is raised against an assessment line — the gap — and carries an
    owner, a date and progress, so the quarter between two reviews has
    something in it besides waiting for the next review.
    """

    _name = 'employee.development.plan'
    _description = 'Employee Development Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'target_date, id'

    name = fields.Char(string='Action', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, ondelete='restrict', index=True, tracking=True,
    )
    employee_user_id = fields.Many2one(
        related='employee_id.user_id', store=True, index=True,
        string='Employee User',
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, index=True,
        string='Department',
    )
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Assessment',
        ondelete='set null', index=True,
    )
    job_id = fields.Many2one(
        related='assessment_id.job_id',
        string='Job Position',
        store=True,
        readonly=True,
    )

    cycle_id = fields.Many2one(
        related='assessment_id.cycle_id',
        string='Review Cycle',
        store=True,
        readonly=True,
        index=True,
    )
    assessment_line_id = fields.Many2one(
        'employee.competency.assessment.line', string='Competency Gap',
        ondelete='set null', index=True,
        help='The assessed competency this plan answers.',
    )
    profile_id = fields.Many2one(
        'employee.competency.profile', string='Competency Profile',
        compute='_compute_profile_id', store=True, ondelete='set null',
        help='Technical: links the plan to the employee\'s standing profile '
             'entry so the Competency tab can show it.',
    )
    competency_id = fields.Many2one(
        'employee.competency', string='Competency',
        compute='_compute_competency_id', store=True, readonly=False,
        required=True, precompute=True, ondelete='restrict', index=True,
    )
    category_id = fields.Many2one(
        related='competency_id.category_id', store=True, string='Category',
    )
    action_type = fields.Selection(
        selection=[
            ('training', 'Training'),
            ('mentoring', 'Mentoring'),
            ('project', 'Project / On-the-job'),
            ('certification', 'Certification'),
            ('exposure', 'Exposure'),
            ('self_learning', 'Self Learning'),
        ],
        string='Action Type', default='training', required=True, tracking=True,
    )
    action_plan = fields.Text(
        string='Description',
        help='The detailed action and its expected outcome.',
    )
    assigned_person_id = fields.Many2one(
        'res.users', string='Owner',
        required=True, default=lambda self: self.env.user, tracking=True, domain=[('share', '=', False)],
        help='Who is accountable for the action happening — usually the '
             'manager or a mentor, not the employee.',
    )
    date_start = fields.Date(string='Start Date')
    target_date = fields.Date(string='Due Date', required=True, tracking=True)
    target_level = fields.Integer(
        string='Target Level', default=0,
        help='The level the employee should reach once the action is done.',
    )
    state = fields.Selection(
        selection=[
            ('planned', 'Not Started'),
            ('in_progress', 'In Progress'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
        ],
        default='planned', required=True, tracking=True, copy=False,
    )
    completion_percentage = fields.Float(
        string='Completion %', digits=(5, 2), default=0.0, tracking=True,
    )
    remarks = fields.Text()
    result = fields.Text(
        string='Result / Outcome',
        help='What actually changed, recorded when the action closes.',
    )
    is_overdue = fields.Boolean(
        compute='_compute_is_overdue', search='_search_is_overdue',
        string='Overdue',
    )
    target_level_id = fields.Many2one(
        'employee.competency.level', string='Target Level Record',
        compute='_compute_target_level_id', inverse='_inverse_target_level_id',
        store=True, ondelete='restrict',
    )
    goal_id = fields.Many2one(
        'employee.appraisal.goal', string='Goal', ondelete='set null', index=True,
        domain=(
            "[('employee_id', '=', employee_id), "
            "('state', 'in', ['draft', 'in_progress'])]"
        ),
        help='The appraisal goal this action serves, when there is one.',
    )

    # Specification names (hr.employee.development.action).
    appraisal_id = fields.Many2one(related='assessment_id', readonly=False, string='Appraisal (spec)')
    competency_line_id = fields.Many2one(
        related='assessment_line_id', readonly=False, string='Competency Line (spec)',
    )
    skill_id = fields.Many2one(related='competency_id', readonly=False, string='Competency (spec)')
    description = fields.Text(related='action_plan', readonly=False, string='Description (spec)')
    owner_id = fields.Many2one(related='assigned_person_id', readonly=False, string='Owner (spec)')
    due_date = fields.Date(related='target_date', readonly=False, string='Due Date (spec)')

    _completion_range = models.Constraint(
        'CHECK(completion_percentage BETWEEN 0 AND 100)',
        'Completion must be between 0 and 100%.',
    )
    _target_level_range = models.Constraint(
        f'CHECK(target_level BETWEEN 0 AND {MAX_RATING})',
        f'A target level must be between 1 and {MAX_RATING}.',
    )
    @api.constrains('employee_id', 'assessment_id', 'assessment_line_id')
    def _check_assessment_mapping(self):
        for plan in self:
            if (
                plan.assessment_id
                and plan.assessment_id.employee_id != plan.employee_id
            ):
                raise ValidationError(self.env._(
                    'The selected assessment must belong to this employee.'
                ))

            if (
                plan.assessment_line_id
                and plan.assessment_line_id.assessment_id != plan.assessment_id
            ):
                raise ValidationError(self.env._(
                    'The selected competency line must belong to '
                    'the selected assessment.'
                ))

    @api.model
    def _check_entered_dates(self, vals):
        today = fields.Date.context_today(self)

        for field_name, label in (
            ('date_start', 'Start Date'),
            ('target_date', 'Due Date'),
            ('due_date', 'Due Date'),
        ):
            if vals.get(field_name):
                value = fields.Date.to_date(vals[field_name])
                if value < today:
                    raise ValidationError(self.env._(
                        '%(label)s cannot be in the past.',
                        label=label,
                    ))

    @api.depends('target_level')
    def _compute_target_level_id(self):
        levels = self.env['employee.competency.level']._by_rating()
        empty = self.env['employee.competency.level']
        for plan in self:
            plan.target_level_id = levels.get(plan.target_level, empty)

    def _inverse_target_level_id(self):
        for plan in self:
            plan.target_level = plan.target_level_id.rating or 0

    @api.depends('assessment_line_id')
    def _compute_competency_id(self):
        for plan in self:
            if plan.assessment_line_id:
                plan.competency_id = plan.assessment_line_id.competency_id
            elif not plan.competency_id:
                plan.competency_id = False

    @api.depends('employee_id', 'competency_id')
    def _compute_profile_id(self):
        for plan in self:
            if not plan.employee_id or not plan.competency_id:
                plan.profile_id = False
                continue
            plan.profile_id = self.env['employee.competency.profile'].search(
                [
                    ('employee_id', '=', plan.employee_id.id),
                    ('competency_id', '=', plan.competency_id.id),
                ],
                limit=1,
            )

    @api.depends('target_date', 'state')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for plan in self:
            plan.is_overdue = bool(
                plan.target_date
                and plan.target_date < today
                and plan.state in ('planned', 'in_progress')
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError
        overdue = [
            ('target_date', '<', fields.Date.context_today(self)),
            ('state', 'in', ('planned', 'in_progress')),
        ]
        wants_overdue = (operator == '=') == bool(value)
        # '!' negates the ONE term after it, so the '&' joining the two leaves
        # has to sit inside the negation or only the date clause gets flipped.
        return overdue if wants_overdue else ['!', '&', *overdue]

    @api.constrains('assigned_person_id')
    def _check_internal_owner(self):
        for plan in self:
            if (
                plan.assigned_person_id
                and plan.assigned_person_id.sudo().share
            ):
                raise ValidationError(
                    "The Development Plan Owner must be an "
                    "internal user. Portal and public users "
                    "cannot be selected."
                )

    @api.constrains('date_start', 'target_date')
    def _check_dates(self):
        for plan in self:
            if (
                plan.date_start
                and plan.target_date
                and plan.target_date <= plan.date_start
            ):
                raise ValidationError(
                    "The Due Date must be later than the Start Date. "
                    "Both dates cannot be the same."
                )

    @api.constrains('state', 'completion_percentage')
    def _check_completion(self):
        # BR-022: a completed action that reads 40% done tells nobody anything.
        for plan in self:
            if plan.state == 'completed' and plan.completion_percentage < 100.0:
                raise ValidationError(self.env._(
                    '%(plan)s is marked Completed, so its completion must be '
                    '100%%. It currently reads %(percent).2f%%.',
                    plan=plan.name, percent=plan.completion_percentage,
                ))

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_complete(self):
        self.write({'state': 'completed', 'completion_percentage': 100.0})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_to_planned(self):
        self.write({'state': 'planned'})

    # ------------------------------------------------------------------
    # Emails - all from the support mailbox
    # ------------------------------------------------------------------
    def _manager_email(self):
        """The employee's manager: the reviewer of the assessment that raised
        the action, else the employee's own manager."""
        self.ensure_one()
        plan = self.sudo()
        manager = plan.assessment_id.reviewer_id or plan.employee_id.parent_id
        return manager.work_email

    def _check_selectable_goal(self):
        for plan in self:
            if (
                plan.goal_id
                and plan.goal_id.state
                not in ('draft', 'in_progress')
            ):
                raise ValidationError(
                    "Select a Draft or In Progress goal. "
                    "Achieved or Cancelled goals cannot be "
                    "assigned to a development plan."
                )

    @api.model_create_multi
    def create(self, vals_list):
        plans = super().create(vals_list)
        plans._check_selectable_goal()
        for plan in plans:
            if not plan.assessment_id:
                raise ValidationError(self.env._(
                    'Select an assessment to map this development plan '
                    'to a review cycle.'
                ))

            plan._check_entered_dates({
                'date_start': plan.date_start,
                'target_date': plan.target_date,
            })
        # Mail 10: a gap was identified and an action created - to its owner.
        for plan in plans:
            send_competency_mail(
                plan, 'mail_template_development_plan_created', 'support',
                email_to=join_emails(plan.assigned_person_id.email),
            )
        return plans

    def write(self, vals):
        self.mapped('assessment_id')._check_manager_hr_readonly()
        protected_fields = {
            'name',
            'employee_id',
            'assessment_id',
            'assessment_line_id',
            'competency_id',
            'action_type',
            'action_plan',
            'assigned_person_id',
            'date_start',
            'target_date',
            'target_level',
            'target_level_id',
            'state',
            'completion_percentage',
            'remarks',
            'result',
            'goal_id',
            # Writable aliases of the same fields:
            'appraisal_id',
            'competency_line_id',
            'skill_id',
            'description',
            'owner_id',
            'due_date',
        }

        if protected_fields.intersection(vals):
            if any(plan.state == 'completed' for plan in self):
                raise ValidationError(
                    "Completed development plans are read-only "
                    "and cannot be modified or reset."
                )
        newly_completed = (
            self.filtered(lambda plan: plan.state != 'completed')
            if vals.get('state') == 'completed' else self.browse()
        )
        goal_changed = self.browse()
        if 'goal_id' in vals:
            goal_changed = self.filtered(
                lambda plan:
                    plan.goal_id.id != (vals['goal_id'] or False)
            )
        result = super().write(vals)
        goal_changed._check_selectable_goal()
        # Mail 12: the action is completed - to the employee and their
        # manager, HR in copy.
        for plan in newly_completed:
            send_competency_mail(
                plan, 'mail_template_development_plan_completed', 'support',
                email_to=join_emails(plan.sudo().employee_id.work_email, plan._manager_email()),
                email_cc=hr_emails(self.env),
            )
        return result

    @api.model
    def _cron_overdue_reminders(self):
        """Mail 11: chase an open action whose due date is approaching or has
        passed - to the employee, the owner and the manager."""
        today = fields.Date.context_today(self)
        due = self.search([
            ('state', 'in', ('planned', 'in_progress')),
            ('target_date', '!=', False),
            ('target_date', '<=', today + timedelta(days=DEVELOPMENT_REMINDER_DAYS)),
        ])
        for plan in due:
            send_competency_mail(
                plan, 'mail_template_development_plan_reminder', 'support',
                email_to=join_emails(
                    plan.sudo().employee_id.work_email,
                    plan.assigned_person_id.email,
                    plan._manager_email(),
                ),
            )
        for plan in due.filtered('is_overdue'):
            if plan.assigned_person_id and not plan.activity_ids.filtered(
                lambda activity, p=plan: activity.user_id == p.assigned_person_id
            ):
                plan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=fields.Date.context_today(self),
                    summary=self.env._('Overdue development action'),
                    user_id=plan.assigned_person_id.id,
                )
