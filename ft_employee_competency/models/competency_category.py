from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .competency_utils import SCOPE_SELECTION


class EmployeeCompetencyCategory(models.Model):
    """A grouping of competencies — Leadership, Communication, Functional, ...

    The category carries the default scope for the competencies inside it, so
    an HR admin sets "Leadership competencies count as leadership" once rather
    than on every competency. A competency may still override it.
    """

    _name = 'employee.competency.category'
    _description = 'Employee Competency Category'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(
        help='Short readable prefix for the competencies in this category, '
             'such as LED for Leadership.',
    )
    sequence = fields.Integer(default=10)
    scope = fields.Selection(
        selection=SCOPE_SELECTION,
        string='Default Scope', default='core', required=True,
        help='Scope applied to new competencies created under this category. '
             'Core and functional scores are reported separately, and '
             'leadership competencies only score for employees whose job '
             'matrix includes them.',
    )
    description = fields.Text()
    active = fields.Boolean(default=True)

    competency_ids = fields.One2many(
        'employee.competency', 'category_id', string='Competencies',
    )
    hr_skill_type_id = fields.Many2one(
        'hr.skill.type', string='Employee Skill Type', readonly=True, copy=False,
        ondelete='set null',
        help='The skill type on the employee Skills tab that approved levels of '
             'this category are written to (BR-018). Created the first time a '
             'review carrying one of its competencies is completed.',
    )

    _name_uniq = models.Constraint(
        'unique(name)',
        'A competency category with this name already exists.',
    )
    @api.constrains('code', 'name')
    def _check_duplicate_code_and_name(self):
        def normalize(value):
            return ' '.join((value or '').split()).casefold()

        # Include archived categories and records hidden by access rules.
        categories = self.sudo().with_context(
            active_test=False,
            lang=None,
        ).search([])

        for record in self:
            current = categories.filtered(lambda c: c.id == record.id)
            if not current:
                continue

            other_categories = categories.filtered(
                lambda c: c.id != record.id
            )

            code = normalize(current.code)
            name = normalize(current.name)

            if code and any(
                normalize(category.code) == code
                for category in other_categories
            ):
                raise ValidationError(
                    "A competency category with this code already exists. "
                    "Capitalization and extra spaces do not make it unique."
                )

            if name and any(
                normalize(category.name) == name
                for category in other_categories
            ):
                raise ValidationError(
                    "A competency category with this name already exists. "
                    "Capitalization and extra spaces do not make it unique."
                )
