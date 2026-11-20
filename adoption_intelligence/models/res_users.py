# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    adoption_excluded = fields.Boolean(
        string='Exclude from Adoption Intelligence', groups='adoption_intelligence.group_adoption_admin',
        help='Integration / service accounts. Nothing is recorded for them and they '
             'are left out of the adoption population.',default=False)

    def write(self, vals):
        result = super().write(vals)
        if 'adoption_excluded' in vals:
            self.env.registry.clear_cache()
        return result

    def _update_last_login(self):
        """Odoo calls this once per successful authentication (not per request,
        not on page refresh, not on session renewal).  We only *observe* it:
        a failure here must never break a login."""
        result = super()._update_last_login()
        try:
            with self.env.cr.savepoint(flush=False):
                self.env['adoption.login.summary']._register_login(self)
        except Exception:  # noqa: BLE001 - logging must not break authentication
            _logger.exception('Adoption Intelligence: could not record login')
        return result
