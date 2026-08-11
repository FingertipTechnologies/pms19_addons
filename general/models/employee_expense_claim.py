# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EmployeeExpenseClaim(models.Model):
    _name = "employee.expense.claim"
    _description = "Employee Expense Claim"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "claim_date desc, id desc"
    _rec_name = "claim_number"

    claim_number = fields.Char(
        string="Claim Number", required=True, copy=False,
        readonly=True, default=lambda self: _('New'))
    employee = fields.Many2one(
        'hr.employee', string="Employee", required=True,
        tracking=True)
    department = fields.Many2one(
        'hr.department', string="Department")
    claim_date = fields.Date(
        string="Claim Date", required=True, tracking=True)

    # Period
    expense_period_from = fields.Date(string="Expense Period From")
    expense_period_to = fields.Date(string="Expense Period To")

    # Project/Client
    project_id = fields.Many2one('project.project', string="Project")
    partner_id = fields.Many2one('res.partner', string="Client")

    # Lines
    expense_line_ids = fields.One2many(
        'employee.expense.line', 'expense_claim',
        string="Expense Lines", copy=True)

    # Totals
    total_amount = fields.Monetary(
        string="Total Amount", compute='_compute_total_amount',
        store=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # Status (plain selection — set manually)
    approval_status = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('paid', 'Paid'),
        ],
        string="Approval Status", required=True, default='draft',
        tracking=True)
    approved_by = fields.Many2one(
        'res.users', string="Approved By")
    approved_date = fields.Date(string="Approved Date")

    # Payment
    payment_status = fields.Selection(
        selection=[
            ('unpaid', 'Unpaid'),
            ('paid', 'Paid'),
        ],
        string="Payment Status", default='unpaid', tracking=True)
    paid_date = fields.Date(string="Paid Date")
    payment_reference = fields.Char(string="Payment Reference")

    remarks = fields.Text(string="Remarks")

    # Advance link
    advance_id = fields.Many2one(
        'employee.advance', string="Advance Adjusted")

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _claim_number_uniq = models.Constraint(
        "unique(claim_number, company_id)",
        "Claim number must be unique per company.",
    )
    bill_available = fields.Boolean(string="Bills Available")

    # --------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('claim_number', _('New')) == _('New'):
                vals['claim_number'] = self.env[
                    'ir.sequence'].next_by_code(
                    'pms.employee.expense.claim') or _('New')
        return super().create(vals_list)

    @api.depends('expense_line_ids.amount')
    def _compute_total_amount(self):
        for claim in self:
            claim.total_amount = sum(
                line.amount for line in claim.expense_line_ids)

    @api.constrains('expense_period_from', 'expense_period_to')
    def _check_period(self):
        for rec in self:
            if rec.expense_period_from and rec.expense_period_to \
                    and rec.expense_period_from > rec.expense_period_to:
                raise UserError(_(
                    "Expense Period From cannot be after Expense "
                    "Period To."))

    def write(self, vals):
        res = super().write(vals)
        # Light automation when the user changes the status manually.
        if 'approval_status' in vals:
            for rec in self:
                if rec.approval_status == 'approved' and not rec.approved_by:
                    rec.approved_by = self.env.user
                    rec.approved_date = fields.Date.context_today(rec)
                elif rec.approval_status == 'paid':
                    rec.payment_status = 'paid'
                    if not rec.paid_date:
                        rec.paid_date = fields.Date.context_today(rec)
                    if rec.advance_id:
                        rec.advance_id._recompute_adjustment()
        return res