# -*- coding: utf-8 -*-
from odoo import fields, models


class FtPmsStageApprovalRejectWizard(models.TransientModel):
    _name = 'ft.pms.stage.approval.reject.wizard'
    _description = 'Reject Stage Approval Request'

    approval_ids = fields.Many2many(
        'ft.pms.stage.approval', 'ft_pms_stage_approval_reject_wizard_rel',
        'wizard_id', 'approval_id', string='Approval Requests', required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.approval_ids._pwf_do_reject(self.reason)
        return {'type': 'ir.actions.act_window_close'}
