# -*- coding: utf-8 -*-
"""Install-time catch-up for the AMC monthly milestones.

The daily cron only ever ensures the CURRENT month. A database that installs
this module mid-month would therefore start with no milestone for the month
that is still being worked on and none for the month whose e-mail is about to
go out on the 7th, so both are created here for every eligible AMC project.
``_amc_ensure_monthly_milestone`` is idempotent, so re-running this from a
shell is safe.
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


def post_init_hook(env):
    milestones = ensure_recent_milestones(env)
    _logger.info("ft_amc_payment_milestone: %s AMC monthly milestone(s) ensured on install",
                 len(milestones))
