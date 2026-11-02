# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Re-run the original-deadline / historical-overdue backfill on upgrade.

The install hook fills ``pwf_original_deadline`` from the chatter's deadline
tracking (or the current deadline) and stamps ``ft_historical_overdue_days``
on completed tasks, but a post_init_hook runs on INSTALL only. Databases where
it did not take (the table then shows the current deadline under "Original
Deadline" for every task, since that is the fallback) had no way to repair
themselves short of a shell session. Both steps only touch rows that are
still empty / are recomputed from the originals, so running them again is
harmless; they are now part of every upgrade.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    from odoo.addons.ft_amc_overdue_dashboard.hooks import (
        backfill_historical_overdue,
        backfill_original_deadlines,
    )
    env = api.Environment(cr, SUPERUSER_ID, {})
    originals = backfill_original_deadlines(env)
    frozen = backfill_historical_overdue(env)
    _logger.info(
        "ft_amc_overdue_dashboard 19.0.1.3.0: original deadline filled on %s "
        "task(s), historical overdue stamped on %s completed task(s).",
        originals, frozen)
