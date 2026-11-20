# -*- coding: utf-8 -*-
import logging
import traceback

from odoo import api, fields, models

_logger = logging.getLogger(__name__)
SUPERUSER = 1


class AdoptionErrorLog(models.Model):
    """Failures of the tracking / processing machinery itself.

    Written through its OWN cursor (committed independently).  That is the one
    deliberate exception to "everything rolls back with the business
    transaction": a tracking failure should stay visible even if the user's
    save is later rolled back.  The message never contains field values: only
    the exception type and a truncated message are kept.
    """
    _name = 'adoption.error.log'
    _inherit = ['adoption.immutable.mixin']
    _description = 'Adoption Error Log'
    _order = 'occurred_at desc, id desc'

    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    context = fields.Char(required=True, index=True,
                          help='create / write / unlink / track / rollup / score ...')
    severity = fields.Selection([('warning', 'Warning'), ('error', 'Error')], default='error', index=True)
    model_name = fields.Char(string='Model')
    user_id = fields.Many2one('res.users', ondelete='set null')
    transaction_id = fields.Char()
    message = fields.Char()
    detail = fields.Text(string='Traceback')

    @api.model
    def _log(self, context, exc, model_name=None, transaction_id=None, severity='error', uid=None):
        """Never raises."""
        try:
            message = ('%s: %s' % (type(exc).__name__, exc))[:500] if isinstance(exc, BaseException) else str(exc)[:500]
            detail = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-3500:] \
                if isinstance(exc, BaseException) else ''
            values = {
                'context': context, 'severity': severity, 'model_name': model_name,
                'transaction_id': transaction_id, 'message': message, 'detail': detail,
                'user_id': uid or self.env.uid,
            }
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER, {})
                env['adoption.error.log'].with_context(adoption_internal=True).create(values)
        except Exception:  # noqa: BLE001
            _logger.exception('Adoption Intelligence: could not write error log (%s)', context)
