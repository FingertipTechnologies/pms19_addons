from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from . import validators as v


class HrEmployeeFamily(models.Model):
    _name = 'hr.employee.family'
    _inherit = ['hr.employee.detail.line.mixin']
    _description = 'Employee Family Particulars'

    employee_id = fields.Many2one('hr.employee', string='Employee', ondelete='cascade')
    name = fields.Char(string='Name', required=True)
    date_of_birth = fields.Date(string='Date of Birth')
    relation = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('spouse', 'Spouse'),
        ('kid', 'Kid'),
        ('other', 'Other'),
    ], string='Relationship', required=True)
    is_residing_with = fields.Selection([
        ('yes', 'Yes'),
        ('no', 'No'),
    ], string='Residing with Employee')
    place_of_residence = fields.Char(string='Place of Residence (if not residing)')
    state = fields.Many2one(
        'res.country.state', string='State',
        domain="[('country_id.code', '=', 'IN')]")
    district = fields.Char(string='District')
    phone = fields.Char(string='Phone Number')

    @api.constrains('date_of_birth')
    def _check_date_of_birth_not_future(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_of_birth and rec.date_of_birth > today:
                raise ValidationError(_(
                    "Date of Birth of family member '%s' cannot be a future date.", rec.name))

    @api.constrains('name')
    def _check_name(self):
        for rec in self:
            if not v.is_alpha_name(rec.name):
                raise ValidationError(_(
                    "Family Particulars - Name '%s' must contain letters only "
                    "(no numbers or special characters).", rec.name))

    @api.constrains('district')
    def _check_district(self):
        for rec in self:
            if not v.is_alpha_name(rec.district):
                raise ValidationError(_(
                    "Family Particulars - District for '%s' must contain letters only.",
                    rec.name))

    @api.constrains('relation', 'phone')
    def _check_phone(self):
        for rec in self:
            phone = (rec.phone or '').strip()
            if rec.relation != 'kid' and not phone:
                raise ValidationError(_(
                    "Family Particulars - Phone Number is mandatory for '%s'.",
                    rec.name or rec.relation or ''))
            if phone and not v.is_phone(phone, 10, 13):
                raise ValidationError(_(
                    "Family Particulars - Phone Number for '%s' is not valid. Use numbers "
                    "only (10 to 13 digits, an optional leading +); letters are not allowed.",
                    rec.name or ''))

    @api.constrains('employee_id', 'relation', 'date_of_birth')
    def _check_parent_birth_date(self):
        """Father's and Mother's DOB must be before employee's DOB."""
        for rec in self:
            if (
                    rec.employee_id
                    and rec.relation in ('father', 'mother')
                    and rec.date_of_birth
                    and rec.employee_id.birthday
                    and rec.date_of_birth >= rec.employee_id.birthday
            ):
                relation_label = dict(
                    rec._fields['relation'].selection
                ).get(rec.relation, rec.relation)

                raise ValidationError(_(
                    "%s's Date of Birth must be earlier than "
                    "the employee's Date of Birth.",
                    relation_label,
                ))

    @api.constrains('employee_id', 'relation')
    def _check_unique_family_relation(self):
        """Allow only one Father, Mother, and Spouse per employee."""
        unique_relations = {'father', 'mother', 'spouse'}

        for rec in self:
            if not rec.employee_id or rec.relation not in unique_relations:
                continue

            duplicate = self.search([
                ('employee_id', '=', rec.employee_id.id),
                ('relation', '=', rec.relation),
                ('id', '!=', rec.id),
            ], limit=1)

            if duplicate:
                relation_label = dict(
                    rec._fields['relation'].selection
                ).get(rec.relation, rec.relation)

                raise ValidationError(_(
                    "Only one %s is allowed for an employee.",
                    relation_label,
                ))

    def unlink(self):
        if not self.env.user.has_group('hr.group_hr_user'):
            employees_to_check = self.mapped('employee_id').filtered(
                lambda emp: emp.aadhar_no or emp.pan_no
            )
            for emp in employees_to_check:
                remaining = self.search_count([
                    ('employee_id', '=', emp.id),
                    ('id', 'not in', self.ids),
                ])
                if remaining < 1:
                    raise ValidationError(_(
                        "Family Particulars must contain at least 1 record for employee '%s'.",
                        emp.name,
                    ))
        return super().unlink()