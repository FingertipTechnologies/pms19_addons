from odoo import models, fields, api
from odoo.exceptions import UserError


class QABulkApproveWizard(models.TransientModel):
    _name = 'qa_testapp.bulk_approve_wizard'
    _description = 'QA Bulk Approve / Reject Wizard'

    action_type = fields.Selection([
        ('approve', 'Approve'),
        ('reject', 'Reject'),
    ], string='Action', required=True, default='approve')
    target_model = fields.Selection([
        ('qa_testapp.ticket', 'Bug'),
        ('qa_testapp.test_case', 'Test Case'),
    ], string='Target', required=True)
    record_ids = fields.Char(string='Record IDs', required=True)
    rejection_reason = fields.Text(string='Rejection Reason')
    eligible_count = fields.Integer(string='Eligible Records', readonly=True)
    skipped_count = fields.Integer(string='Skipped (not your project)', readonly=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids') or []
        if active_model not in ('qa_testapp.ticket', 'qa_testapp.test_case'):
            raise UserError("This wizard can only be launched from the Bug or Test Case list.")
        records = self.env[active_model].browse(active_ids)
        pending = records.filtered(lambda r: r.approval_state == 'pending_approval')
        own = pending.filtered(
            lambda r: r._user_can_approve() if hasattr(r, '_user_can_approve')
            else r.approver_id == self.env.user
        )
        res.update({
            'target_model': active_model,
            'record_ids': ','.join(str(i) for i in own.ids),
            'eligible_count': len(own),
            'skipped_count': len(records) - len(own),
        })
        return res

    def _records(self):
        if not self.record_ids:
            return self.env[self.target_model]
        ids = [int(x) for x in self.record_ids.split(',') if x.strip()]
        return self.env[self.target_model].browse(ids)

    def action_confirm(self):
        self.ensure_one()
        records = self._records()
        if not records:
            raise UserError("No eligible records to process. You can only approve/reject bugs or test cases in projects where you are the PM.")
        if self.action_type == 'approve':
            for rec in records:
                rec.action_approve()
        else:
            if not self.rejection_reason:
                raise UserError("Please provide a rejection reason.")
            for rec in records:
                rec.action_reject(reason=self.rejection_reason)
        return {'type': 'ir.actions.act_window_close'}
