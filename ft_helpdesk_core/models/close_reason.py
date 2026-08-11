from odoo import fields, models


class HelpdeskCloseReason(models.Model):
    _name = 'ft.helpdesk.close.reason'
    _description = 'Helpdesk Close Reason'
    _order = 'sequence, name'

    name = fields.Char(string='Reason', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    is_cancel_reason = fields.Boolean(
        string='Is Cancellation Reason', default=False,
        help='If checked, this reason is only available when cancelling tickets.',
    )
    description = fields.Text(string='Description', translate=True)
