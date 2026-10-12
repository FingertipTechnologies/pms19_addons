from collections import defaultdict

from odoo import api, fields, models
from odoo.fields import Command

from .competency_utils import READINESS_SELECTION, readiness_of

# Every STORED field added to hr.employee here has to carry this group.
#
# hr.employee.public is a fixed, whitelisted SQL view of the employee, and a
# user without hr.employee read access is served from it. When such a user
# reads any employee, hr.employee.fetch() is called with no field list, and
# _determine_fields_to_fetch() then expands that to "every stored field the
# user is allowed to read" - our fields included, because a field with no
# `groups` is readable by everyone. Those names are not columns of
# hr.employee.public, so _check_private_fields() raises
#
#     AccessError: The fields "..." which you are trying to read, are not
#     available for employee public profiles.
#
# and it raises on EVERY hr.employee read anywhere in the system, not just on
# a competency screen - which is how eight fields on this model took the whole
# PMS home page down.
#
# Naming a group the public-profile users do not have keeps the fields out of
# that prefetch entirely, and hr.group_hr_user is the right one: it is exactly
# the group that ir.model.access grants hr.employee read to, so anyone allowed
# to read these fields is served from hr.employee directly and never reaches
# the public path. This is Odoo's own documented rule - see the note on the
# HrEmployee class in addons/hr/models/hr_employee.py.
#
# Only stored fields are affected. Fields.prefetch is forced to False for
# anything non-stored, so the one2many fields below are
# never pulled into that prefetch and need no group.
HR_ONLY = 'hr.group_hr_user'


class HrEmployee(models.Model):
    """The employee, extended with their competency standing.

    Everything here is a roll-up of the latest COMPLETED assessment. Nothing
    an employee sees on their form is entered here — it is the result of the
    review, so it moves when a review completes and not before.
    """

    _inherit = 'hr.employee'

    target_job_id = fields.Many2one(
        'hr.job', string='Target Job', groups=HR_ONLY,
        help='The role this employee is being grown towards. Readiness is '
             'measured against its competency matrix.',
    )
    competency_profile_ids = fields.One2many(
        'employee.competency.profile', 'employee_id', string='Competencies',
    )
    competency_assessment_ids = fields.One2many(
        'employee.competency.assessment',
        'employee_id',
        string='Assessments',
        context={'active_test': False},
    )
    development_plan_ids = fields.One2many(
        'employee.development.plan', 'employee_id', string='Development Plans',
    )
    latest_assessment_id = fields.Many2one(
        'employee.competency.assessment', string='Latest Assessment',
        compute='_compute_competency_standing', store=True, groups=HR_ONLY,
    )
    last_assessment_date = fields.Date(
        string='Last Assessment Date',
        compute='_compute_competency_standing', store=True, groups=HR_ONLY,
    )
    resource_strength_score = fields.Float(
        string='Resource Strength / 5', digits=(3, 2),
        compute='_compute_competency_standing', store=True, groups=HR_ONLY,
        help='Overall score of the latest completed assessment.',
    )
    previous_strength_score = fields.Float(
        string='Previous Strength / 5', digits=(3, 2),
        compute='_compute_competency_standing', store=True, groups=HR_ONLY,
    )
    competency_improvement_score = fields.Float(
        string='Improvement', digits=(3, 2),
        compute='_compute_competency_standing', store=True, groups=HR_ONLY,
        help='Latest score minus the score before it. Positive means the '
             'employee improved quarter on quarter.',
    )
    # Readiness is measured LIVE, against the target job as it stands on the
    # employee now, using their latest approved levels (the profile). Taking
    # it from the latest assessment instead froze it at whatever target that
    # review happened to carry: set a new target job on the employee and the
    # form went on reporting readiness for the old one until the next review.
    role_readiness_percent = fields.Float(
        string='Role Readiness %', digits=(5, 2),
        compute='_compute_readiness', store=True, groups=HR_ONLY,
        help='Share of the mandatory competencies of the target job the '
             'employee meets on their latest approved levels.',
    )
    readiness_status = fields.Selection(
        selection=READINESS_SELECTION, string='Readiness Status',
        compute='_compute_readiness', store=True, groups=HR_ONLY,
    )

    @api.depends(
        'competency_assessment_ids.state',
        'competency_assessment_ids.assessment_date',
        'competency_assessment_ids.overall_score',
        'competency_assessment_ids.previous_overall_score',
        'competency_assessment_ids.improvement_score',
    )
    def _compute_competency_standing(self):
        for employee in self:
            latest = employee.competency_assessment_ids.filtered(
                lambda assessment: assessment.state == 'done'
            ).sorted(key=lambda a: (a.assessment_date, a.id), reverse=True)[:1]
            employee.latest_assessment_id = latest
            employee.last_assessment_date = latest.assessment_date
            employee.resource_strength_score = latest.overall_score
            employee.previous_strength_score = latest.previous_overall_score
            employee.competency_improvement_score = latest.improvement_score

    def _reached_levels(self):
        self.ensure_one()
        return {
            entry.competency_id.id: entry.current_level
            for entry in self.competency_profile_ids
        }

    def _target_mandatory_lines(self):
        self.ensure_one()
        return self.target_job_id.competency_line_ids.filtered(
            lambda line: line.mandatory and line.active
        )

    @api.depends(
        'target_job_id',
        'target_job_id.competency_line_ids.required_level',
        'target_job_id.competency_line_ids.mandatory',
        'target_job_id.competency_line_ids.active',
        'competency_profile_ids.current_level',
    )
    def _compute_readiness(self):
        # BR-016 / BR-017. No target job, nothing to be ready for: blank.
        for employee in self:
            percent, band = readiness_of(
                employee._target_mandatory_lines(), employee._reached_levels(),
            )
            employee.role_readiness_percent = percent
            employee.readiness_status = band

    def _rebuild_competency_profile(self):
        """Rewrite the current competency profile from completed reviews.

        BR-018, done as a rebuild rather than an update: for every competency
        the employee's completed reviews have rated, the latest approved level
        becomes the current one and the one before it the previous one. The
        same call serves completing a review and taking one back - a review
        reset to draft or cancelled after completion stops counting, and the
        profile falls back to what the reviews still standing say. A
        competency no completed review rates any more leaves the profile.
        """
        Profile = self.env['employee.competency.profile'].sudo()
        Line = self.env['employee.competency.assessment.line'].sudo()
        for employee in self:
            lines = Line.search(
                [
                    ('employee_id', '=', employee.id),
                    ('assessment_id.state', '=', 'done'),
                    ('final_rating', '>', 0),
                ],
                order='assessment_date, assessment_id, id',
            )
            history = defaultdict(list)
            for line in lines:
                history[line.competency_id.id].append(line)
            existing = {
                entry.competency_id.id: entry
                for entry in Profile.search([('employee_id', '=', employee.id)])
            }
            to_create = []
            for competency_id, rated in history.items():
                latest = rated[-1]
                values = {
                    'current_level': latest.final_rating,
                    'previous_level': rated[-2].final_rating if len(rated) > 1 else 0,
                    'last_assessment_id': latest.assessment_id.id,
                    'last_assessment_date': latest.assessment_date,
                }
                entry = existing.pop(competency_id, None)
                if entry:
                    entry.write(values)
                else:
                    to_create.append(dict(values, employee_id=employee.id, competency_id=competency_id))
            if to_create:
                Profile.create(to_create)
            if existing:
                Profile.browse([entry.id for entry in existing.values()]).unlink()

    def action_view_competency_assessments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Assessments: %s', self.name),
            'res_model': 'employee.competency.assessment',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def action_view_development_plans(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Development Plans: %s', self.name),
            'res_model': 'employee.development.plan',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }

    def _sync_employee_skills(self):
        """BR-018: write the approved competency levels onto the employee's
        skills (hr.employee.skill).

        Driven by the competency profile, which is rebuilt from completed
        reviews only - so a draft, in-progress or cancelled review never
        reaches the Skills tab, the level written is always the FINAL approved
        rating (never the self rating), and a review completed out of order
        cannot overwrite a later result.

        A skill already on the employee is updated, not duplicated: the new
        level goes through hr.employee's own skill handling, which archives
        the previous level (kept as the skill's history) and leaves one current
        line per skill. A skill already at the approved level is left alone.
        """
        today = fields.Date.context_today(self)
        for employee in self.sudo():
            current = employee.employee_skill_ids.filtered(
                lambda s: not s.valid_to or s.valid_to >= today
            )
            commands = []
            for entry in employee.competency_profile_ids.filtered('current_level'):
                competency = entry.competency_id
                skill = competency._ensure_hr_skill()
                level = competency._hr_skill_level(skill, entry.current_level)
                existing = current.filtered(lambda s, sk=skill: s.skill_id == sk)[:1]
                if existing.skill_level_id == level:
                    continue
                commands.append(Command.create({
                    'skill_id': skill.id,
                    'skill_level_id': level.id,
                    'skill_type_id': skill.skill_type_id.id,
                }))
            if commands:
                employee.write({'employee_skill_ids': commands})

