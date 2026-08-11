# -*- coding: utf-8 -*-
from odoo import fields, models


class ExpenseCategory(models.Model):
    _name = "expense.category"
    _description = "Expense Category"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "category_name"
    _rec_name = "category_name"

    category_name = fields.Char(
        string="Category Name", required=True, tracking=True)
    requires_bill = fields.Boolean(
        string="Requires Bill", default=False, tracking=True,
        help="If checked, expense lines under this category must have a "
             "bill attachment.")
    max_limit = fields.Monetary(
        string="Max Limit",
        help="Soft policy limit. Lines above this amount will trigger a "
             "warning on submit.")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)
    approval_required = fields.Boolean(
        string="Approval Required", default=True)
    description = fields.Text(string="Description")
    active = fields.Boolean(default=True)

    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    _category_name_uniq = models.Constraint(
        "unique(category_name, company_id)",
        "Expense category name must be unique per company.",
    )