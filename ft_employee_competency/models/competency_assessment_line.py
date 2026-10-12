from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .competency_utils import (
    MAX_RATING, SCOPE_SELECTION, is_competency_manager,
    is_hr_manager,
)


class EmployeeCompetencyAssessmentLine(models.Model):
    """One competency scored inside one assessment.

    Every field down to the weightage is a SNAPSHOT taken when the assessment
    was generated (BR-003). Nothing here is related to the job matrix, on
    purpose: a line has to keep saying what it said on the day it was signed
    off, whatever the job requires a year later.
    """

    _name = 'employee.competency.assessment.line'
    _description = 'Competency Assessment Line'
    _order = 'assessment_id, sequence, id'
    _rec_name = 'competency_id'

    sequence = fields.Integer(default=10)
    assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Assessment',
        required=True, ondelete='cascade', index=True,
    )
    state = fields.Selection(related='assessment_id.state', store=True, string='Status')
    employee_id = fields.Many2one(
        related='assessment_id.employee_id', store=True, index=True,
        string='Employee',
    )
    department_id = fields.Many2one(
        related='assessment_id.department_id', store=True, index=True,
        string='Department',
    )
    job_id = fields.Many2one(
        related='assessment_id.job_id', store=True, index=True,
        string='Job Position',
    )
    cycle_id = fields.Many2one(
        related='assessment_id.cycle_id', store=True, index=True,
        string='Review Cycle',
    )
    assessment_date = fields.Date(related='assessment_id.assessment_date', store=True)
    company_id = fields.Many2one(related='assessment_id.company_id', store=True)

    # -- snapshots -----------------------------------------------------
    competency_id = fields.Many2one(
        'employee.competency', string='Competency',
        required=True, ondelete='restrict', index=True,
    )
    category_id = fields.Many2one(
        'employee.competency.category', string='Category',
        ondelete='restrict', index=True,
        help='Snapshot of the category at the time of the review.',
    )
    scope = fields.Selection(
        selection=SCOPE_SELECTION, string='Scope',
        help='Snapshot of the competency scope, so the core / functional / '
             'leadership split of an old review never shifts.',
    )
    weightage = fields.Float(
        string='Weightage %', digits=(5, 2), required=True, default=0.0,
        help='Snapshot of the job matrix weightage. Re-weighting the job '
             'afterwards never touches this.',
    )
    required_level = fields.Integer(
        string='Expected Level', required=True, default=0, aggregator='avg',
        help='Snapshot of the target level the job asked for, on the 1-5 '
             'scale.',
    )
    minimum_level = fields.Integer(string='Minimum Level', default=0)
    mandatory = fields.Boolean(default=True)
    development_threshold = fields.Integer(
        string='Development Threshold', default=3,
        help='Snapshot of the competency threshold: a final rating below this '
             'flags development even when the job requirement is met.',
    )
    evidence_required = fields.Boolean(
        string='Evidence Always Required',
        help='Snapshot of the competency setting.',
    )

    # -- ratings -------------------------------------------------------
    self_rating = fields.Integer(
        string='Self Rating', aggregator='avg',
        help='The employee\'s own rating, 1 to 5. Reference for the '
             'perception-gap conversation; it never sets the official score.',
    )
    manager_rating = fields.Integer(
        string='Manager Rating', aggregator='avg',
        help='The reviewing manager\'s rating, 1 to 5.',
    )
    final_rating = fields.Integer(
        string='Final Rating',
        aggregator='avg',
        default=0,
        help='Manually enter the official final rating from 1 to 5. '
            'This rating is used to calculate assessment scores.',
    )
    previous_rating = fields.Integer(
        string='Previous Level', aggregator='avg',
        compute='_compute_previous_rating', store=True,
        help='Final rating for the same competency in the previous completed '
             'assessment of this employee. Zero when there is none.',
    )

    # -- results -------------------------------------------------------
    weighted_score = fields.Float(
        string='Score %', digits=(5, 2),
        compute='_compute_results', store=True,
        help='Points this competency contributes to the overall score: '
             '(Final Rating / 5) x Weightage.',
    )
    gap = fields.Integer(
        string='Gap Score', compute='_compute_results', store=True, aggregator='avg',
        help='Final Rating minus Expected Level (BR-008). Negative means below '
             'the level the job asks for, and flags Development Required.',
    )
    improvement_score = fields.Integer(
        string='Improvement', compute='_compute_results', store=True, aggregator='avg',
        help='Final rating minus the previous cycle\'s final rating.',
    )
    is_strength = fields.Boolean(
        string='Strength', compute='_compute_results', store=True,
        help='A rating of 4 or better that also meets the job requirement.',
    )
    development_required = fields.Boolean(
        string='Development Required', compute='_compute_results', store=True,
        help='Set when the rating falls below the competency threshold or '
             'below the level the job requires.',
    )
    evidence_needed = fields.Boolean(compute='_compute_evidence_needed')
    can_self_rate = fields.Boolean(
        compute='_compute_can_rate_as_manager',
        help='Technical: opens the self rating columns to the assessed '
             'employee while the self assessment is open.',
    )
    can_edit_final_rating = fields.Boolean(
        compute='_compute_can_rate_as_manager',
    )
    can_rate_as_manager = fields.Boolean(
        compute='_compute_can_rate_as_manager',
        help='Technical: locks the manager columns in the view for anyone '
             'outside the competency manager group.',
    )

    # -- narrative -----------------------------------------------------
    employee_comments = fields.Text(string='Employee Comments')
    manager_comments = fields.Text(string='Manager Comments')
    evidence = fields.Text(
        help='Examples and results that back the rating.',
    )

    development_plan_ids = fields.One2many(
        'employee.development.plan', 'assessment_line_id',
        string='Development Plans',
    )

    # -- levels as records of the rating scale --------------------------
    # The integers above are what every score is computed from; these are
    # the same values as rows of the 1-5 level master (hr.skill.level in the
    # specification), for grouping and for reading the level's definition.
    expected_level_id = fields.Many2one(
        'employee.competency.level', string='Expected Level Record',
        compute='_compute_level_ids', store=True, ondelete='restrict',
    )
    previous_level_id = fields.Many2one(
        'employee.competency.level', string='Previous Level Record',
        compute='_compute_level_ids', store=True, ondelete='restrict',
    )

    # -- specification names (hr.appraisal.competency.line) -------------
    appraisal_id = fields.Many2one(related='assessment_id', string='Appraisal (spec)')
    skill_type_id = fields.Many2one(related='category_id', string='Competency Category (spec)')
    skill_id = fields.Many2one(related='competency_id', string='Competency (spec)')
    competency_scope = fields.Selection(related='scope', string='Competency Scope (spec)')
    gap_score = fields.Integer(related='gap', string='Gap Score (spec)')
    development_action_ids = fields.One2many(
        related='development_plan_ids', string='Development Actions (spec)',
    )

    _self_rating_range = models.Constraint(
        f'CHECK(self_rating BETWEEN 0 AND {MAX_RATING})',
        f'A self rating must be between 1 and {MAX_RATING}.',
    )
    _manager_rating_range = models.Constraint(
        f'CHECK(manager_rating BETWEEN 0 AND {MAX_RATING})',
        f'A manager rating must be between 1 and {MAX_RATING}.',
    )
    _final_rating_range = models.Constraint(
        # BR-004.
        f'CHECK(final_rating BETWEEN 0 AND {MAX_RATING})',
        f'A final rating must be between 1 and {MAX_RATING}.',
    )
    _weightage_positive = models.Constraint(
        'CHECK(weightage >= 0)',
        'A weightage cannot be negative.',
    )

    @api.depends(
        'competency_id',
        'assessment_id.previous_assessment_id',
        'assessment_id.previous_assessment_id.line_ids.final_rating',
    )
    def _compute_previous_rating(self):
        # BR-009 / Previous Level: looked up, not snapshotted. It used to be
        # copied once, when the lines were generated - and a cycle is usually
        # opened while the one before it is still being reviewed, so the
        # previous review was not completed yet, every line got 0, and nothing
        # ever filled it in afterwards. Improvement read 0 with it.
        for line in self:
            previous = line.assessment_id.previous_assessment_id.line_ids.filtered(
                lambda prev, c=line.competency_id: prev.competency_id == c
            )[:1]
            line.previous_rating = previous.final_rating

    @api.depends('required_level', 'previous_rating')
    def _compute_level_ids(self):
        levels = self.env['employee.competency.level']._by_rating()
        empty = self.env['employee.competency.level']
        for line in self:
            line.expected_level_id = levels.get(line.required_level, empty)
            line.previous_level_id = levels.get(line.previous_rating, empty)

    # @api.depends('manager_rating')
    # def _compute_final_rating(self):
    #     # BR-015: the manager's rating is what becomes official, not the
    #     # employee's. Stored and writable, so the manager can still override.
    #     for line in self:
    #         line.final_rating = line.manager_rating

    @api.depends(
        'final_rating', 'weightage', 'required_level',
        'previous_rating', 'development_threshold',
    )
    def _compute_results(self):
        for line in self:
            if not line.final_rating:
                # Nothing is a gap until somebody has actually rated it.
                line.weighted_score = 0.0
                line.gap = 0
                line.improvement_score = 0
                line.is_strength = False
                line.development_required = False
                continue
            # BR-005.
            line.weighted_score = (line.final_rating / MAX_RATING) * line.weightage
            # BR-008.
            line.gap = line.final_rating - line.required_level
            # BR-009.
            line.improvement_score = (
                line.final_rating - line.previous_rating if line.previous_rating else 0
            )
            # BR-013.
            line.is_strength = line.final_rating >= 4 and line.gap >= 0
            # BR-011.
            line.development_required = (
                line.final_rating < (line.development_threshold or 0) or line.gap < 0
            )

    @api.depends('final_rating', 'evidence_required')
    def _compute_evidence_needed(self):
        # BR-012: the ratings that need justifying are the ones a reader will
        # question — the bottom two and the top one — plus anything the
        # competency master insists on.
        for line in self:
            line.evidence_needed = bool(
                line.evidence_required
                or (line.final_rating and (
                    line.final_rating <= 2 or line.final_rating == MAX_RATING
                ))
            )

    def _rating_permissions(self):
        self.ensure_one()

        assessment = self.assessment_id
        own_assessment = (
            assessment.employee_user_id == self.env.user
        )

        # On your own assessment, only self-review is permitted.
        # Manager and Final Rating remain blocked regardless of role.
        if own_assessment:
            return (
                assessment.state == 'employee_review',
                False,
                False,
            )

        privileged = (
            self.env.su
            or is_hr_manager(self.env)
            or self.env.user.has_group('base.group_system')
        )

        can_manager = (
            assessment.reviewer_user_id == self.env.user
            and (
                is_competency_manager(self.env)
                or privileged
            )
            and assessment.state == 'manager_review'
        )
        
        can_final = (
            can_manager
            or (
                privileged
                and assessment.state == 'hr_review'
            )
        )

        return False, can_manager, can_final

    @api.depends(
        'state',
        'assessment_id.employee_user_id',
        'assessment_id.reviewer_user_id',
    )
    @api.depends_context('uid')
    def _compute_can_rate_as_manager(self):
        for line in self:
            (
                line.can_self_rate,
                line.can_rate_as_manager,
                line.can_edit_final_rating,
            ) = line._rating_permissions()

    # ------------------------------------------------------------------
    # Who may write what
    #
    # The view hides the manager's columns from an employee, but a view is
    # cosmetic: `groups` on a field node stops it being rendered, not written.
    # Without a server-side guard an employee could set their own final rating
    # through the ORM, which is the one number the whole module treats as
    # official (BR-015). So the rule lives here, where it actually holds.
    # ------------------------------------------------------------------
    MANAGER_FIELDS = frozenset({
        'manager_rating', 'final_rating', 'manager_comments', 'evidence',
    })
    EMPLOYEE_FIELDS = frozenset({'self_rating', 'employee_comments'})

    def _check_rating_access(self, vals, creating=False):
        controlled_fields = {
            'self_rating',
            'employee_comments',
            'manager_rating',
            'manager_comments',
            'evidence',
            'final_rating',
        }

        for line in self:
            if creating:
                changed = {
                    name
                    for name in controlled_fields
                    if line[name]
                }
            else:
                changed = line._changed_fields(
                    controlled_fields.intersection(vals),
                    vals,
                )

            if not changed:
                continue

            can_self, can_manager, can_final = (
                line._rating_permissions()
            )

            if (
                changed.intersection({
                    'self_rating', 'employee_comments'
                })
                and not can_self
            ):
                raise AccessError(
                    "Only the assessed employee can enter Self "
                    "Rating and Employee Comments during Employee "
                    "Review. HR/Admin cannot enter them on behalf "
                    "of the employee."
                )

            if (
                changed.intersection({
                    'manager_rating',
                    'manager_comments',
                    'evidence',
                })
                and not can_manager
            ):
                raise AccessError(
                    "Only the assigned reviewing manager can enter "
                    "Manager Rating and Manager Comments during "
                    "Manager Review. HR/Admin cannot change them."
                )

            if 'final_rating' in changed and not can_final:
                raise AccessError(
                    "Final Rating can be changed by the assigned "
                    "manager during Manager Review, or by HR/Admin "
                    "during HR Approval."
                )
    def _changed_fields(self, field_names, vals):
        """The subset of ``field_names`` whose value in ``vals`` differs from
        what is stored. The web client saves the whole editable row, so a
        manager column can arrive untouched (an empty text cell as ``''``
        instead of False); only a real change counts."""
        return {
            name for name in field_names
            if any((line[name] or False) != (vals[name] or False) for line in self)
        }

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._check_rating_access({}, creating=True)
        return lines

    def write(self, vals):
        self.mapped('assessment_id')._check_manager_hr_readonly()
        if 'assessment_id' in vals:
            moved = self.filtered(
                lambda line:
                    line.assessment_id.id
                    != (vals['assessment_id'] or False)
            )
            if moved:
                raise UserError(
                    "An assessment line cannot be moved to "
                    "another assessment. Create a new line instead."
                )

        self._check_rating_access(vals)
        return super().write(vals)

    @api.onchange('competency_id')
    def _onchange_competency_id(self):
        for line in self.filtered('competency_id'):
            competency = line.competency_id
            line.category_id = competency.category_id
            line.scope = competency.scope
            line.development_threshold = competency.development_threshold
            line.evidence_required = competency.evidence_required
            if not line.weightage:
                line.weightage = competency.default_weightage

    def action_create_development_plan(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Development Plan'),
            'res_model': 'employee.development.plan',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_assessment_id': self.assessment_id.id,
                'default_assessment_line_id': self.id,
                'default_competency_id': self.competency_id.id,
                'default_name': self.env._('Improve %s', self.competency_id.name),
                'default_target_level': self.required_level or MAX_RATING,
            },
        }
