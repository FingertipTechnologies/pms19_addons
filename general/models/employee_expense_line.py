# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EmployeeExpenseLine(models.Model):
    _name = "employee.expense.line"
    _description = "Employee Expense Line"
    _order = "expense_date desc, id desc"

    name = fields.Char(
        string="Reference", compute="_compute_name", store=True)
    expense_claim = fields.Many2one(
        'employee.expense.claim', string="Expense Claim",
        required=True, ondelete='cascade')
    expense_date = fields.Date(
        string="Expense Date", required=True)
    category = fields.Many2one(
        'expense.category', string="Category", required=True)
    description = fields.Text(string="Description", required=True)
    amount = fields.Monetary(string="Amount", required=True)
    tax_amount = fields.Monetary(string="Tax Amount")
    payment_mode = fields.Selection(
        selection=[
            ('cash', 'Cash'),
            ('upi', 'UPI'),
            ('card', 'Card'),
            ('company_card', 'Company Card'),
            ('bank_transfer', 'Bank Transfer'),
        ],
        string="Payment Mode")
    bill_available = fields.Boolean(string="Bill Available")
    bill_attachment = fields.Many2many(
        'ir.attachment', 'expense_line_attachment_rel',
        'line_id', 'attachment_id', string="Bill Attachment")

    project_id = fields.Many2one('project.project', string="Project")
    partner_id = fields.Many2one('res.partner', string="Client")

    remarks = fields.Text(string="Remarks")

    currency_id = fields.Many2one(
        related='expense_claim.currency_id', store=True, readonly=True)

    company_id = fields.Many2one(
        related='expense_claim.company_id', store=True, readonly=True)

    @api.depends('expense_claim.claim_number')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.expense_claim.claim_number or "Expense Line"

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_("Amount must be greater than zero."))

    @api.onchange('category')
    def _onchange_category(self):
        if self.category and self.category.max_limit \
                and self.amount > self.category.max_limit:
            return {
                'warning': {
                    'title': _("Amount exceeds category limit"),
                    'message': _(
                        "The amount %(amt)s exceeds the policy limit of "
                        "%(lim)s for category '%(cat)s'."
                    ) % {
                        'amt': self.amount,
                        'lim': self.category.max_limit,
                        'cat': self.category.category_name,
                    },
                },
            }

    @api.model_create_multi
    def create(self, vals_list):
        is_manager = self.env.user.has_group('general.group_expense_manager') or self.env.is_admin() or self.env.su
        if not is_manager:
            for vals in vals_list:
                claim_id = vals.get('expense_claim')
                if claim_id:
                    claim = self.env['employee.expense.claim'].browse(claim_id)
                    if claim.approval_status != 'draft':
                        raise UserError(_(
                            "You cannot add expense lines to a claim that has already been submitted."
                        ))
        return super().create(vals_list)

    def write(self, vals):
        is_manager = self.env.user.has_group('general.group_expense_manager') or self.env.is_admin() or self.env.su
        if not is_manager:
            for line in self:
                if line.expense_claim.approval_status != 'draft':
                    raise UserError(_(
                        "You cannot modify expense lines on a claim that has already been submitted."
                    ))
        return super().write(vals)

    def unlink(self):
        is_manager = self.env.user.has_group('general.group_expense_manager') or self.env.is_admin() or self.env.su
        if not is_manager:
            for line in self:
                if line.expense_claim.approval_status != 'draft':
                    raise UserError(_(
                        "You cannot delete expense lines on a claim that has already been submitted."
                    ))
        return super().unlink()
