# -*- coding: utf-8 -*-
from odoo import _, models
from odoo.exceptions import UserError


class AdoptionImmutableMixin(models.AbstractModel):
    """Audit-style rows: created by the tracker, never edited by hand.

    ACLs already give nobody write/create/unlink; this is the second line of
    defence against ``sudo()`` code, wizards, imports and shell sessions.  The
    tracker, aggregator and retention job pass an internal context key.
    """
    _name = 'adoption.immutable.mixin'
    _description = 'Adoption Immutable Mixin'

    def write(self, vals):
        if not self.env.context.get('adoption_internal'):
            raise UserError(_('Adoption Intelligence records are read-only.'))
        return super().write(vals)

    def unlink(self):
        if not (self.env.context.get('adoption_internal') or self.env.context.get('adoption_retention')
                or self.env.context.get('module_uninstall')):
            raise UserError(_('Adoption Intelligence records cannot be deleted manually. '
                              'They expire automatically (see retention in the settings).'))
        return super().unlink()
