# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


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
        string="Status", required=True, default='open', tracking=True)

    related_expense_claim = fields.Many2one(
        'employee.expense.claim',
        string="Related Expense Claim",
        help="Claim used for adjustment of this advance.")

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

    @api.depends('related_expense_claim.total_amount', 'advance_amount')
    def _compute_balance(self):
        for rec in self:
            claim = rec.related_expense_claim
            adjusted = claim.total_amount if claim else 0.0
            rec.adjusted_amount = adjusted
            rec.balance_amount = (rec.advance_amount or 0.0) - adjusted


def _recompute_adjustment(self):
        """Called by linked claims when paid; updates status."""
        for rec in self:
            rec._compute_balance()
            if rec.balance_amount <= 0:
                rec.status = 'closed'
            elif rec.adjusted_amount > 0:
                rec.status = 'partially_adjusted'
            else:
                rec.status = 'open'
