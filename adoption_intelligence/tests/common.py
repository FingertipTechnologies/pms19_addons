# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class AdoptionCase(TransactionCase):
    """Tracks res.partner (a base model, so the tests need no other app)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Config = cls.env['adoption.tracking.config']
        cls.Log = cls.env['adoption.activity.log'].sudo()
        cls.Change = cls.env['adoption.field.change'].sudo()
        model = cls.env['ir.model']._get('res.partner')
        cls.cfg = cls.Config.sudo().with_context(active_test=False).search([('model_id', '=', model.id)], limit=1)
        vals = {'is_tracking_enabled': True, 'track_create': True, 'track_update': True,
                'track_delete': True, 'track_field_changes': True, 'track_read': True,
                'track_view_time': True, 'active': True}
        if cls.cfg:
            cls.cfg.write(vals)
        else:
            cls.cfg = cls.Config.sudo().create(dict(vals, model_id=model.id))
        cls.phone_cfg = cls.env['adoption.field.config'].sudo().search(
            [('tracking_config_id', '=', cls.cfg.id), ('field_name', '=', 'phone')], limit=1)
        if not cls.phone_cfg:
            cls.phone_cfg = cls.env['adoption.field.config'].sudo().create({
                'tracking_config_id': cls.cfg.id, 'is_meaningful': True, 'weight': 1.0,
                'field_id': cls.env['ir.model.fields']._get('res.partner', 'phone').id})
        cls.user = cls.env.user
        cls.env.registry.clear_cache()

    def partner(self, **vals):
        """A partner created as a *web* user (so it counts as human activity)."""
        return self.env['res.partner'].with_context(adoption_source='web').create(
            dict({'name': 'Probe'}, **vals))

    def logs(self, record, op=None):
        domain = [('model_name', '=', record._name), ('record_id', '=', record.id)]
        if op:
            domain.append(('operation', '=', op))
        return self.Log.search(domain, order='id')

    def new_request(self):
        """Simulate a separate HTTP request inside one test transaction."""
        from odoo.addons.adoption_intelligence.services import activity_tracker as t
        t.txn_state(self.env).pop('seen', None)
