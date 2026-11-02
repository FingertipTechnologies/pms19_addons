# Part of ft_amc_monthly_timesheet.
# data/cron.xml is noupdate="1", so upgrading from 19.0.1.x left the
# existing cron inactive and hourly. Force it to the intended state once.
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install: data/cron.xml already creates the correct record.
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref('ft_amc_monthly_timesheet.cron_amc_monthly_reports', raise_if_not_found=False)
    if not cron:
        _logger.warning("AMC monthly report cron not found; nothing to migrate.")
        return
    cron.with_context(active_test=False).write({
        'active': True,
        'interval_number': 1,
        'interval_type': 'days',
        'code': 'model._cron_send_monthly_reports()',
        'user_id': env.ref('base.user_root').id,
    })
    _logger.info("AMC monthly report cron (id %s) activated and set to run daily.", cron.id)
