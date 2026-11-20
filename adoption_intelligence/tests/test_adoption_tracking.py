# -*- coding: utf-8 -*-
"""Needs a real Odoo 19 database (TransactionCase). NOT run in the authoring sandbox."""
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import AdoptionCase


@tagged('post_install', '-at_install', 'adoption')
class TestAdoptionTracking(AdoptionCase):

    def test_create_is_tracked(self):
        p = self.partner()
        log = self.logs(p, 'create')
        self.assertEqual(len(log), 1)
        self.assertEqual((log.activity_type, log.is_automated, log.source), ('primary', False, 'web'))
        self.assertEqual(log.user_id, self.env.user)

    def test_update_old_new_values(self):
        p = self.partner(phone='111')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '222'})
        upd = self.logs(p, 'update')
        self.assertEqual(len(upd), 1)
        change = self.Change.search([('activity_log_id', '=', upd.id)])
        self.assertEqual((change.field_name, change.old_value, change.new_value), ('phone', '111', '222'))
        self.assertTrue(change.is_meaningful)

    def test_multiple_fields_make_separate_rows(self):
        p = self.partner(phone='1', city='A')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '2', 'city': 'B'})
        upd = self.logs(p, 'update')
        self.assertEqual(sorted(upd.field_change_ids.mapped('field_name')), ['city', 'phone'])
        self.assertEqual(upd.field_change_count, 2)

    def test_unchanged_value_creates_nothing(self):
        p = self.partner(phone='111')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '111'})
        self.assertFalse(self.logs(p, 'update'))

    def test_delete_is_tracked_with_snapshot(self):
        p = self.partner(phone='999')
        self.new_request()
        pid = p.id
        p.with_context(adoption_source='web').unlink()
        dele = self.Log.search([('model_name', '=', 'res.partner'), ('record_id', '=', pid), ('operation', '=', 'delete')])
        self.assertEqual(len(dele), 1)
        snap = dele.field_change_ids
        self.assertEqual(snap.change_kind, 'final')
        self.assertEqual(dele.field_change_count, 0, 'deletion snapshots never count as edits')

    def test_excluded_field_is_not_tracked(self):
        fc = self.env['adoption.field.config'].sudo().create({
            'tracking_config_id': self.cfg.id, 'is_tracked': False,
            'field_id': self.env['ir.model.fields']._get('res.partner', 'city').id})
        p = self.partner(city='A')
        self.new_request()
        p.with_context(adoption_source='web').write({'city': 'B'})
        self.assertFalse(self.logs(p, 'update'), 'only an excluded field changed')
        fc.unlink()

    def test_sensitive_field_config_is_refused(self):
        with self.assertRaises(Exception):
            self.env['adoption.field.config'].sudo().create({
                'tracking_config_id': self.env['adoption.tracking.config'].sudo().search([('model_name', '=', 'res.partner')], limit=1).id,
                'field_id': self.env['ir.model.fields']._get('res.users', 'password').id})

    def test_masked_field_stores_no_value(self):
        fc = self.env['adoption.field.config'].sudo().create({
            'tracking_config_id': self.cfg.id, 'mask_value': True,
            'field_id': self.env['ir.model.fields']._get('res.partner', 'street').id})
        p = self.partner(street='secret street')
        self.new_request()
        p.with_context(adoption_source='web').write({'street': 'other street'})
        ch = self.Change.search([('record_id', '=', p.id), ('field_name', '=', 'street'), ('change_kind', '=', 'update')])
        self.assertEqual((ch.old_value, ch.new_value, ch.is_masked), ('***masked***', '***masked***', True))
        fc.unlink()

    def test_disabled_model_is_not_tracked(self):
        self.cfg.is_tracking_enabled = False
        p = self.partner()
        self.assertFalse(self.logs(p))
        self.cfg.is_tracking_enabled = True

    def test_operation_flags(self):
        self.cfg.track_update = False
        p = self.partner(phone='1')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '2'})
        self.assertFalse(self.logs(p, 'update'))
        self.assertTrue(self.logs(p, 'create'))
        self.cfg.track_update = True

    def test_batch_create_and_write(self):
        ps = self.env['res.partner'].with_context(adoption_source='web').create(
            [{'name': 'B%d' % i, 'phone': '1'} for i in range(5)])
        self.assertEqual(self.Log.search_count([('model_name', '=', 'res.partner'), ('record_id', 'in', ps.ids), ('operation', '=', 'create')]), 5)
        self.new_request()
        ps.with_context(adoption_source='web').write({'phone': '2'})
        upd = self.Log.search([('record_id', 'in', ps.ids), ('operation', '=', 'update'), ('model_name', '=', 'res.partner')])
        self.assertEqual(len(upd), 5)
        self.assertEqual(len(set(upd.mapped('transaction_id'))), 1, 'one transaction id for the batch')

    def test_rollback_leaves_no_activity(self):
        pid = None
        try:
            with self.env.cr.savepoint():
                p = self.partner()
                pid = p.id
                raise UserError('boom')
        except UserError:
            pass
        self.assertFalse(self.Log.search([('model_name', '=', 'res.partner'), ('record_id', '=', pid)]))

    def test_no_recursive_audit(self):
        before = self.Log.search_count([('model_name', 'like', 'adoption.%')])
        self.partner()
        self.assertEqual(self.Log.search_count([('model_name', 'like', 'adoption.%')]), before)

    def test_internal_models_cannot_be_configured(self):
        with self.assertRaises(Exception):
            self.Config.sudo().create({'model_id': self.env['ir.model']._get('adoption.activity.log').id})

    def test_followup_write_in_same_transaction_is_secondary(self):
        p = self.partner(phone='1')
        self.new_request()
        p.with_context(adoption_source='web').write({'phone': '2'})          # first touch: primary
        p.with_context(adoption_source='web').write({'phone': '3'})          # same transaction: follow-on
        upd = self.logs(p, 'update').sorted('id')
        self.assertEqual(upd.mapped('activity_type'), ['primary', 'secondary'])
        self.assertEqual(upd.mapped('is_automated'), [False, True])
        self.assertEqual(upd[1].adoption_points, 0.0)

    def test_no_request_means_automation(self):
        p = self.env['res.partner'].create({'name': 'Cron made'})            # no adoption_source, no HTTP request
        log = self.logs(p, 'create')
        self.assertTrue(log.is_automated)
        self.assertEqual(log.adoption_points, 0.0)

    def test_import_follows_setting(self):
        S = self.env['adoption.settings']._get()
        S.import_counts_as_automated = True
        p = self.env['res.partner'].with_context(adoption_source='import').create({'name': 'Imported'})
        self.assertTrue(self.logs(p, 'create').is_automated)
        S.import_counts_as_automated = False
        q = self.env['res.partner'].with_context(adoption_source='import').create({'name': 'Imported 2'})
        self.assertFalse(self.logs(q, 'create').is_automated)

    def test_logs_are_immutable(self):
        log = self.logs(self.partner(), 'create')
        with self.assertRaises(UserError):
            log.write({'operation': 'delete'})
        with self.assertRaises(UserError):
            log.unlink()
