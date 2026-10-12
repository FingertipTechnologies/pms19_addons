from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EmployeeAppraisalGoal(models.Model):
    """A goal agreed with an employee - the Community stand-in for the
    Enterprise ``hr.appraisal.goal``.

    The specification links a development action to an appraisal goal
    (``goal_id``) and tells the developer to verify the model in their Odoo
    edition. ``hr.appraisal.goal`` ships with the Enterprise ``hr_appraisal``
    module, which this module does not depend on, so the goal lives here, next
    to the assessment that plays the part of ``hr.appraisal``.

    A goal is broader than a development action: it states an outcome ("Lead
    the Q3 client migration"), and the development actions under it are the
    steps that close the competency gaps standing in its way.
    """

    _name = 'employee.appraisal.goal'
    _description = 'Appraisal Goal'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'deadline, id'

    name = fields.Char(string='Goal', required=True, tracking=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        ondelete='cascade', index=True, tracking=True,
    )
    employee_user_id = fields.Many2one(
        related='employee_id.user_id', store=True, index=True, string='Employee User',
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, index=True, string='Department',
    )
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Assessment',
        ondelete='set null', index=True,
        domain="[('employee_id', '=', employee_id)]",
        help='The review in which the goal was agreed.',
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        compute='_compute_job_id',
        store=True,
    )

    cycle_id = fields.Many2one(
        related='assessment_id.cycle_id',
        string='Review Cycle',
        store=True,
        readonly=True,
    )

    @api.depends(
        'assessment_id',
        'assessment_id.job_id',
        'employee_id',
        'employee_id.job_id',
    )
    def _compute_job_id(self):
        for goal in self:
            goal.job_id = (
                goal.assessment_id.job_id
                if goal.assessment_id
                else goal.employee_id.job_id
            )

    manager_id = fields.Many2one(
        'res.users', string='Manager', tracking=True,
        default=lambda self: self.env.user, domain=[('share', '=', False)],
        help='Who agreed the goal with the employee and follows it up.',
    )
    description = fields.Html()
    deadline = fields.Date(tracking=True)
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('in_progress', 'In Progress'),
            ('done', 'Achieved'),
            ('cancel', 'Cancelled'),
        ],
        string='Status', default='draft', required=True, tracking=True, copy=False,
    )
    development_action_ids = fields.One2many(
        'employee.development.plan', 'goal_id', string='Development Actions',
    )
    def write(self, vals):
        self.mapped(
            'assessment_id'
        )._check_manager_hr_readonly()
        return super().write(vals)

    @api.constrains('manager_id')
    def _check_internal_manager(self):
        for goal in self:
            if goal.manager_id and goal.manager_id.sudo().share:
                raise ValidationError(
                    "The Goal Manager must be an internal user. "
                    "Portal and public users cannot be selected."
                )

    @api.constrains('deadline')
    def _check_future_deadline(self):
        today = fields.Date.context_today(self)

        for goal in self:
            if goal.deadline and goal.deadline <= today:
                raise ValidationError(self.env._(
                    'The goal deadline must be a future date. '
                    'Please select tomorrow or a later date.'
                ))

    @api.onchange('assessment_id')
    def _onchange_assessment_id(self):
        if self.assessment_id and not self.employee_id:
            self.employee_id = self.assessment_id.employee_id

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})
