# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import ValidationError


class FtMilestoneChangeRejectWizard(models.TransientModel):
    """Asks the approver for the rejection reason: a rejection without one
    tells the requester nothing."""
    _name = 'ft.milestone.change.reject.wizard'
    _description = 'Reject Milestone Change Request'

    request_id = fields.Many2one(
        'ft.milestone.change.request', string='Request', required=True,
        ondelete='cascade')
    reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise ValidationError(_("Please give the reason for rejecting the request."))
        self.request_id._do_reject(reason=self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}
