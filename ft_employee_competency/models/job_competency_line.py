from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .competency_utils import RATING_SELECTION, SCOPE_SELECTION, rating_to_int


class EmployeeJobCompetencyLine(models.Model):
    """One competency a job position requires, at a level and a weightage.

    Together, a job's lines are its competency matrix: the standard an
    employee in that job is measured against. An assessment copies the matrix
    onto its own lines at generation time and never reads it again, so
    re-weighting a job next quarter leaves last quarter's scores alone.
    """

    _name = 'employee.job.competency.line'
    _description = 'Job Competency Requirement'
    _order = 'job_id, sequence, id'
    _rec_name = 'competency_id'

    sequence = fields.Integer(default=10)
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        required=True, ondelete='cascade', index=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='job_id.department_id',
        store=True,
        readonly=True,
        index=True,
    )
    competency_id = fields.Many2one(
        'employee.competency', string='Competency',
        required=True, ondelete='restrict', index=True, domain=[('active', '=', True)],
    )
    category_id = fields.Many2one(
        'employee.competency.category', string='Category',
        related='competency_id.category_id', store=True,
    )
    scope = fields.Selection(
        selection=SCOPE_SELECTION, string='Scope',
        related='competency_id.scope', store=True,
    )
    required_level = fields.Selection(
        selection=RATING_SELECTION, string='Target Level',
        required=True, default='3',
        help='The level the job expects. An employee rated below this has a '
             'gap on this competency. Snapshotted onto each assessment line as '
             'its Expected Level.',
    )
    minimum_level = fields.Selection(
        selection=RATING_SELECTION, string='Minimum Level',
        help='The lowest level still acceptable in the role. Optional — used '
             'to separate "below target" from "below acceptable".',
    )
    weightage = fields.Float(
        string='Weightage %', digits=(5, 2), required=True, default=0.0,
        help='How much of the overall score this competency carries. The '
             'assessed competencies of a job must total 100%.',
    )
    mandatory = fields.Boolean(
        default=True,
        help='Mandatory competencies decide readiness for the role. Someone '
             'below the required level on a mandatory competency is not ready '
             'for the job however well they score elsewhere.',
    )
    assessment_required = fields.Boolean(
        string='Assess', default=True,
        help='Include this competency on generated assessments. Clear it to '
             'record a requirement for reference without scoring it — such a '
             'line carries no weightage.',
    )
    leadership_competency = fields.Boolean(
        string='Leadership Competency',
        compute='_compute_leadership_competency', store=True, readonly=False,
        help='Marks the competency for leadership analysis. Ticks itself for a '
             'leadership-scope competency and can be set by hand on any other.',
    )
    effective_from = fields.Date(
        help='Date the requirement starts applying. Assessments generated for '
             'a cycle ending before this date skip the line.',
    )
    effective_to = fields.Date(
        help='Leave empty while the requirement is current.',
    )
    notes = fields.Text()
    company_id = fields.Many2one(related='job_id.company_id', store=True)
    active = fields.Boolean(default=True)

    # The two levels as records of the rating scale (hr.skill.level in the
    # specification), so a report can group by "4 - Strong" and a reader sees
    # the level's definition. The Selection above stays the source of truth -
    # every score is arithmetic on its digit - and these follow it both ways.
    target_level_id = fields.Many2one(
        'employee.competency.level', string='Target Level Record',
        compute='_compute_level_ids', inverse='_inverse_target_level_id',
        store=True, ondelete='restrict',
    )
    minimum_level_id = fields.Many2one(
        'employee.competency.level', string='Minimum Level Record',
        compute='_compute_level_ids', inverse='_inverse_minimum_level_id',
        store=True, ondelete='restrict',
    )
    skill_id = fields.Many2one(related='competency_id', string='Competency (spec)')

    @api.depends('required_level', 'minimum_level')
    def _compute_level_ids(self):
        levels = self.env['employee.competency.level']._by_rating()
        empty = self.env['employee.competency.level']
        for line in self:
            line.target_level_id = levels.get(rating_to_int(line.required_level), empty)
            line.minimum_level_id = levels.get(rating_to_int(line.minimum_level), empty)

    def _inverse_target_level_id(self):
        for line in self.filtered('target_level_id'):
            line.required_level = str(line.target_level_id.rating)

    def _inverse_minimum_level_id(self):
        for line in self:
            line.minimum_level = str(line.minimum_level_id.rating) if line.minimum_level_id else False

    _job_competency_uniq = models.Constraint(
        'unique(job_id, competency_id)',
        'This competency is already on the job competency matrix.',
    )
    _weightage_positive = models.Constraint(
        'CHECK(weightage >= 0)',
        'A weightage cannot be negative.',
    )

    @api.depends('competency_id.scope')
    def _compute_leadership_competency(self):
        for line in self:
            line.leadership_competency = line.competency_id.scope == 'leadership'

    @api.constrains('competency_id', 'active', 'job_id')
    def _check_active_competency(self):
        for line in self:
            if (
                line.active
                and line.competency_id
                and not line.competency_id.active
            ):
                raise ValidationError(
                    "Archived competency '%s' cannot be added "
                    "to an active Job Competency Matrix. "
                    "Select an active competency."
                    % line.competency_id.display_name
                )

    @api.constrains('effective_from', 'effective_to')
    def _check_effective_dates(self):
        # BR-021: a requirement cannot stop applying before it starts.
        for line in self:
            if (
                line.effective_from and line.effective_to
                and line.effective_to < line.effective_from
            ):
                raise ValidationError(self.env._(
                    'On %(competency)s, the Effective To date (%(to)s) is '
                    'before the Effective From date (%(from_)s).',
                    competency=line.competency_id.display_name,
                    to=line.effective_to,
                    from_=line.effective_from,
                ))

    @api.constrains('required_level', 'minimum_level')
    def _check_levels(self):
        for line in self:
            if not line.minimum_level:
                continue
            if rating_to_int(line.minimum_level) > rating_to_int(line.required_level):
                raise ValidationError(self.env._(
                    'On %(competency)s, the Minimum Level cannot be above the '
                    'Target Level.',
                    competency=line.competency_id.display_name,
                ))

    @api.constrains('weightage', 'assessment_required', 'active', 'job_id')
    def _check_weightage_total(self):
        # BR-001, in two halves. Overshooting 100% is always a mistake and is
        # refused the moment it happens. Undershooting is not: a matrix is
        # built one line at a time and is legitimately incomplete in between,
        # so falling short only blocks validating the matrix — see
        # hr.job.action_validate_competency_matrix.
        for job in self.job_id:
            job._check_competency_weightage_ceiling()

    @api.onchange('competency_id')
    def _onchange_competency_id(self):
        for line in self:
            if line.competency_id and not line.weightage:
                line.weightage = line.competency_id.default_weightage

    @api.onchange('assessment_required')
    def _onchange_assessment_required(self):
        # A competency that is not scored carries no weight, or it would eat
        # into the 100% the scored ones have to share.
        for line in self.filtered(lambda l: not l.assessment_required):
            line.weightage = 0.0

    def _is_effective_on(self, date):
        """Return the lines of ``self`` that apply on ``date``."""
        return self.filtered(lambda line: (
            (not line.effective_from or line.effective_from <= date)
            and (not line.effective_to or line.effective_to >= date)
        ))
