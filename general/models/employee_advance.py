# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EmployeeAdvance(models.Model):
    _name = "employee.advance"
    _description = "Employee Advance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "advance_date desc, id desc"
    _rec_name = "advance_number"

    advance_number = fields.Char(
        string="Advance Number", required=True, copy=False,
        readonly=True, default=lambda self: _('New'))
    employee = fields.Many2one(
        'hr.employee', string="Employee", required=True, tracking=True)
    advance_date = fields.Date(
        string="Advance Date", required=True, tracking=True)
    advance_amount = fields.Monetary(
        string="Advance Amount", required=True, tracking=True)
    purpose = fields.Text(string="Purpose", required=True)

    # One advance, many claims. Adjusted Amount is what the linked claims
    # actually used of it (each claim's Advance Used = min(total, advance
    # paid), rejected claims count nothing), capped at the advance; the
    # balance is what is still available for the employee's next claim.
    claim_ids = fields.One2many(
        'employee.expense.claim', 'advance_id',
        string="Related Expense Claims",
        help="Claims adjusted against this advance.")
    claim_count = fields.Integer(compute='_compute_balance')
    adjusted_amount = fields.Monetary(
        string="Adjusted Amount", compute='_compute_balance', store=True)
    balance_amount = fields.Monetary(
        string="Balance Amount", compute='_compute_balance', store=True,
        tracking=True)
    status = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('partially_adjusted', 'Partially Adjusted'),
            ('closed', 'Closed'),
        ],
        string="Status", compute='_compute_balance', store=True,
        tracking=True)

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _advance_number_uniq = models.Constraint(
        "unique(advance_number, company_id)",
        "Advance number must be unique per company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('advance_number', _('New')) == _('New'):
                vals['advance_number'] = self.env[
                    'ir.sequence'].next_by_code(
                    'pms.employee.advance') or _('New')
        return super().create(vals_list)

    @api.depends('claim_ids.advance_used', 'advance_amount')
    def _compute_balance(self):
        for rec in self:
            used = sum(rec.claim_ids.mapped('advance_used'))
            advance = rec.advance_amount or 0.0
            rec.claim_count = len(rec.claim_ids)
            rec.adjusted_amount = min(used, advance)
            rec.balance_amount = advance - rec.adjusted_amount
            if advance and rec.balance_amount <= 0:
                rec.status = 'closed'
            elif rec.adjusted_amount > 0:
                rec.status = 'partially_adjusted'
            else:
                rec.status = 'open'

    @api.constrains('claim_ids', 'employee')
    def _check_claims_employee(self):
        for rec in self:
            others = rec.claim_ids.filtered(lambda c: c.employee != rec.employee)
            if others:
                raise ValidationError(_(
                    "Claim(s) %s belong to another employee and cannot be "
                    "adjusted against this advance.",
                    ', '.join(others.mapped('claim_number'))))
