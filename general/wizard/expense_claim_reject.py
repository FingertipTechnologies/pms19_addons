# -*- coding: utf-8 -*-
from odoo import fields, models


class EmployeeExpenseClaimReject(models.TransientModel):
    """Asks for the reason before an expense claim is rejected."""
    _name = "employee.expense.claim.reject"
    _description = "Reject Expense Claim"

    claim_id = fields.Many2one(
        'employee.expense.claim', string="Claim", required=True, readonly=True)
    reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.claim_id.action_do_reject(self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
