from odoo import models, fields, api
from odoo.exceptions import UserError


class QABugDevRejectWizard(models.TransientModel):
    """Developer rejects a bug (status Rejected) with a mandatory reason."""
    _name = 'qa_testapp.bug_dev_reject_wizard'
    _description = 'QA Bug - Developer Reject Wizard'

    ticket_ids = fields.Many2many('qa_testapp.ticket', string='Bugs', required=True)
    reason = fields.Text(string='Invalid Reason', required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'qa_testapp.ticket':
            res['ticket_ids'] = [(6, 0, self.env.context.get('active_ids') or [])]
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.ticket_ids:
            raise UserError("No bug selected.")
        self.ticket_ids.action_dev_reject(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
