# -*- coding: utf-8 -*-
"""Install-time catch-up for the AMC monthly milestones, and the hand-over of
the automatic sending to this module's single scheduled action.

The daily scheduled action ("AMC: Monthly Milestones & Timesheets",
ir_cron_ft_amc_monthly) only ever ensures the CURRENT month. A database that installs
this module mid-month would therefore start with no milestone for the month
that is still being worked on and none for the month whose e-mail is about to
go out on the Monthly E-mail Day, so both are created here for every eligible
AMC project. ``_amc_ensure_monthly_milestone`` is idempotent, so re-running
this from a shell is safe.

Sending: the same scheduled action runs ft_amc_monthly_timesheet's report
send AND the milestone send in one run, so that module's own cron
(cron_amc_monthly_reports) is archived here - not deleted: its xmlid is
``noupdate`` data of the other module and a deleted record would be recreated
(active) by that module's next upgrade. The uninstall hook gives it back.
"""
import logging

from odoo.addons.ft_amc_monthly_timesheet.models.periods import month_start, previous_month

_logger = logging.getLogger(__name__)


def ensure_recent_milestones(env):
    """Current and previous month for every eligible AMC project. Returns the
    milestones that were created (or already existed)."""
    Project = env['project.project'].sudo()
    Report = env['ft.amc.monthly.report'].sudo()
    created = env['project.custom.milestone'].sudo()
    for project in Project._amc_milestone_candidates():
        today = Report._local_today(project.company_id or env.company)
        previous, _end = previous_month(today)
        for period_start in (previous, month_start(today)):
            created |= project._amc_ensure_monthly_milestone(period_start)
    return created


REPORT_CRON_XMLID = 'ft_amc_monthly_timesheet.cron_amc_monthly_reports'
# This module's single scheduled action (data/ir_cron_data.xml).
CRON_XMLID = 'ft_amc_payment_milestone.ir_cron_ft_amc_monthly'
CRON_NAME = 'AMC: Monthly Milestones & Timesheets'


def supersede_report_cron(env, active=False):
    """Archive (default) or restore ft_amc_monthly_timesheet's own report cron:
    while this module is installed its send runs inside CRON_XMLID
    (ir_cron_ft_amc_monthly). Idempotent; missing record: nothing to do."""
    cron = env.ref(REPORT_CRON_XMLID, raise_if_not_found=False)
    if not cron:
        _logger.warning("ft_amc_payment_milestone: %s not found; nothing to %s.",
                        REPORT_CRON_XMLID, 'restore' if active else 'archive')
        return cron
    cron = cron.sudo().with_context(active_test=False)
    if cron.active != active:
        cron.write({'active': active})
    _logger.info("ft_amc_payment_milestone: scheduled action '%s' (id %s) %s.",
                 cron.name, cron.id,
                 'restored' if active else "archived - superseded by '%s'" % CRON_NAME)
    return cron


def post_init_hook(env):
    milestones = ensure_recent_milestones(env)
    _logger.info("ft_amc_payment_milestone: %s AMC monthly milestone(s) ensured on install",
                 len(milestones))
    supersede_report_cron(env, active=False)


def uninstall_hook(env):
    """The report send is no longer run by this module's cron: give
    ft_amc_monthly_timesheet its own scheduled action back (on its 5th)."""
    supersede_report_cron(env, active=True)
