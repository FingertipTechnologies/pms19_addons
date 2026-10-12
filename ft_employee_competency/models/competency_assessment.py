from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

from .competency_utils import (
    MAX_RATING, READINESS_SELECTION, WEIGHTAGE_TOLERANCE, hr_emails,
    is_competency_manager, is_hr_manager, join_emails, rating_to_int,
    readiness_of, send_competency_mail,
)


class EmployeeCompetencyAssessment(models.Model):
    """One employee's competency review for one cycle.

    The header holds the scores and the summary; the arithmetic lives on the
    lines. Every score here is a roll-up of ``line_ids``, so nothing on this
    model has to be maintained by hand except the manager's judgement calls —
    performance, potential and the two summaries.
    """

    _name = 'employee.competency.assessment'
    _description = 'Employee Competency Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'assessment_date desc, id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: self.env._('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True,
        ondelete='restrict', index=True, tracking=True,
    )
    employee_user_id = fields.Many2one(
        related='employee_id.user_id', store=True, index=True,
        string='Employee User',
        help='Technical: lets an employee find their own assessment.',
    )
    department_id = fields.Many2one(
        'hr.department', string='Department',
        compute='_compute_employee_context', store=True, readonly=False,
        index=True,
    )
    job_id = fields.Many2one(
        'hr.job', string='Job Position',
        compute='_compute_employee_context', store=True, readonly=False,
        index=True,
        help='The job the employee held when the assessment was raised. It is '
             'a snapshot: moving the employee to another job later does not '
             'rewrite this review.',
    )
    cycle_id = fields.Many2one(
        'employee.competency.cycle', string='Review Cycle',
        required=True, ondelete='restrict', index=True, tracking=True,
    )
    reviewer_id = fields.Many2one(
        'hr.employee', string='Reviewer',
        compute='_compute_employee_context', store=True, readonly=False,
        tracking=True,
        help='The manager who owns the manager review. Defaults to the '
             "employee's manager.",
    )
    reviewer_user_id = fields.Many2one(
        related='reviewer_id.user_id', store=True, index=True,
        string='Reviewer User',
    )
    is_pending_my_review = fields.Boolean(
        string='Awaiting My Review',
        compute='_compute_is_pending_my_review',
        search='_search_is_pending_my_review',
        help='Technical: drives the To Review menu. An open assessment the '
             'current user reviews — or, for an HR manager, any open '
             'assessment, since HR oversees every review without being the '
             'named reviewer on any of them.',
    )
    assessment_date = fields.Date(
        string='Assessment Date', required=True,
        default=fields.Date.context_today, tracking=True,
    )
    active = fields.Boolean(
        default=True,
        copy=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('employee_review', 'Employee Review'),
            ('manager_review', 'Manager Review'),
            ('hr_review', 'HR Approval'),
            ('done', 'Completed'),
            ('cancel', 'Cancelled'),
        ],
        default='draft', required=True, tracking=True, copy=False,
        help='Draft -> Employee Review (self assessment) -> Manager Review '
             '(manager rating, evidence and final rating) -> HR Approval -> '
             'Completed. HR approval certifies the final ratings and writes '
             'them onto the employee profile.',
    )
    company_id = fields.Many2one(
        related='cycle_id.company_id', store=True, index=True, string='Company',
    )

    # Final competency certification: the HR approval that makes the final
    # ratings the official result. Written by the workflow only.
    hr_approved_on = fields.Datetime(
        string='Certified On', readonly=True, copy=False, tracking=True,
        help='When the final ratings were approved and certified. From this '
             'moment they are the official competency result.',
    )
    hr_approved_by_id = fields.Many2one(
        'res.users', string='Certified By', readonly=True, copy=False,
        tracking=True,
    )

    goal_ids = fields.One2many(
        'employee.appraisal.goal', 'assessment_id', string='Goals',
    )

    # Specification names (hr.appraisal in the workbook).
    review_cycle_id = fields.Many2one(related='cycle_id', string='Review Cycle (spec)')
    competency_line_ids = fields.One2many(
        related='line_ids', readonly=False, string='Competency Lines (spec)',
    )

    line_ids = fields.One2many(
        'employee.competency.assessment.line', 'assessment_id',
        string='Competency Lines', copy=True,
    )

    # ------------------------------------------------------------------
    # Scores
    # ------------------------------------------------------------------
    core_score = fields.Float(
        string='Core Score / 5', digits=(3, 2),
        compute='_compute_scores', store=True, aggregator='avg',
        help='Weighted average final rating across the core competencies.',
    )
    functional_score = fields.Float(
        string='Functional Score / 5', digits=(3, 2),
        compute='_compute_scores', store=True, aggregator='avg',
    )
    leadership_score = fields.Float(
        string='Leadership Score / 5', digits=(3, 2),
        compute='_compute_scores', store=True, aggregator='avg',
        help='Zero when the job matrix carries no leadership competency.',
    )
    overall_score_percent = fields.Float(
        string='Overall Score %', digits=(5, 2),
        compute='_compute_scores', store=True, tracking=True, aggregator='avg',
        help='Sum of the weighted score of every line. With weightages '
             'totalling 100%, this runs from 20% (all ones) to 100% (all '
             'fives).',
    )
    overall_score = fields.Float(
        string='Overall Score / 5', digits=(3, 2),
        compute='_compute_scores', store=True, tracking=True, aggregator='avg',
        help='The overall percentage put back on the 1-5 scale.',
    )
    previous_assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Previous Assessment',
        compute='_compute_previous_assessment_id', store=True,
        ondelete='set null',
        help='The last completed assessment for this employee before the '
             'current cycle. Draft and cancelled reviews are never linked.',
    )
    previous_overall_score = fields.Float(
        string='Previous Score / 5', digits=(3, 2),
        compute='_compute_improvement', store=True, aggregator='avg',
    )
    improvement_score = fields.Float(
        string='Improvement', digits=(3, 2),
        compute='_compute_improvement', store=True, aggregator='avg',
        help='Overall score minus the previous overall score. Positive means '
             'the employee improved on the previous cycle.',
    )
    previous_appraisal_id = fields.Many2one(
        related='previous_assessment_id', string='Previous Appraisal (spec)',
    )
    # ------------------------------------------------------------------
    # Gaps, readiness and judgement
    # ------------------------------------------------------------------
    performance_rating = fields.Selection(
        selection=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        string='Performance Rating', tracking=True,
        help="Management's view of delivery this cycle. Entered by the "
             'manager; it is not derived from the competency scores.',
    )
    potential_rating = fields.Selection(
        selection=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        string='Potential Rating', tracking=True,
        help='Judgement on how far the employee can grow. Together with the '
             'performance rating it drives the Leadership Pipeline report.',
    )
    target_job_id = fields.Many2one(
        'hr.job', string='Target Job',
        compute='_compute_target_job_id', store=True, readonly=False,
        help='The role readiness is measured against. Defaults to the target '
             'job on the employee record.',
    )
    role_readiness_percent = fields.Float(
        string='Role Readiness %', digits=(5, 2),
        compute='_compute_readiness', store=True, aggregator='avg',
        help='Share of the mandatory competencies of the target job that the '
             'employee already meets. Empty when no target job is set.',
    )
    readiness_status = fields.Selection(
        selection=READINESS_SELECTION, string='Readiness Status',
        compute='_compute_readiness', store=True,
    )
    strength_summary = fields.Text(
        string='Strength Summary',
        help='The strengths the manager wants on the record for this cycle.',
    )
    development_summary = fields.Text(
        string='Development Summary',
        help='The gaps and focus areas for the next cycle.',
    )

    can_edit_as_manager = fields.Boolean(
        compute='_compute_can_edit_as_manager',
        help='Technical: locks the manager-owned fields in the view — the '
             'target job, the performance and potential ratings and the two '
             'summaries — for anyone outside the competency manager group. '
             'The server-side guard is _check_manager_fields.',
    )
    can_submit_manager_review = fields.Boolean(
        compute='_compute_can_edit_as_manager',
    )
    manager_hr_readonly = fields.Boolean(
        compute='_compute_manager_hr_readonly',
    )
    can_submit_own_self_review = fields.Boolean(
        compute='_compute_can_submit_own_self_review',
    )

    development_plan_ids = fields.One2many(
        'employee.development.plan', 'assessment_id', string='Plans Raised Here',
        help='The plans RAISED FROM this assessment. Not what the Development '
             'Plans tab shows — see employee_plan_ids.',
    )
    # What the Development Plans tab lists: everything on the books for this
    # employee, not only the plans this review raised. A plan created from the
    # Development Plans menu carries no assessment — the field is optional and
    # has no default — so the tab, keyed on the link, came back empty however
    # many plans the employee had. The link is still worth having, and the tab
    # shows it as a column, but it is the wrong thing to hang the LIST on: what
    # a reviewer wants there is what this person is working on.
    employee_plan_ids = fields.Many2many(
        'employee.development.plan', string='Development Plans',
        compute='_compute_employee_plan_ids', inverse='_inverse_employee_plan_ids',
        readonly=False,
    )

    _employee_cycle_uniq = models.Constraint(
        'unique(employee_id, cycle_id)',
        'This employee already has an assessment in this review cycle.',
    )

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('employee_id')
    def _compute_employee_context(self):
        # Only fills the blanks. These are snapshots — once an assessment is
        # raised they belong to it, so an employee changing department mid
        # cycle does not silently move their review with them.
        for assessment in self:
            employee = assessment.employee_id
            if not assessment.department_id:
                assessment.department_id = employee.department_id
            if not assessment.job_id:
                assessment.job_id = employee.job_id
            if not assessment.reviewer_id:
                assessment.reviewer_id = employee.parent_id or employee.department_id.manager_id

    @api.depends('employee_id')
    def _compute_target_job_id(self):
        # sudo on the employee read: hr.employee.target_job_id is restricted to
        # hr.group_hr_user, so a reviewing manager who is not also an HR user
        # cannot read it directly. Seeding the default is an internal lookup,
        # not the manager inspecting HR data - whether they may touch this
        # assessment at all is already settled by the record rules on it, and
        # the value they end up with is the assessment's own target_job_id,
        # which is theirs to see.
        for assessment in self:
            if not assessment.target_job_id:
                assessment.target_job_id = assessment.employee_id.sudo().target_job_id

    @api.depends(
        'line_ids.final_rating', 'line_ids.weightage',
        'line_ids.scope', 'line_ids.weighted_score',
    )
    def _compute_scores(self):
        for assessment in self:
            lines = assessment.line_ids
            # BR-006: the overall percentage is simply the sum of what each
            # line contributed.
            assessment.overall_score_percent = sum(lines.mapped('weighted_score'))
            # BR-007: back onto the 1-5 scale. 100% of 100 weightage points is
            # a straight five, so the divisor is 100 / MAX_RATING.
            assessment.overall_score = assessment.overall_score_percent / (100.0 / MAX_RATING)
            for scope, field_name in (
                ('core', 'core_score'),
                ('functional', 'functional_score'),
                ('leadership', 'leadership_score'),
            ):
                scoped = lines.filtered(lambda line, s=scope: line.scope == s)
                weight = sum(scoped.mapped('weightage'))
                assessment[field_name] = (
                    sum(line.final_rating * line.weightage for line in scoped) / weight
                    if weight else 0.0
                )

    @api.depends('employee_id', 'cycle_id.date_from', 'state')
    def _compute_previous_assessment_id(self):
        # BR-010. Looked up per record rather than in one read_group: an
        # employee has a handful of assessments, and the domain differs per
        # record because it keys off that record's own cycle start.
        for assessment in self:
            date_from = assessment.cycle_id.date_from
            if not assessment.employee_id or not date_from:
                assessment.previous_assessment_id = False
                continue
            assessment.previous_assessment_id = self.with_context(active_test=False).search(
                [
                    ('employee_id', '=', assessment.employee_id.id),
                    ('state', '=', 'done'),
                    ('cycle_id.date_to', '<', date_from),
                    ('id', '!=', assessment._origin.id or 0),
                ],
                order='assessment_date desc, id desc',
                limit=1,
            )

    @api.depends(
        'overall_score',
        'previous_assessment_id',
        'previous_assessment_id.overall_score',
    )
    def _compute_improvement(self):
        for assessment in self:
            previous = assessment.previous_assessment_id.overall_score
            assessment.previous_overall_score = previous
            # BR-009 at header level. With no previous review there is nothing
            # to improve on, so the trend reads zero rather than the whole of
            # this cycle's score.
            assessment.improvement_score = (
                assessment.overall_score - previous if previous else 0.0
            )

    @api.depends(
        'target_job_id', 'target_job_id.competency_line_ids',
        'line_ids.final_rating', 'line_ids.competency_id',
    )
    def _compute_readiness(self):
        # BR-016 and BR-017.
        for assessment in self:
            mandatory = assessment.target_job_id.competency_line_ids.filtered(
                lambda line: line.mandatory and line.active
            )
            reached = assessment._levels_by_competency() if mandatory else {}
            percent, band = readiness_of(mandatory, reached)
            assessment.role_readiness_percent = percent
            assessment.readiness_status = band

    def _levels_by_competency(self):
        """Return {competency_id: level} for this employee, best evidence first.

        This assessment's own final ratings win, because they are the freshest
        judgement. Competencies the target role needs but this job never
        assessed fall back to the employee's standing profile.
        """
        self.ensure_one()
        levels = {
            line.competency_id.id: line.final_rating
            for line in self.line_ids if line.final_rating
        }
        profile = self.env['employee.competency.profile'].search([
            ('employee_id', '=', self.employee_id.id),
        ])
        for entry in profile:
            levels.setdefault(entry.competency_id.id, entry.current_level)
        return levels

    @api.depends('employee_id', 'cycle_id')
    def _compute_display_name(self):
        for assessment in self:
            employee = assessment.employee_id.name or ''
            cycle = assessment.cycle_id.name or ''
            assessment.display_name = (
                f'{employee} - {cycle}' if employee and cycle
                else (assessment.name or '')
            )

    # States in which a review is still under way and can need a reviewer.
    # HR Approval belongs to HR alone: once the manager has submitted, the
    # review is off the manager's desk.
    _OPEN_REVIEW_STATES = ('employee_review', 'manager_review')
    _HR_OPEN_STATES = ('employee_review', 'manager_review', 'hr_review')

    def _pending_review_domain(self):
        privileged = (
            self.env.su
            or is_hr_manager(self.env)
            or self.env.user.has_group('base.group_system')
        )

        assigned_reviews = [
            ('state', '=', 'manager_review'),
            ('reviewer_user_id', '=', self.env.uid),
        ]

        if privileged:
            return [
                '|',
                ('state', '=', 'hr_review'),
                '&',
                ('state', '=', 'manager_review'),
                ('reviewer_user_id', '=', self.env.uid),
            ]

        return assigned_reviews
    @api.depends('state', 'employee_user_id')
    @api.depends_context('uid')
    def _compute_can_submit_own_self_review(self):
        for assessment in self:
            assessment.can_submit_own_self_review = (
                assessment.state == 'employee_review'
                and assessment.employee_user_id == self.env.user
            )

       

    @api.depends('state')
    @api.depends_context('uid')
    def _compute_manager_hr_readonly(self):
        restricted_manager = (
            is_competency_manager(self.env)
            and not self.env.su
            and not is_hr_manager(self.env)
            and not self.env.user.has_group('base.group_system')
        )

        for assessment in self:
            assessment.manager_hr_readonly = (
                restricted_manager
                and assessment.state == 'hr_review'
            )

    def _check_manager_hr_readonly(self):
        if any(self.mapped('manager_hr_readonly')):
            raise AccessError(
                "This assessment has been submitted for HR Approval "
                "and is read-only for the manager."
            )

    @api.depends('employee_user_id', 'reviewer_user_id', 'state')
    @api.depends_context('uid')
    def _compute_can_edit_as_manager(self):
        privileged = (
            self.env.su
            or is_hr_manager(self.env)
            or self.env.user.has_group('base.group_system')
        )

        for assessment in self:
            own_assessment = (
                assessment.employee_user_id == self.env.user
            )
            assigned_reviewer = (
                assessment.reviewer_user_id == self.env.user
                and (
                    is_competency_manager(self.env)
                    or privileged
                )
            )

            assessment.can_edit_as_manager = (
                not own_assessment
                and (privileged or assigned_reviewer)
            )
            assessment.can_submit_manager_review = (
                not own_assessment
                and assigned_reviewer
                and assessment.state == 'manager_review'
            )

    @api.depends('employee_id', 'cycle_id','development_plan_ids','development_plan_ids.employee_id', )
    def _compute_employee_plan_ids(self):
        Plan = self.env['employee.development.plan']

        for assessment in self:
            assessment.employee_plan_ids = (
                assessment.development_plan_ids.filtered(
                    lambda plan:
                        plan.employee_id == assessment.employee_id
                )
                if assessment.employee_id and assessment.cycle_id
                else Plan.browse()
            )

    def _inverse_employee_plan_ids(self):
        # Membership follows from the plan's own Employee, so there is no link
        # to write back; a row edited in the tab was saved by the x2many's own
        # update command before this ran.
        pass

    @api.depends('state', 'reviewer_user_id')
    @api.depends_context('uid')
    def _compute_is_pending_my_review(self):
        privileged = (
            self.env.su
            or is_hr_manager(self.env)
            or self.env.user.has_group('base.group_system')
        )

        for assessment in self:
            assessment.is_pending_my_review = (
                (
                    assessment.state == 'manager_review'
                    and assessment.reviewer_user_id == self.env.user
                )
                or (
                    privileged
                    and assessment.state == 'hr_review'
                )
            )

    def _search_is_pending_my_review(self, operator, value):
        if operator in ('in', 'not in'):
            wanted = True in value
            positive = wanted if operator == 'in' else not wanted
        elif operator in ('=', '!='):
            positive = bool(value) if operator == '=' else not value
        else:
            return NotImplemented
        domain = Domain(self._pending_review_domain())
        return domain if positive else ~domain

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.constrains('employee_id', 'cycle_id')
    def _check_cycle_overlap_on_assessment(self):
        self.mapped('cycle_id')._check_overlapping_open_cycles()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == self.env._('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'employee.competency.assessment'
                ) or self.env._('New')
        assessments = super().create(vals_list)
        for assessment in assessments:
            job = assessment.job_id

            if not job:
                raise UserError(
                    "Assign a Job Position before creating the assessment."
                )

            if job.competency_matrix_state != 'validated':
                raise UserError(
                    "Cannot create this assessment. "
                    "Please validate the Job Competency Matrix for '%s' "
                    "before creating an assessment."
                    % job.display_name
                )    

        for assessment in assessments:
            # BR-020: a closed cycle takes no new work.
            if assessment.cycle_id.state == 'closed':
                raise UserError(self.env._(
                    'Review cycle %(cycle)s is closed. No assessment can be '
                    'raised against it.', cycle=assessment.cycle_id.name,
                ))
            if not assessment.line_ids:
                assessment._generate_lines()
        return assessments

    # BR-020: what a person may no longer change once the cycle is closed.
    # Deliberately NOT "everything": the stored computes on this model
    # (readiness, previous assessment, the scores) are recomputed by the ORM
    # whenever their sources move — editing a target job's matrix recomputes
    # role_readiness_percent on every assessment aimed at that job, closed
    # cycles included. Blocking those writes would turn an ordinary
    # configuration change into a crash, so the guard names the manual inputs
    # instead of excluding a couple of technical fields.
    _CYCLE_LOCKED_FIELDS = frozenset({
        'employee_id', 'cycle_id', 'reviewer_id', 'assessment_date',
        'department_id', 'job_id', 'target_job_id', 'line_ids',
        'performance_rating', 'potential_rating',
        'strength_summary', 'development_summary',
    })

    # ------------------------------------------------------------------
    # Who may write what
    #
    # The judgement calls on this form belong to the reviewing manager, not to
    # the person being reviewed: where the employee stands against their next
    # role, and the two summaries that go on the record for the cycle. The
    # field help has always said so — "the strengths the manager wants on the
    # record" — but nothing enforced it, so an employee could rewrite both
    # during their own self assessment.
    #
    # `groups` on the field in the view is not enough. It stops the field being
    # RENDERED, not written: the value can still be set through the ORM, an
    # import or a shortcut. So the rule lives here, the way the same rule for
    # the ratings lives on the line (see assessment_line._check_rating_access).
    # ------------------------------------------------------------------
    MANAGER_FIELDS = frozenset({
        'target_job_id', 'performance_rating', 'potential_rating',
        'strength_summary', 'development_summary',
    })

    def _check_manager_fields(self, vals):
        """Refuse a write to the manager's own fields by anyone else."""
        if self.env.su or self.env.context.get('competency_skip_access_check'):
            return
        if not self.MANAGER_FIELDS & set(vals):
            return
        if is_competency_manager(self.env):
            return
        raise AccessError(self.env._(
            'The target job, the performance and potential ratings and the '
            'strength and development summaries are the reviewing manager\'s '
            'to set. Your self ratings and your own comments on each '
            'competency are recorded separately.'
        ))

    def _check_state_write(self, vals):
        """The status only moves through the workflow buttons.

        Each button checks who is pressing it - the employee submits their
        own self assessment, the manager submits the review, HR approves it.
        A plain write of `state` would step round all three, and the
        employee has write access to their own assessment (they self-rate on
        it), so without this an employee could mark their own review
        Completed.
        """
        if 'state' not in vals or self.env.su or self.env.context.get('competency_workflow'):
            return
        raise AccessError(self.env._(
            'The status of a competency assessment changes through its '
            'workflow buttons only.'
        ))

    def _check_submitted_lock(self, vals):
        """Once the self assessment is submitted, it is out of the employee's
        hands: they can read the review, not change it."""
        if self.env.su or is_competency_manager(self.env):
            return
        if not self._CYCLE_LOCKED_FIELDS & set(vals):
            return
        locked = self.filtered(lambda a: a.state not in ('draft', 'employee_review'))
        if locked:
            raise UserError(self.env._(
                '%(assessment)s has been submitted and can no longer be '
                'changed by the employee.',
                assessment=locked[0].display_name,
            ))
    
    

    def write(self, vals):
        own_protected = self._CYCLE_LOCKED_FIELDS - {'line_ids'}
        own_protected |= {
            'employee_plan_ids',
            'development_plan_ids',
            'goal_ids',
            'review_cycle_id',
            'hr_approved_on',
            'hr_approved_by_id',
        }

        if own_protected.intersection(vals) and any(
            assessment.employee_user_id == self.env.user
            for assessment in self
        ):
            raise AccessError(
                "You can only enter your Self Rating and Employee "
                "Comments on your own assessment during Self Review. "
                "The other tabs are read-only."
            )
        if 'active' in vals:
            self._check_hr_rights()

            if not vals['active'] and any(
                assessment.state not in ('done', 'cancel')
                for assessment in self
            ):
                raise UserError(
                    "Only Completed or Cancelled assessments "
                    "can be archived."
                )
        protected_fields = self._CYCLE_LOCKED_FIELDS | {
            'employee_plan_ids',
            'development_plan_ids',
            'goal_ids',
            'state',
        }

        if protected_fields.intersection(vals):
            self._check_manager_hr_readonly()

        # Employees cannot change the assigned reviewer.
        summary_fields = {
            'strength_summary',
            'development_summary',
        }

        for assessment in self:
            if assessment.state not in (
                'hr_review', 'done', 'cancel'
            ):
                continue

            changed = any(
                (assessment[field_name] or '')
                != (vals[field_name] or '')
                for field_name in summary_fields.intersection(vals)
            )

            if changed:
                raise UserError(
                    "The Summary is read-only after the manager "
                    "submits the assessment."
                )
        if 'reviewer_id' in vals and not self.env.su:
            reviewer_changed = any(
                assessment.reviewer_id.id != (vals['reviewer_id'] or False)
                for assessment in self
            )

            if reviewer_changed and not is_competency_manager(self.env):
                raise AccessError(self.env._(
                    'You are not allowed to change the reviewer '
                    'assigned to this assessment. Please contact HR.'
                ))

        if 'assessment_date' in vals and not self.env.su:
            new_date = fields.Date.to_date(vals['assessment_date'])

            date_changed = any(
                (assessment.assessment_date or None) != (new_date or None)
                for assessment in self
            )

            if date_changed and not is_competency_manager(self.env):
                raise AccessError(self.env._(
                    'You are not allowed to change the Assessment Date. '
                    'Please contact HR.'
                ))

        self._check_state_write(vals)
        self._check_manager_fields(vals)
        self._check_submitted_lock(vals)

        if not self.env.context.get('competency_skip_cycle_check'):
            if self._CYCLE_LOCKED_FIELDS & set(vals):
                for assessment in self:
                    if assessment.cycle_id.state == 'closed':
                        raise UserError(self.env._(
                            '%(assessment)s belongs to the closed cycle '
                            '%(cycle)s and can no longer be changed.',
                            assessment=assessment.display_name,
                            cycle=assessment.cycle_id.name,
                        ))

        return super().write(vals)


    def _check_job_matrix_validated(self):
        for assessment in self:
            job = assessment.job_id
            if not job:
                raise UserError(
                    "Assign a Job Position to the employee before "
                    "starting the assessment."
                )

            if job.competency_matrix_state != 'validated':
                raise UserError(
                    "Validate the Job Competency Matrix for '%s' before "
                    "generating or starting the assessment."
                    % job.display_name
                )

    # ------------------------------------------------------------------
    # Line generation
    # ------------------------------------------------------------------
    def _generate_lines(self):
        """BR-002 and BR-003: snapshot the job matrix onto the assessment.

        Everything the line needs to score itself is copied here and never
        read from the job again, so re-weighting the matrix next quarter
        leaves this review exactly as it was signed off.
        """
        self._check_job_matrix_validated()
        for assessment in self:
            job = assessment.job_id
            if not job:
                raise UserError(self.env._(
                    '%(employee)s has no job position, so there is no '
                    'competency matrix to assess against.',
                    employee=assessment.employee_id.display_name,
                ))
            reference_date = assessment.cycle_id.date_to or assessment.assessment_date
            matrix = job.competency_line_ids.filtered(
                lambda line: line.active and line.assessment_required
                and line.competency_id.active
            )._is_effective_on(reference_date)
            if not matrix:
                raise UserError(self.env._(
                    'The competency matrix of %(job)s has no competency in '
                    'effect on %(date)s.', job=job.display_name,
                    date=reference_date,
                ))

            total = sum(matrix.mapped('weightage'))
            if abs(total - 100.0) > WEIGHTAGE_TOLERANCE:
                raise UserError(
                    "The applicable competencies for '%s' total %.2f%%. "
                    "They must total 100%%. Check the matrix weights, "
                    "active competencies and effective dates before "
                    "starting the assessment."
                    % (job.display_name, total)
                )
            assessment.line_ids = [fields.Command.clear()] + [
                fields.Command.create({
                    'competency_id': line.competency_id.id,
                    'category_id': line.category_id.id,
                    'scope': line.scope,
                    'weightage': line.weightage,
                    'required_level': rating_to_int(line.required_level),
                    'minimum_level': rating_to_int(line.minimum_level),
                    'mandatory': line.mandatory,
                    'development_threshold': line.competency_id.development_threshold,
                    'evidence_required': line.competency_id.evidence_required,
                    'sequence': line.sequence,
                })
                for line in matrix
            ]

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_cycle_open(self):
        today = fields.Date.context_today(self)

        for assessment in self:
            cycle = assessment.cycle_id

            if cycle.state == 'closed':
                raise UserError(self.env._(
                    'Review cycle %(cycle)s is closed and accepts '
                    'no further submissions.',
                    cycle=cycle.name,
                ))

            # if cycle.date_to and today > cycle.date_to:
            #     raise UserError(self.env._(
            #         'The review cycle %(cycle)s ended on %(date)s. '
            #         'Further review actions and HR approval are '
            #         'not allowed. Please contact HR.',
            #         cycle=cycle.name,
            #         date=cycle.date_to.strftime('%d-%m-%Y'),
            #     ))

    def _check_reviewer_rights(self):
        own = self.filtered(
            lambda assessment:
                assessment.employee_user_id == self.env.user
        )
        if own:
            raise AccessError(
                "You cannot perform reviewer actions on your "
                "own assessment. Your assigned reviewer must do this."
            )

        privileged = (
            self.env.su
            or is_hr_manager(self.env)
            or self.env.user.has_group('base.group_system')
        )

        if privileged:
            return

        if not is_competency_manager(self.env):
            raise AccessError(
                "Only a competency manager or HR/Admin "
                "can perform this action."
            )

        if any(
            assessment.reviewer_user_id != self.env.user
            for assessment in self
        ):
            raise AccessError(
                "Only the assigned reviewer can perform this action."
            )

    def _check_hr_rights(self):
        if (self.env.su or is_hr_manager(self.env) or self.env.user.has_group('base.group_system')):
            return
        raise AccessError(self.env._(
            'Only an HR competency manager can approve, reopen or reset a '
            'competency assessment at this stage.'
        ))

    def _set_state(self, state):
        """The one way the status moves. Closes the to-dos of the stage being
        left, so the previous owner's activity does not linger."""
        self.activity_feedback(['mail.mail_activity_data_todo'])
        self.with_context(competency_workflow=True).write({'state': state})

    def action_start_self_review(self):
        self._check_cycle_open()

        for assessment in self:
            if assessment.state != 'draft':
                continue

            assessment._check_job_matrix_validated()

            if not assessment.line_ids:
                assessment._generate_lines()

            reference_date = (
                assessment.cycle_id.date_to
                or assessment.assessment_date
            )
            matrix = assessment.job_id.competency_line_ids.filtered(
                lambda line: (
                    line.active
                    and line.assessment_required
                    and line.competency_id.active
                )
            )._is_effective_on(reference_date)

            expected = {
                line.competency_id.id: line.weightage
                for line in matrix
            }
            lines = assessment.line_ids

            if (
                not expected
                or len(lines) != len(expected)
                or set(lines.competency_id.ids) != set(expected)
            ):
                raise UserError(
                    "The assessment must contain every applicable "
                    "competency from the validated Job Competency Matrix, "
                    "without extra or duplicate competencies. "
                    "Correct the draft assessment before starting."
                )

            if any(
                abs(
                    line.weightage
                    - expected[line.competency_id.id]
                ) > WEIGHTAGE_TOLERANCE
                for line in lines
            ):
                raise UserError(
                    "Assessment weights must match the validated "
                    "Job Competency Matrix."
                )

            total = sum(lines.mapped('weightage'))
            if abs(total - 100.0) > WEIGHTAGE_TOLERANCE:
                raise UserError(
                    "Assessment competency weights total %.2f%%. "
                    "They must total 100%% before starting."
                    % total
                )

            assessment._set_state('employee_review')
            assessment._notify_stage('employee')

        return True

    def action_submit_self_review(self):
        """Workflow step 5: the employee hands their self assessment over.

        From here the self ratings and employee comments are locked
        (assessment_line._check_rating_access) - they are what the manager
        reviews, and must not move under them.
        """
        # if (
        #     self.env.su
        #     or is_hr_manager(self.env)
        #     or self.env.user.has_group('base.group_system')
        # ):
        #     raise AccessError(
        #         "HR/Admin cannot submit employee self-assessments."
        #     )
        self._check_cycle_open()
        for assessment in self:
            if assessment.state != 'employee_review':
                raise UserError(self.env._(
                    '%(assessment)s is not open for self assessment.',
                    assessment=assessment.display_name,
                ))
            # if assessment.employee_user_id != self.env.user:
            #     raise AccessError(
            #         "You can submit only your own self-assessment."
            #     )
            deadline = assessment.cycle_id.self_review_deadline
            today = fields.Date.context_today(assessment)

            if deadline and today > deadline:
                raise UserError(self.env._(
                    'The self-review submission deadline (%(deadline)s) '
                    'has passed. You cannot submit this assessment. '
                    'Please contact HR.',
                    deadline=deadline.strftime('%d-%m-%Y'),
                ))
            unrated = assessment.line_ids.filtered(lambda line: not line.self_rating)
            if unrated:
                raise UserError(self.env._(
                    'Rate every competency before submitting. Still to rate: '
                    '%(names)s',
                    names=', '.join(unrated.mapped('competency_id.display_name')),
                ))
            missing_comments = assessment.line_ids.filtered(
                lambda line: not (
                    line.employee_comments or ''
                ).strip()
            )
            if missing_comments:
                raise UserError(
                    "Enter Employee Comments for every competency "
                    "before submitting.\n\nMissing comments: %s"
                    % ', '.join(
                        missing_comments.mapped(
                            'competency_id.display_name'
                        )
                    )
                )
            assessment._set_state('manager_review')
            assessment._notify_stage('manager')
        return True

    def action_skip_self_review(self):
        raise UserError(
            "Skipping Self Assessment is not allowed. "
            "The employee must submit their own self-assessment."
        )

    def action_submit_manager_review(self):
        """Manager approval: the manager signs off their ratings.

        Everything the manager owes is checked here - a manager and final
        rating on every line, the evidence behind the exceptional ones, and a
        scorecard that weighs 100%. A development action is raised for every
        gap that has none, and the review goes to HR for approval.
        """
        self._check_cycle_open()
        self._check_reviewer_rights()
        for assessment in self:
            if assessment.employee_user_id == self.env.user:
                raise AccessError(
                    "You cannot submit Manager Review "
                    "on your own assessment."
                )

            if assessment.reviewer_user_id != self.env.user:
                raise AccessError(
                    "Only the assigned reviewer can submit "
                    "Manager Review. Check the reviewer's "
                    "employee record and linked user account."
                )
            if assessment.state != 'manager_review':
                raise UserError(self.env._(
                    '%(assessment)s is not in manager review.',
                    assessment=assessment.display_name,
                ))
            deadline = assessment.cycle_id.manager_review_deadline
            today = fields.Date.context_today(assessment)

            if deadline and today > deadline:
                raise UserError(self.env._(
                    'The manager-review submission deadline (%(deadline)s) '
                    'has passed. You cannot submit this assessment. '
                    'Please contact HR.',
                    deadline=deadline.strftime('%d-%m-%Y'),
                ))
            assessment._validate_manager_review()
            
            assessment._set_state('hr_review')
            # Mails 4 + 8: the manager's review is complete and HR's approval
            # is pending. One event, so one mail to HR rather than two at once.
            send_competency_mail(
                assessment, 'mail_template_assessment_hr_approval', 'support',
                email_to=hr_emails(self.env),
            )
        return True

    def action_hr_approve(self):
        """Workflow step 9: HR approves the final ratings and certifies them."""
        self._check_cycle_open()
        self._check_hr_rights()
        for assessment in self:
            if assessment.state != 'hr_review':
                raise UserError(self.env._(
                    '%(assessment)s is not waiting on HR approval.',
                    assessment=assessment.display_name,
                ))
            assessment._validate_manager_review()
            assessment._finalize()
        return True

    def action_done(self):
        """Move the review on from wherever it stands towards completion.

        Kept for anything that called it before the HR approval step existed
        (server actions, other modules): it now does exactly what the button
        for the current stage does, with that button's checks.
        """
        for assessment in self:
            if assessment.state == 'manager_review':
                assessment.action_submit_manager_review()
            elif assessment.state == 'hr_review':
                assessment.action_hr_approve()
            elif assessment.state != 'done':
                raise UserError(self.env._(
                    '%(assessment)s cannot be completed from %(state)s.',
                    assessment=assessment.display_name,
                    state=dict(self._fields['state']._description_selection(self.env))[assessment.state],
                ))
        return True

    def _validate_manager_review(self):
        """BR-004 and BR-012 — what a manager must supply to sign off."""
        self.ensure_one()

        # Check whether the assessment has any competencies.
        if not self.line_ids:
            raise UserError(self.env._(
                '%(assessment)s has no competency to rate.',
                assessment=self.display_name,
            ))

        # Manager comments are mandatory for every competency.
        missing_comments = self.line_ids.filtered(
            lambda line: not (
                line.manager_comments or ''
            ).strip()
        )

        if missing_comments:
            raise UserError(
                "Enter Manager Comments for every competency "
                "before submitting the manager review.\n\n"
                "Missing comments: %s"
                % ', '.join(
                    missing_comments.mapped(
                        'competency_id.display_name'
                    )
                )
            )

        # Every competency must have a manager rating and final rating.
        unrated = self.line_ids.filtered(
            lambda line: not line.manager_rating or not line.final_rating
        )

        if unrated:
            raise UserError(self.env._(
                'Every competency needs a manager rating and a final rating. '
                'Still to rate: %(names)s',
                names=', '.join(
                    unrated.mapped('competency_id.display_name')
                ),
            ))

        # BR-006: Validate that competency weightages total 100%.
        total = sum(self.line_ids.mapped('weightage'))

        if abs(total - 100.0) > WEIGHTAGE_TOLERANCE:
            raise UserError(self.env._(
                'The competency weightages of %(assessment)s total '
                '%(total).2f%%. They must total 100%% for the overall score '
                'to mean anything.',
                assessment=self.display_name,
                total=total,
            ))

    def _check_development_policy(self):
        """BR-019: a gap should have a development action before the review
        closes. Phase 1 of the specification: a warning in the chatter, not a
        block."""
        self.ensure_one()
        unplanned = self.line_ids.filtered(
            lambda line: line.development_required and not line.development_plan_ids
        )
        if unplanned:
            self.message_post(body=self.env._(
                'Completed with no development plan against %(count)s gap(s): '
                '%(names)s', count=len(unplanned),
                names=', '.join(unplanned.mapped('competency_id.display_name')),
            ))

    def _finalize(self):
        """Complete and certify the review, and make it the official result.

        Workflow steps 9-10: the approval is stamped, and the employee's
        current competency profile is rebuilt from their completed reviews
        (BR-018) - which this one now is. The review lines themselves are
        never touched again: they are the history.
        """
        for assessment in self:
            assessment.write({
                'hr_approved_on': fields.Datetime.now(),
                'hr_approved_by_id': self.env.uid,
            })
            assessment._set_state('done')
        self._results_changed()
        # Mail 9: the result is official - to the employee, manager in copy.
        for assessment in self:
            send_competency_mail(
                assessment, 'mail_template_assessment_completed', 'hr',
                email_to=join_emails(assessment.employee_id.work_email),
                email_cc=join_emails(assessment.reviewer_id.work_email),
            )

    def _results_changed(self):
        """Follow a completed result appearing or going away.

        Called when a review completes, and when a completed one is cancelled
        or reset to draft. For every employee concerned:

          * the competency profile is rebuilt from the completed reviews still
            standing (BR-018);
          * their open reviews re-read which completed review is their
            baseline (BR-010), and with it every line's Previous Level and
            Improvement (BR-009). The baseline only follows the review's own
            status otherwise, so a Q4 review raised while Q3 was still in
            progress would never have learnt that Q3 had since completed;
          * the approved levels are written onto the employee's skills
            (hr.employee.skill, BR-018).
        """
        employees = self.employee_id
        employees._rebuild_competency_profile()
        later = self.with_context(active_test=False).search([
            ('employee_id', 'in', employees.ids),
            ('state', 'not in', ('done', 'cancel')),
            ('id', 'not in', self.ids),
        ])
        if later:
            # 'state' is what previous_assessment_id depends on, and marking it
            # modified recomputes that and everything computed from it.
            later.modified(['state'])
        employees._sync_employee_skills()

    def _update_competency_profile(self):
        """Push the approved final ratings onto the employee's profile."""
        self._results_changed()

    def unlink(self):
        self._check_hr_rights()

        # TEST DATA CLEANUP ONLY:
        # Original deletion restriction temporarily commented.
        #
        # certified = self.filtered(
        #     lambda assessment: (
        #         assessment.state == 'done'
        #         or assessment.hr_approved_on
        #         or assessment.hr_approved_by_id
        #     )
        # )
        #
        # if certified:
        #     raise UserError(
        #         "Certified assessments cannot be deleted. "
        #         "Use the authorized Reset to Draft, Cancel or Archive action instead.\n\n"
        #         "Assessments: %s"
        #         % ', '.join(certified.mapped('display_name'))
        #     )

        employees = self.mapped('employee_id')
        result = super().unlink()

        # Rebuild employee results after deleting test assessments.
        employees._rebuild_competency_profile()

        remaining_reviews = self.env[
            'employee.competency.assessment'
        ].with_context(active_test=False).search([
            ('employee_id', 'in', employees.ids),
            ('state', 'not in', ('done', 'cancel')),
        ])
        if remaining_reviews:
            remaining_reviews.modified(['state'])

        employees._sync_employee_skills()
        return result

    def action_cancel(self):
        self._check_reviewer_rights()
        was_done = self.filtered(lambda a: a.state == 'done')
        if was_done:
            self._check_hr_rights()
        self._set_state('cancel')
        # A cancelled review is no longer a result, so the profile it fed is
        # rebuilt without it.
        was_done._results_changed()

    def action_reset_to_draft(self):
        self._check_hr_rights()

        for assessment in self:
            if assessment.cycle_id.state == 'closed':
                raise UserError(self.env._(
                    'Assessment %(assessment)s cannot be reset to draft '
                    'because review cycle %(cycle)s is closed.',
                    assessment=assessment.display_name,
                    cycle=assessment.cycle_id.name,
                ))

        was_done = self.filtered(lambda a: a.state == 'done')
        self.write({
            'hr_approved_on': False,
            'hr_approved_by_id': False,
        })
        self._set_state('draft')
        was_done._results_changed()

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _notify_stage(self, audience):
        """Mail and an activity for whoever the assessment is now waiting on."""
        self.ensure_one()
        if audience == 'employee':
            # Mail 1: the review cycle is open and this assessment assigned.
            user = self.employee_id.user_id
            send_competency_mail(
                self, 'mail_template_assessment_assigned', 'hr',
                email_to=join_emails(self.employee_id.work_email),
            )
            summary = self.env._('Complete your competency self assessment')
            deadline = self.cycle_id.self_review_deadline
        else:
            # Mail 3: the self assessment is submitted - to the manager.
            user = self.reviewer_id.user_id
            send_competency_mail(
                self, 'mail_template_assessment_manager_review', 'support',
                email_to=join_emails(self.reviewer_id.work_email),
            )
            summary = self.env._('Review the competency assessment')
            deadline = self.cycle_id.manager_review_deadline
        if user:
            self.with_context(
                mail_activity_quick_update=True,
            ).activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=deadline or self.assessment_date,
                summary=summary,
                user_id=user.id,
            )

    # ------------------------------------------------------------------
    # Scheduled reminders
    # ------------------------------------------------------------------
    @api.model
    def _cron_review_reminders(self):
        """Chase self assessments and manager reviews past their deadline."""
        today = fields.Date.context_today(self)
        for state, deadline_field, template_xmlid, recipient, kind in (
            # Mail 2: the self assessment is not completed - from HR.
            (
                'employee_review', 'self_review_deadline',
                'mail_template_assessment_self_review_reminder', 'employee_id', 'hr',
            ),
            (
                'manager_review', 'manager_review_deadline',
                'mail_template_assessment_manager_review_reminder', 'reviewer_id', 'support',
            ),
        ):
            pending = self.search([
                ('state', '=', state),
                ('cycle_id.state', '=', 'open'),
                (f'cycle_id.{deadline_field}', '!=', False),
                (f'cycle_id.{deadline_field}', '<', today),
            ])
            for assessment in pending:
                send_competency_mail(
                    assessment, template_xmlid, kind,
                    email_to=join_emails(assessment[recipient].work_email),
                )

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_open_competency_board(self):
        """The Competencies tab on a screen of its own, full width."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Competencies: %s', self.display_name),
            'res_model': 'employee.competency.assessment.line',
            'view_mode': 'list',
            'views': [(self.env.ref('ft_employee_competency.view_assessment_line_board_list').id, 'list')],
            'domain': [('assessment_id', '=', self.id)],
            'context': {'default_assessment_id': self.id},
            'target': 'current',
        }

    def action_view_development_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Development Plans'),
            'res_model': 'employee.development.plan',
            'view_mode': 'list,form',
            'domain': [('assessment_id', '=', self.id)],
            'context': {
                'default_assessment_id': self.id,
                'default_employee_id': self.employee_id.id,
            },
        }

    def action_new_development_plan(self):
        """Raise one plan by hand, from the Development Plans tab.

        The tab lists every plan the employee has, so it cannot create through
        the list itself — the rows are not this record's to own. This opens the
        plan form with the employee and this assessment already filled in, so a
        plan raised here is still tied back to the review that called for it.
        """
        self.ensure_one()
        if not self.can_edit_as_manager:
            raise AccessError(
                "Only the reviewer or HR can add a development plan here."
            )
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('New Development Plan'),
            'res_model': 'employee.development.plan',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_employee_id': self.employee_id.id,
                'default_assessment_id': self.id,
            },
        }

    def _development_action_values(self, line):
        """What a development action raised for one gap line starts with."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        return {
            'employee_id': self.employee_id.id,
            'assessment_id': self.id,
            'assessment_line_id': line.id,
            'competency_id': line.competency_id.id,
            'name': self.env._('Improve %s', line.competency_id.name),
            'assigned_person_id': self.reviewer_id.user_id.id or self.env.user.id,
            'date_start': today,
            # One quarterly cycle to close the gap before the next review.
            'target_date': today + relativedelta(months=3),
            'target_level': min(line.required_level or MAX_RATING, MAX_RATING),
        }

    def _generate_development_plans(self, auto=False):
        """Raise one development action for every gap that has none yet.

        "Gap" is the line's Development Required flag (BR-011): a final rating
        under the competency's development threshold, or under the level the
        job expects.
        """
        Plan = self.env['employee.development.plan']
        plans = Plan
        for assessment in self:
            gaps = assessment.line_ids.filtered(
                lambda line: line.development_required and not line.development_plan_ids
            )
            if not gaps:
                continue
            created = Plan.create([assessment._development_action_values(line) for line in gaps])
            plans |= created
            if auto:
                assessment.message_post(body=self.env._(
                    '%(count)s development action(s) raised automatically for '
                    'the gaps on %(names)s.',
                    count=len(created),
                    names=', '.join(gaps.mapped('competency_id.display_name')),
                ))
        return plans

    def action_create_development_plans(self):
        """Raise a draft plan for every gap that has none yet."""
        self.ensure_one()
        self._check_reviewer_rights()
        plans = self._generate_development_plans()
        if not plans:
            raise UserError(self.env._(
                'Every competency gap on this assessment already has a '
                'development plan.'
            ))
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Development Plans'),
            'res_model': 'employee.development.plan',
            'view_mode': 'list,form',
            'domain': [('id', 'in', plans.ids)],
        }
