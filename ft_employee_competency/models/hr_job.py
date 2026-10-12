from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from .competency_utils import WEIGHTAGE_TOLERANCE


class HrJob(models.Model):
    """The job position, extended with its competency matrix."""

    _inherit = 'hr.job'

    competency_line_ids = fields.One2many(
        'employee.job.competency.line', 'job_id', string='Competency Matrix',
        copy=True,
    )
    competency_matrix_notes = fields.Text(
        string='Matrix Notes',
    )
    competency_weightage_total = fields.Float(
        string='Total Weightage %', digits=(5, 2),
        compute='_compute_competency_weightage_total', store=True,
        help='Sum of the weightages of the assessed competencies. Must reach '
             '100% before the matrix can be validated.',
    )
    competency_matrix_state = fields.Selection(
        selection=[('draft', 'Draft'), ('validated', 'Validated')],
        string='Matrix Status', default='draft', required=True, copy=False,
        help='Assessments can only be generated from a validated matrix, and '
             'a matrix only validates at exactly 100%.',
    )

    @api.depends(
        'competency_line_ids.weightage',
        'competency_line_ids.assessment_required',
        'competency_line_ids.active',
    )
    def _compute_competency_weightage_total(self):
        for job in self:
            assessed = job.competency_line_ids.filtered('assessment_required')
            job.competency_weightage_total = sum(assessed.mapped('weightage'))

    def _check_competency_weightage_ceiling(self):
        """Refuse a matrix whose assessed weightages pass 100%."""
        for job in self:
            assessed = job.competency_line_ids.filtered('assessment_required')
            total = sum(assessed.mapped('weightage'))
            if total > 100.0 + WEIGHTAGE_TOLERANCE:
                raise ValidationError(self.env._(
                    'The competency weightages of %(job)s total %(total).2f%%. '
                    'They cannot pass 100%%.',
                    job=job.display_name, total=total,
                ))
            if job.competency_matrix_state == 'validated' and abs(total - 100.0) > WEIGHTAGE_TOLERANCE:
                raise ValidationError(self.env._(
                    'The competency matrix of %(job)s is validated, so its '
                    'weightages must stay at 100%%. They now total '
                    '%(total).2f%%. Reset the matrix to draft to change it.',
                    job=job.display_name, total=total,
                ))

    def action_validate_competency_matrix(self):
        """BR-001: activate the matrix, which requires it to total 100%."""
        for job in self:
            archived_lines = job.competency_line_ids.filtered(
                lambda line: (
                    line.active
                    and not line.competency_id.active
                )
            )
            if archived_lines:
                raise ValidationError(
                    "This matrix contains archived competencies: %s. "
                    "Remove those rows or reactivate the competencies "
                    "before validating."
                    % ', '.join(
                        archived_lines.mapped(
                            'competency_id.display_name'
                        )
                    )
                )

            if not job.department_id:
                raise UserError(self.env._(
                    'Select a Department on job position %(job)s '
                    'before validating its competency matrix.',
                    job=job.display_name,
                ))
            assessed = job.competency_line_ids.filtered('assessment_required')
            if not assessed:
                raise UserError(self.env._(
                    'The competency matrix of %(job)s has no assessed '
                    'competency to score.', job=job.display_name,
                ))
            total = sum(assessed.mapped('weightage'))
            if abs(total - 100.0) > WEIGHTAGE_TOLERANCE:
                raise UserError(self.env._(
                    'The competency weightages of %(job)s total '
                    '%(total).2f%%. They must total exactly 100%% before the '
                    'matrix can be validated.',
                    job=job.display_name, total=total,
                ))
        self.write({'competency_matrix_state': 'validated'})

    def action_reset_competency_matrix(self):
        self.write({'competency_matrix_state': 'draft'})

    def action_add_company_wide_competencies(self):
        """Put every company-wide competency on the matrix in one click."""
        self.ensure_one()
        if self.competency_matrix_state == 'validated':
            raise UserError(self.env._(
                'Reset the matrix to draft before adding competencies to it.'
            ))
        company_wide = self.env['employee.competency'].search([
            ('is_company_wide', '=', True),
            ('company_id', 'in', [False, (self.company_id or self.env.company).id]),
        ])
        missing = company_wide - self.competency_line_ids.competency_id
        self.competency_line_ids = [
            fields.Command.create({
                'competency_id': competency.id,
                'weightage': competency.default_weightage,
                'required_level': str(competency.development_threshold or 3),
            })
            for competency in missing
        ]

    @api.model
    def _seed_competency_sample_matrix(self):
        """Load the sample Salesforce Developer matrix from the specification.

        Found or created by name rather than shipped as a record, because a
        job of that name may already exist in the database, and hr.job is
        unique per name, company and department. A job that already carries a
        matrix is left exactly as HR made it.
        """
        ref = self.env.ref
        rows = [
            # (competency xmlid, weightage, minimum level, target level)
            ('competency_att_001', 5.0, '3', '4'),
            ('competency_own_001', 10.0, '3', '4'),
            ('competency_com_001', 10.0, '3', '3'),
            ('competency_bus_001', 10.0, '2', '3'),
            ('competency_ana_001', 10.0, '3', '4'),
            ('competency_grw_001', 5.0, '3', '4'),
            ('competency_fun_apex', 15.0, '3', '4'),
            ('competency_fun_lwc', 15.0, '3', '4'),
            ('competency_fun_flow', 10.0, '3', '4'),
            ('competency_fun_api', 10.0, '2', '3'),
        ]
        competencies = [
            (ref(f'ft_employee_competency.{xmlid}', raise_if_not_found=False), *rest)
            for xmlid, *rest in rows
        ]
        if not all(competency for competency, *_rest in competencies):
            return
        job = self.search([('name', '=', 'Salesforce Developer')], limit=1)
        if not job:
            job = self.create({'name': 'Salesforce Developer'})
        if job.competency_line_ids:
            return
        job.competency_line_ids = [
            fields.Command.create({
                'sequence': sequence,
                'competency_id': competency.id,
                'weightage': weightage,
                'minimum_level': minimum,
                'required_level': target,
                'mandatory': True,
            })
            for sequence, (competency, weightage, minimum, target)
            in enumerate(competencies, start=1)
        ]

    def action_view_competency_matrix(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.env._('Competency Matrix: %s', self.name),
            'res_model': 'employee.job.competency.line',
            'view_mode': 'list,form',
            'domain': [('job_id', '=', self.id)],
            'context': {'default_job_id': self.id},
        }
