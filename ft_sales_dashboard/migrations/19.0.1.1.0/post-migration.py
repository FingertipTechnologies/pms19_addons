"""Run the Closed Date repair on upgrade.

``post_init_hook`` only fires on a fresh install, and the databases that
actually carry the un-stamped won/lost opportunities are the existing ones —
so the same pass has to run here too. It is idempotent (it only ever fills a
blank ``date_closed``), so install + upgrade doing it twice is harmless.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['crm.lead']._ft_backfill_date_closed()
