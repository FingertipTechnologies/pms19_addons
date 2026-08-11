"""Move already-won opportunities into the Won stage.

The same story as the Lost move one version back. Odoo wins a deal by setting
``probability = 100`` and, when the win comes from the Won button, by moving the
stage as well — but typing 100 into Probability on the form does only the first.
The record then wears the WON ribbon while its stage bar, every list, every
export and every pivot still read Demo or Discussion.

``crm.lead.write()`` now moves those records as they are won. This pass repairs
the ones won before that existed. Idempotent (records already in the Won stage
are not selected), so install and upgrade both running it is harmless.

The Closed Date backfill runs alongside, as it does in the previous migration:
the pass preserves each record's existing Closed Date, so any record still
missing one is better filled first.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['crm.lead']._ft_backfill_date_closed()
    env['crm.lead']._ft_sync_won_stage()
