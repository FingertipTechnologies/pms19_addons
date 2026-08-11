"""Move already-archived opportunities into the Lost stage.

``post_init_hook`` only fires on a fresh install, and the databases carrying
lost deals stranded in Discussion / Demo / Negotiation are the existing ones —
so the same pass has to run on upgrade too. It is idempotent (records already
in the Lost stage are not selected), so install + upgrade doing it twice is
harmless.

The Closed Date backfill is re-run alongside it because the stage move itself
can only help records that already carry a Closed Date; running both keeps the
two repairs in step.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['crm.lead']._ft_backfill_date_closed()
    env['crm.lead']._ft_sync_lost_stage()
