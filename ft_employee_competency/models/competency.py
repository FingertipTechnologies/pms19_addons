from odoo import api, fields, models
from odoo.fields import Command
from odoo.exceptions import ValidationError

from .competency_utils import MAX_RATING, SCOPE_SELECTION


class EmployeeCompetency(models.Model):
    """One competency parameter — Ownership, Communication, Apex, ...

    This is master data: it says what the competency is and how to judge it,
    not what any particular job or employee needs. The job matrix
    (``employee.job.competency.line``) sets the required level and weightage
    per job, and an assessment line snapshots both.
    """

    _name = 'employee.competency'
    _description = 'Employee Competency'
    _order = 'category_id, sequence, name'

    name = fields.Char(string='Competency Name', required=True, translate=True)
    code = fields.Char(
        string='Competency Code', required=True,
        help='Unique readable code such as ATT-001 or COM-001. Used when '
             'importing job matrices from a spreadsheet.',
    )
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one(
        'employee.competency.category', string='Competency Category',
        required=True, ondelete='restrict', index=True,
    )
    scope = fields.Selection(
        selection=SCOPE_SELECTION, string='Scope',
        compute='_compute_scope', store=True, readonly=False, required=True,
        precompute=True,
        help='Which headline score this competency contributes to. Defaults '
             'to the category scope and can be overridden per competency.',
    )
    description = fields.Text(
        help='What the competency means, in the words the business uses.',
    )
    evaluation_guideline = fields.Html(
        string='Evaluation Guidelines',
        help='What evidence a reviewer should look for, ideally with a '
             'behaviour example for each of the five ratings.',
    )
    default_weightage = fields.Float(
        string='Default Weightage', digits=(5, 2), default=0.0,
        help='Weightage suggested when this competency is added to a job '
             'matrix. The job matrix line may override it.',
    )
    is_company_wide = fields.Boolean(
        string='Company-wide',
        help='Marks a competency expected of every job, such as Attitude. '
             'Company-wide competencies can be added to a job matrix in one '
             'click from the job form.',
    )
    evidence_required = fields.Boolean(
        string='Evidence Required', default=True,
        help='Requires the manager to record evidence or a comment before an '
             'assessment carrying this competency can be submitted.',
    )
    development_threshold = fields.Integer(
        string='Development Threshold', default=3,
        help='A final rating below this level flags the competency as needing '
             'a development action, even when it meets the job requirement.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company, index=True,
    )
    active = fields.Boolean(
        default=True,
        help='Archived competencies keep their history but are not offered '
             'for new job matrix lines or generated onto new assessments.',
    )

    job_line_ids = fields.One2many(
        'employee.job.competency.line', 'competency_id', string='Job Matrix Lines',
    )
    hr_skill_id = fields.Many2one(
        'hr.skill', string='Employee Skill', readonly=True, copy=False,
        ondelete='set null',
        help='The skill on the employee Skills tab that this competency\'s '
             'approved level is written to when a review completes (BR-018).',
    )

    # Specification names (hr.skill in the workbook). The workbook's names are
    # what imports, exports and integrations written against it will use, so
    # they resolve here too; the short names stay the ones the module is
    # written in.
    competency_code = fields.Char(related='code', readonly=False, string='Competency Code (spec)')
    competency_scope = fields.Selection(related='scope', readonly=False, string='Competency Scope (spec)')

    _code_company_uniq = models.Constraint(
        'unique(code, company_id)',
        'A competency with this code already exists in this company.',
    )
    _threshold_in_range = models.Constraint(
        f'CHECK(development_threshold BETWEEN 1 AND {MAX_RATING})',
        f'The development threshold must be a rating between 1 and {MAX_RATING}.',
    )
    _default_weightage_positive = models.Constraint(
        'CHECK(default_weightage >= 0)',
        'The default weightage cannot be negative.',
    )

    @api.constrains('name', 'company_id')
    def _check_unique_competency_name(self):
        for competency in self:
            normalized_name = ' '.join(
                (competency.name or '').split()
            ).casefold()

            if not normalized_name:
                continue

            other_competencies = self.sudo().with_context(
                active_test=False
            ).search([
                ('id', '!=', competency.id),
                ('company_id', '=', competency.company_id.id or False),
            ])

            for other in other_competencies:
                other_name = ' '.join(
                    (other.name or '').split()
                ).casefold()

                if normalized_name == other_name:
                    raise ValidationError(self.env._(
                        'A competency with this name already exists '
                        'in this company. Capitalization and extra '
                        'spaces do not make a name unique.'
                    ))

    @api.depends('category_id')
    def _compute_scope(self):
        for competency in self:
            competency.scope = competency.category_id.scope or 'core'

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for competency in self:
            competency.display_name = (
                f'[{competency.code}] {competency.name}'
                if competency.code else competency.name
            )

    # ------------------------------------------------------------------
    # BR-018: the employee's skills (hr.employee.skill)
    #
    # hr.employee.skill needs an hr.skill, which belongs to an hr.skill.type,
    # and a level that belongs to that same type - Odoo keeps a separate level
    # list per skill type. So each category gets a skill type carrying the
    # 1-5 levels of the rating scale, and each competency a skill inside it.
    # Both are created the first time a completed review needs them and kept
    # on the category and competency, so they are found again rather than
    # matched by name: a database's existing resume skills (Languages, Soft
    # Skills, ...) are never touched or mistaken for these.
    # ------------------------------------------------------------------
    def _hr_skill_level_values(self):
        """The rating scale as hr.skill.level values."""
        levels = self.env['employee.competency.level'].sudo().search([])
        if levels:
            return [{'name': level.display_name, 'level_progress': level.progress} for level in levels]
        return [
            {'name': str(rating), 'level_progress': round(rating * 100 / MAX_RATING)}
            for rating in range(1, MAX_RATING + 1)
        ]

    def _ensure_hr_skill(self):
        """Return this competency's hr.skill, creating it (and its category's
        skill type, with the rating levels) on first use."""
        self.ensure_one()
        competency = self.sudo()
        if competency.hr_skill_id:
            return competency.hr_skill_id
        category = competency.category_id
        if category.hr_skill_type_id:
            skill = self.env['hr.skill'].sudo().create({
                'name': competency.name,
                'skill_type_id': category.hr_skill_type_id.id,
            })
        else:
            # One create: hr.skill.type refuses to exist without at least one
            # skill and one level.
            skill_type = self.env['hr.skill.type'].sudo().create({
                'name': category.name,
                'skill_level_ids': [Command.create(vals) for vals in self._hr_skill_level_values()],
                'skill_ids': [Command.create({'name': competency.name})],
            })
            category.hr_skill_type_id = skill_type
            skill = skill_type.skill_ids
        competency.hr_skill_id = skill
        return skill

    def _hr_skill_level(self, skill, rating):
        """The hr.skill.level of ``skill``'s type standing for ``rating``,
        matched on progress - the one property the two scales share."""
        level = self.env['employee.competency.level'].sudo()._for_rating(rating)
        progress = level.progress if level else round(rating * 100 / MAX_RATING)
        skill_type = skill.skill_type_id
        match = skill_type.skill_level_ids.filtered(lambda l: l.level_progress == progress)[:1]
        if not match:
            match = self.env['hr.skill.level'].sudo().create({
                'name': level.display_name if level else str(rating),
                'level_progress': progress,
                'skill_type_id': skill_type.id,
            })
        return match

