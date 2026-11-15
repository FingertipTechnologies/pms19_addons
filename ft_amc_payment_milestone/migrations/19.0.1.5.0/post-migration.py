# -*- coding: utf-8 -*-
"""19.0.1.5.0, after the module is updated: one scheduled action sends the AMC
timesheet / task reports and the AMC payment milestones together.

data/ir_cron_data.xml now holds "AMC: Send Monthly Timesheets & Milestones"
(ir_cron_ft_amc_send_monthly), created (active, daily) by the update itself
because its xmlid is new. The two crons it supersedes are ``noupdate`` data,
so the XML cannot retire them; this script does:

* ``ir_cron_ft_amc_send_monthly_milestones`` ("AMC: Send Monthly Milestone
  Timesheets", this module's own) is deleted with its xmlid - it is gone from
  the XML, so nothing recreates it (same pattern as
  ft_customer_feedback 19.0.2.3.1);
* ``ft_amc_monthly_timesheet.cron_amc_monthly_reports`` ("AMC: Send Monthly
  Timesheet Reports") is ARCHIVED, not deleted: it belongs to the other
  module, stays in its XML for stand-alone installs, and a deleted noupdate
  record would be recreated active by that module's next upgrade.

Idempotent: re-running finds nothing to delete and an already archived cron.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.ft_amc_payment_milestone.hooks import supersede_report_cron

_logger = logging.getLogger(__name__)

OLD_CRON_MODULE = 'ft_amc_payment_milestone'
OLD_CRON_NAME = 'ir_cron_ft_amc_send_monthly_milestones'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    old_cron = env.ref('%s.%s' % (OLD_CRON_MODULE, OLD_CRON_NAME), raise_if_not_found=False)
    if old_cron:
        _logger.info("ft_amc_payment_milestone 19.0.1.5.0: deleting scheduled action '%s' "
                     "(id %s), superseded by 'AMC: Send Monthly Timesheets & Milestones'",
                     old_cron.name, old_cron.id)
        old_cron.sudo().unlink()
    env['ir.model.data'].sudo().search([
        ('module', '=', OLD_CRON_MODULE),
        ('name', '=', OLD_CRON_NAME),
    ]).unlink()
    supersede_report_cron(env, active=False)
    new_cron = env.ref('ft_amc_payment_milestone.ir_cron_ft_amc_send_monthly',
                       raise_if_not_found=False)
    if new_cron:
        _logger.info("ft_amc_payment_milestone 19.0.1.5.0: scheduled action '%s' (id %s) is "
                     "active: %s", new_cron.name, new_cron.id, new_cron.active)
    else:
        _logger.warning("ft_amc_payment_milestone 19.0.1.5.0: ir_cron_ft_amc_send_monthly not "
                        "found after the update; check data/ir_cron_data.xml")
