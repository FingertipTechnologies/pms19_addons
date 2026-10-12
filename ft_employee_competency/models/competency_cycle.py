from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta


class EmployeeCompetencyCycle(models.Model):
    """A review window — Q2 FY 2026-27, and so on.

    The cycle is what makes quarter-on-quarter comparison possible: an
    assessment belongs to exactly one cycle, and "the previous assessment" is
    the completed one from the cycle before. It also holds the deadlines the
    reminder crons chase.
    """

    _name = 'employee.competency.cycle'
    _description = 'Competency Review Cycle'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(
        required=True, tracking=True,
        help='Cycle name as the business says it, such as "Q2 FY 2026-27".',
    )
    review_type = fields.Selection(
        selection=[
            ('quarterly', 'Quarterly'),
            ('half_yearly', 'Half Yearly'),
            ('annual', 'Annual'),
        ],
        string='Review Type', default='quarterly', required=True, tracking=True,
    )
    date_from = fields.Date(string='Start Date', required=True, tracking=True)
    date_to = fields.Date(string='End Date', required=True, tracking=True)
    self_review_deadline = fields.Date(
        string='Self Review Deadline',
        help='Date by which employees should have submitted their self '
             'assessment. Drives the pending self-review reminder.',
    )
    manager_review_deadline = fields.Date(
        string='Manager Review Deadline',
        help='Date by which managers should have completed their review. '
             'Drives the pending approval reminder.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, ondelete='restrict',
        default=lambda self: self.env.company, index=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('open', 'Open'),
            ('closed', 'Closed'),
        ],
        default='draft', required=True, tracking=True, copy=False,
    )

    employee_ids = fields.Many2many(
        'hr.employee', string='Applicable Employees',
        help='Employees this cycle covers. Leave empty to cover every active '
             'employee whose job has a validated competency matrix.',
    )
    department_ids = fields.Many2many(
        'hr.department', string='Applicable Departments',
        help='Narrows the cycle to these departments. Ignored when '
             'Applicable Employees is filled.',
    )
    assessment_ids = fields.One2many(
        'employee.competency.assessment',
        'cycle_id',
        string='Assessments',
        context={'active_test': False},
    )
    notes = fields.Html()
    active = fields.Boolean(default=True)

    _name_company_uniq = models.Constraint(
        'unique(name, company_id)',
        'A review cycle with this name already exists in this company.',
    )

    @api.model
    def _validate_future_dates(self, values):
        today = fields.Date.context_today(self)

        date_fields = {
            'date_from': 'Start Date',
            'date_to': 'End Date',
            'self_review_deadline': 'Self Review Deadline',
            'manager_review_deadline': 'Manager Review Deadline',
        }

        for field_name, label in date_fields.items():
            if not values.get(field_name):
                continue

            selected_date = fields.Date.to_date(values[field_name])

            if field_name == 'date_from':
                if selected_date < today:
                    raise ValidationError(self.env._(
                        'Start Date cannot be in the past. '
                        'Select today or a future date.'
                    ))
            elif selected_date <= today:
                raise ValidationError(self.env._(
                    '%(field)s must be a future date. '
                    'Please select tomorrow or a later date.',
                    field=label,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        cycles = super().create(vals_list)

        # for cycle in cycles:
        #     cycle._validate_future_dates({
        #         'date_from': cycle.date_from,
        #         'date_to': cycle.date_to,
        #         'self_review_deadline': cycle.self_review_deadline,
        #         'manager_review_deadline': cycle.manager_review_deadline,
        #     })

        return cycles

    def write(self, vals):
        if vals.get('state') == 'draft':
            Assessment = self.env[
                'employee.competency.assessment'
            ].sudo().with_context(active_test=False)

            for cycle in self:
                if Assessment.search_count(
                    [('cycle_id', '=', cycle.id)],
                    limit=1,
                ):
                    raise UserError(
                        "Cannot reset review cycle '%s' to Draft "
                        "because assessments already exist."
                        % cycle.display_name
                    )
        # date_fields = {
        #     'date_from',
        #     'date_to',
        #     'self_review_deadline',
        #     'manager_review_deadline',
        # }

        # for cycle in self:
        #     changed_dates = {}

        #     for field_name in date_fields.intersection(vals):
        #         new_date = fields.Date.to_date(vals[field_name])

        #         if (cycle[field_name] or None) != (new_date or None):
        #             changed_dates[field_name] = vals[field_name]

        #     cycle._validate_future_dates(changed_dates)

        return super().write(vals)
        
    # @api.constrains('review_type', 'date_from', 'date_to')
    # def _check_review_type_period(self):
    #     durations = {
    #         'quarterly': 3,
    #         'half_yearly': 6,
    #         'annual': 12,
    #     }

    #     for cycle in self:
    #         months = durations.get(cycle.review_type)
    #         if not months or not cycle.date_from or not cycle.date_to:
    #             continue

    #         expected_end = (
    #             cycle.date_from
    #             + relativedelta(months=months)
    #             - relativedelta(days=1)
    #         )

    #         if cycle.date_to != expected_end:
    #             raise ValidationError(
    #                 "The selected Review Type requires a "
    #                 "%s-month period.\n"
    #                 "For Start Date %s, End Date must be %s."
    #                 % (
    #                     months,
    #                     cycle.date_from.strftime('%d-%m-%Y'),
    #                     expected_end.strftime('%d-%m-%Y'),
    #                 )
    #             )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        # BR-021.
        for cycle in self:
            if cycle.date_to < cycle.date_from:
                raise ValidationError(self.env._(
                    'On %(cycle)s, the End Date is before the Start Date.',
                    cycle=cycle.name,
                ))

    @api.constrains('date_from','date_to','self_review_deadline','manager_review_deadline',)
    def _check_deadlines(self):
        for cycle in self:
            for label, deadline in (
                (
                    self.env._('Self Review Deadline'),
                    cycle.self_review_deadline,
                ),
                (
                    self.env._('Manager Review Deadline'),
                    cycle.manager_review_deadline,
                ),
            ):
                if not deadline:
                    continue

                if cycle.date_from and deadline < cycle.date_from:
                    raise ValidationError(self.env._(
                        '%(label)s cannot be before the Start Date.',
                        label=label,
                    ))

                # if cycle.date_to and deadline >= cycle.date_to:
                #     raise ValidationError(self.env._(
                #         'The End Date must be after the %(label)s.',
                #         label=label,
                #     ))

            if (
                cycle.self_review_deadline
                and cycle.manager_review_deadline
                and cycle.manager_review_deadline
                    < cycle.self_review_deadline
            ):
                raise ValidationError(self.env._(
                    'The Manager Review Deadline cannot be before '
                    'the Self Review Deadline.'
                ))

    def _target_employees(self):
        self.ensure_one()

        if self.employee_ids:
            return self.employee_ids.filtered('active')

        return self.env['hr.employee'].search([
            ('active', '=', True),
            ('company_id', '=', self.company_id.id),
        ])

    def _overlap_employee_ids(self):
        self.ensure_one()

        # Include both the configured scope and assessments
        # already generated for this cycle.
        employees = self.sudo()._target_employees()

        assessments = self.env[
            'employee.competency.assessment'
        ].sudo().with_context(active_test=False).search([
            ('cycle_id', '=', self.id),
        ])

        return set(employees.ids) | set(
            assessments.employee_id.ids
        )

    @api.constrains(
        'state',
        'date_from',
        'date_to',
        'employee_ids',
        'department_ids',
        'company_id',
    )
    def _check_overlapping_open_cycles(self):
        Cycle = self.sudo().with_context(active_test=False)

        for cycle in self:
            if (
                cycle.state != 'open'
                or not cycle.date_from
                or not cycle.date_to
            ):
                continue

            other_cycles = Cycle.search([
                ('id', '!=', cycle.id),
                ('state', '=', 'open'),
                ('company_id', '=', cycle.company_id.id),
                ('date_from', '<=', cycle.date_to),
                ('date_to', '>=', cycle.date_from),
            ])

            employee_ids = cycle._overlap_employee_ids()

            for other in other_cycles:
                if employee_ids.intersection(
                    other._overlap_employee_ids()
                ):
                    raise ValidationError(
                        "Review cycle '%s' overlaps with open "
                        "cycle '%s' and covers one or more of "
                        "the same employees. Change the dates "
                        "or employee selection before proceeding."
                        % (
                            cycle.display_name,
                            other.display_name,
                        )
                    )

    def action_open(self):
        for cycle in self:
            if cycle.state != 'draft':
                raise UserError(self.env._(
                    'Only a draft cycle can be opened.'
                ))
        self.write({'state': 'open'})

    def action_generate_assessments(self):
        """Raise an assessment per applicable employee, skipping those already
        covered. The cycle stays Open until it is closed."""
        self._check_overlapping_open_cycles()
        Assessment = self.env['employee.competency.assessment']
        created = Assessment
        for cycle in self:
            if cycle.state == 'draft':
                raise UserError(self.env._(
                    'Open %(cycle)s before generating its assessments.',
                    cycle=cycle.name,
                ))
            if cycle.state == 'closed':
                # BR-020.
                raise UserError(self.env._(
                    '%(cycle)s is closed. No further assessment can be '
                    'raised against it.', cycle=cycle.name,
                ))
            employees = cycle._target_employees()
            if not employees:
                raise UserError(self.env._(
                    'No employee matches %(cycle)s. Check the applicable '
                    'employees and departments, and that their job positions '
                    'have a validated competency matrix.', cycle=cycle.name,
                ))
            existing = cycle.assessment_ids.employee_id
            missing = employees - existing
            skipped = employees.filtered(lambda e: e.job_id.competency_matrix_state != 'validated')
            eligible = missing - skipped
            if eligible:
                created |= Assessment.create([
                    {
                        'employee_id': employee.id,
                        'cycle_id': cycle.id,
                        'assessment_date': cycle.date_to,
                    }
                    for employee in eligible
                ])
            if skipped:
                cycle.message_post(body=self.env._(
                    'No assessment was raised for %(names)s: their job '
                    'position has no validated competency matrix.',
                    names=', '.join(skipped.mapped('display_name')),
                ))
        created.action_start_self_review()
        return created

    def action_close(self):
        for cycle in self:
            if cycle.state != 'open':
                raise UserError(self.env._('Only an open cycle can be closed.'))
            pending = cycle.assessment_ids.filtered(
                lambda a: a.state not in ('done', 'cancel')
            )
            if pending:
                raise UserError(self.env._(
                    '%(count)s assessment(s) in %(cycle)s are not completed '
                    'yet: %(names)s',
                    count=len(pending), cycle=cycle.name,
                    names=', '.join(pending.mapped('display_name')[:10]),
                ))
        self.write({'state': 'closed'})

    def action_reopen(self):
        # BR-020: HR can reopen a closed cycle; the view limits the button to
        # them, and only HR has write access to cycles at all.
        self.write({'state': 'open'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def action_view_assessments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Assessments: %s', self.name),
            'res_model': 'employee.competency.assessment',
            'view_mode': 'list,kanban,form',
            'domain': [('cycle_id', '=', self.id)],
            'context': {'default_cycle_id': self.id},
        }
