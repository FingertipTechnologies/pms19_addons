from odoo import api, fields, models

from .competency_utils import SCOPE_SELECTION, rating_to_int


class EmployeeCompetencyProfile(models.Model):
    """Where an employee stands on one competency, right now.

    One row per employee and competency, written only when an assessment
    completes (BR-018). The assessment lines are the history; this is the
    current picture, and it is what the employee form's Competency tab shows
    and what readiness falls back on for competencies the current job never
    assessed.
    """

    _name = 'employee.competency.profile'
    _description = 'Employee Competency Profile'
    _order = 'employee_id, category_id, competency_id'
    _rec_name = 'competency_id'

    employee_id = fields.Many2one(
        'hr.employee', string='Employee',
        required=True, ondelete='cascade', index=True,
    )
    employee_user_id = fields.Many2one(
        related='employee_id.user_id', store=True, index=True,
        string='Employee User',
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, index=True,
        string='Department',
    )
    job_id = fields.Many2one(
        related='employee_id.job_id', store=True, index=True,
        string='Job Position',
    )
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    competency_id = fields.Many2one(
        'employee.competency', string='Competency',
        required=True, ondelete='cascade', index=True,
    )
    category_id = fields.Many2one(
        related='competency_id.category_id', store=True, string='Category',
    )
    scope = fields.Selection(
        selection=SCOPE_SELECTION, related='competency_id.scope', store=True,
    )
    current_level = fields.Integer(
        string='Current Level', aggregator='avg',
        help='The latest approved level, from the most recent completed '
             'assessment.',
    )
    required_level = fields.Integer(
        string='Required Level', compute='_compute_requirement', store=True,
        aggregator='avg',
        help="Level the employee's current job asks for. Unlike the "
             'assessment line, this one follows the job matrix: it is the '
             'live picture, not history.',
    )
    gap = fields.Integer(
        string='Gap Score', compute='_compute_requirement', store=True, aggregator='avg',
        help='Current level minus the level the current job requires.',
    )
    mandatory = fields.Boolean(compute='_compute_requirement', store=True)
    last_assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Last Assessment',
        ondelete='set null',
    )
    last_assessment_date = fields.Date(string='Last Assessment Date')

    # -- history ---------------------------------------------------------
    # Written with current_level, by hr.employee._rebuild_competency_profile,
    # from the employee's completed reviews in date order.
    previous_level = fields.Integer(
        string='Previous Level', aggregator='avg',
        help='The level approved for this competency in the completed review '
             'before the latest one. Zero when it has been assessed only once.',
    )
    level_change = fields.Integer(
        string='Change', compute='_compute_growth', store=True, aggregator='avg',
        help='Current level minus previous level.',
    )
    development_plan_ids = fields.One2many(
        'employee.development.plan', 'profile_id', string='Development Plans',
    )

    _employee_competency_uniq = models.Constraint(
        'unique(employee_id, competency_id)',
        'This employee already has a profile entry for this competency.',
    )

    @api.depends(
        'current_level', 'competency_id',
        'employee_id.job_id',
        'employee_id.job_id.competency_line_ids.required_level',
        'employee_id.job_id.competency_line_ids.mandatory',
        'employee_id.job_id.competency_line_ids.active',
    )
    def _compute_requirement(self):
        for entry in self:
            requirement = entry.employee_id.job_id.competency_line_ids.filtered(
                lambda line, e=entry: line.competency_id == e.competency_id and line.active
            )[:1]
            required = rating_to_int(requirement.required_level)
            entry.required_level = required
            entry.mandatory = bool(requirement.mandatory)
            entry.gap = (
                entry.current_level - required if required and entry.current_level else 0
            )

    @api.depends('current_level', 'previous_level')
    def _compute_growth(self):
        # BR-009 on the standing profile: zero on the first review.
        for entry in self:
            entry.level_change = (
                entry.current_level - entry.previous_level if entry.previous_level else 0
            )
