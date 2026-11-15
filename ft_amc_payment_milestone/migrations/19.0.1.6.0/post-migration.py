# -*- coding: utf-8 -*-
"""19.0.1.6.0, after the module is updated: the WHOLE AMC monthly automation
is one scheduled action.

data/ir_cron_data.xml now holds "AMC: Monthly Milestones & Timesheets"
(ir_cron_ft_amc_monthly), created (active, daily) by the update itself
because its xmlid is new (``noupdate`` only protects existing records, a
record whose xmlid is missing is still created). It creates the current
month's milestones, then sends the timesheet reports and the milestones. The
crons it supersedes are ``noupdate`` data, so the XML cannot retire them;
this script deletes them with their xmlids - they are gone from the XML, so
nothing recreates them (same pattern as the 19.0.1.5.0 migration):

* ``ir_cron_ft_amc_create_monthly_milestones`` ("AMC: Create Monthly Payment
  Milestones", the creation cron of the first release);
* ``ir_cron_ft_amc_send_monthly`` ("AMC: Send Monthly Timesheets &
  Milestones", the 19.0.1.5.0 combined send cron);
* ``ir_cron_ft_amc_send_monthly_milestones`` (the pre-19.0.1.5.0 send cron),
  for a database that skipped 19.0.1.5.0 - Odoo runs every migration whose
  version is > installed and <= new, in order, so the 19.0.1.5.0 script has
  already handled it; this is a no-op safety net.

ft_amc_monthly_timesheet's "AMC: Send Monthly Timesheet Reports"
(cron_amc_monthly_reports) stays ARCHIVED, never deleted (foreign noupdate
record; the uninstall hook restores it).

Idempotent: re-running finds nothing to delete and an already archived cron.
"""
import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.ft_amc_payment_milestone.hooks import CRON_NAME, CRON_XMLID, supersede_report_cron

_logger = logging.getLogger(__name__)

MODULE = 'ft_amc_payment_milestone'
SUPERSEDED_CRON_NAMES = (
    'ir_cron_ft_amc_create_monthly_milestones',
    'ir_cron_ft_amc_send_monthly',
    'ir_cron_ft_amc_send_monthly_milestones',
)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    for xml_name in SUPERSEDED_CRON_NAMES:
        old_cron = env.ref('%s.%s' % (MODULE, xml_name), raise_if_not_found=False)
        if old_cron:
            _logger.info("ft_amc_payment_milestone 19.0.1.6.0: deleting scheduled action '%s' "
                         "(id %s, %s), superseded by '%s'",
                         old_cron.name, old_cron.id, xml_name, CRON_NAME)
            old_cron.sudo().unlink()
        env['ir.model.data'].sudo().search([
            ('module', '=', MODULE),
            ('name', '=', xml_name),
        ]).unlink()
    supersede_report_cron(env, active=False)
    new_cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if new_cron:
        _logger.info("ft_amc_payment_milestone 19.0.1.6.0: scheduled action '%s' (id %s) is "
                     "active: %s", new_cron.name, new_cron.id, new_cron.active)
    else:
        _logger.warning("ft_amc_payment_milestone 19.0.1.6.0: %s not found after the update; "
                        "check data/ir_cron_data.xml", CRON_XMLID)
