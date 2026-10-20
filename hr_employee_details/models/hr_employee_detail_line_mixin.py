from odoo import api, fields, models, _
from odoo.exceptions import AccessError
from odoo.fields import Domain


class HrEmployeeDetailLineMixin(models.AbstractModel):
    """Shared behaviour of the Family Particulars / References lines.

    ``employee_public_id`` mirrors ``employee_id`` (hr.employee.public uses the
    same ids as hr.employee) so the lines can also be shown as a One2many on
    the public employee profile. It is not stored: no schema change.
    """
    _name = 'hr.employee.detail.line.mixin'
    _description = 'Employee Personal Detail Line'

    employee_public_id = fields.Many2one(
        'hr.employee.public', string='Employee (public)',
        compute='_compute_employee_public_id',
        search='_search_employee_public_id',
        ondelete='cascade')

    @api.depends('employee_id')
    def _compute_employee_public_id(self):
        Public = self.env['hr.employee.public']
        for line in self:
            line.employee_public_id = Public.browse(line.employee_id.id) if line.employee_id else False

    def _search_employee_public_id(self, operator, value):
        if isinstance(value, models.BaseModel):
            value = value.ids
        return Domain('employee_id', operator, value)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            public_id = vals.pop('employee_public_id', None)
            if public_id and not vals.get('employee_id'):
                vals['employee_id'] = public_id
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        public_id = vals.pop('employee_public_id', None)
        if public_id and 'employee_id' not in vals:
            vals['employee_id'] = public_id
        # Record rules are checked on the lines *before* the write, so without
        # this guard an employee could move one of their own lines onto
        # another employee's record.
        if 'employee_id' in vals and not self.env.su \
                and not self.env['hr.employee.public']._is_personal_details_admin():
            raise AccessError(_("You cannot move %s to another employee.", self._description))
        return super().write(vals)
