# -*- coding: utf-8 -*-
from odoo import api, models

from ..services import activity_tracker as tracker


class Base(models.AbstractModel):
    """Single, centralised hook.

    ``base`` is inherited by every model, so these three overrides cover every
    model; *which* models are tracked is data (adoption.tracking.config), not
    code, and an untracked model costs one dict lookup (see
    ``tracker.get_config``).  No per-model Python or runtime code generation.
    """
    _inherit = 'base'

    @api.model_create_multi
    def create(self, vals_list):
        cfg = tracker.get_config(self.env, self._name, 'create')
        if cfg is None:
            return super().create(vals_list)
        token = tracker.enter(self.env, self._name, 'create')
        try:
            records = super().create(vals_list)
        finally:
            tracker.leave(self.env, token)
        tracker.after_create(records, vals_list, cfg)
        return records

    def write(self, vals):
        cfg = tracker.get_config(self.env, self._name, 'update') if self else None
        if cfg is None:
            return super().write(vals)
        pre = tracker.before_write(self, vals, cfg)
        token = tracker.enter(self.env, self._name, 'write')
        try:
            result = super().write(vals)
        finally:
            tracker.leave(self.env, token)
        tracker.after_write(self, vals, cfg, pre)
        return result

    def unlink(self):
        cfg = tracker.get_config(self.env, self._name, 'delete') if self else None
        if cfg is None:
            return super().unlink()
        snap = tracker.before_unlink(self, cfg)
        token = tracker.enter(self.env, self._name, 'unlink')
        try:
            result = super().unlink()
        finally:
            tracker.leave(self.env, token)
        tracker.after_unlink(self, cfg, snap)
        return result
