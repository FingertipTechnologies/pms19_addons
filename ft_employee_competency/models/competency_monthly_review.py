from odoo import api, fields, models
from odoo.tools.misc import format_date


class CompetencyMonthlyReview(models.Model):
    """One manager's note on one resource for one month.

    The spreadsheet it replaces had three columns — Manager, Resource,
    Improvements — and a sheet per month. A record is one row of one sheet:
    the manager writing it, the employee it is about and what that employee
    should work on. Previous months are kept, one row per employee per month.
    """

    _name = 'ft.competency.monthly.review'
    _description = 'Competency Monthly Review'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, employee_id, id'
    _rec_name = 'name'

    name = fields.Char(
        string='Reference', compute='_compute_name', store=True,
    )
    employee_id = fields.Many2one(
        'hr.employee', string='Resource',
        required=True, ondelete='restrict', index=True, tracking=True,
    )
    employee_user_id = fields.Many2one(
        related='employee_id.user_id', store=True, index=True,
        string='Resource User',
    )
    manager_id = fields.Many2one(
        'hr.employee', string='Manager',
        required=True, ondelete='restrict', index=True, tracking=True,
        help='Who reviewed the resource this month. Filled from the '
             "resource's manager when left empty.",
    )
    manager_user_id = fields.Many2one(
        related='manager_id.user_id', store=True, index=True,
        string='Manager User',
    )
    department_id = fields.Many2one(
        related='employee_id.department_id', store=True, index=True,
        string='Department',
    )
    company_id = fields.Many2one(related='employee_id.company_id', store=True)
    date = fields.Date(
        string='Month', required=True, index=True, tracking=True,
        default=lambda self: self._default_date(),
        help='The month reviewed. Any day of the month may be picked; it is '
             'stored as the first day of that month.',
    )
    month_label = fields.Char(
        string='Month', compute='_compute_month_label', store=True,
    )
    improvements = fields.Text(
        string='Improvements', required=True, tracking=True,
        help='What the resource should work on, e.g. "Need to work on post '
             'sales, improve communication".',
    )

    _employee_month_uniq = models.Constraint(
        'unique(employee_id, date)',
        'A monthly review already exists for this resource for this month.',
    )

    @api.model
    def _default_date(self):
        return fields.Date.context_today(self).replace(day=1)

    @staticmethod
    def _first_of_month(value):
        return fields.Date.to_date(value).replace(day=1)

    @api.depends('date')
    def _compute_month_label(self):
        for review in self:
            review.month_label = (
                format_date(self.env, review.date, date_format='MMMM yyyy')
                if review.date else False
            )

    @api.depends('employee_id.name', 'month_label')
    def _compute_name(self):
        for review in self:
            parts = [review.employee_id.name, review.month_label]
            review.name = ' - '.join(part for part in parts if part) or False

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        for review in self:
            if review.employee_id and not review.manager_id:
                review.manager_id = review.employee_id.parent_id

    @api.model_create_multi
    def create(self, vals_list):
        employees = self.env['hr.employee']
        for vals in vals_list:
            # Snap to the first of the month so the unique constraint is per
            # month, not per day.
            if vals.get('date'):
                vals['date'] = self._first_of_month(vals['date'])
            if vals.get('employee_id') and not vals.get('manager_id'):
                vals['manager_id'] = employees.browse(vals['employee_id']).parent_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('date'):
            vals['date'] = self._first_of_month(vals['date'])
        return super().write(vals)
