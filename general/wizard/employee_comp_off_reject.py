# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class EmployeeCompOffReject(models.TransientModel):
    """Asks for the rejection reason before rejecting a Comp-Off request."""
    _name = "employee.comp.off.reject"
    _description = "Reject Employee Comp-Off"

    comp_off_id = fields.Many2one(
        'employee.comp.off', string="Comp-Off Request",
        required=True, readonly=True)
    reason = fields.Text(string="Rejection Reason", required=True)

    def action_confirm(self):
        self.ensure_one()
        reason = (self.reason or '').strip()
        if not reason:
            raise UserError(_("Please provide a rejection reason."))
        self.comp_off_id.action_do_reject(reason)
        return {'type': 'ir.actions.act_window_close'}

