from odoo import api, SUPERUSER_ID
from odoo.addons.ft_project_lifecycle.hooks import backfill_start_dates


def migrate(cr, version):
    # Runs on -u for existing installs where post_init_hook never fired (e.g. a
    # restored/cloned database). Backfills Start Date from create_date; the
    # stage migration is intentionally left to post_init to avoid re-shuffling
    # stages on databases that have already been reorganised.
    env = api.Environment(cr, SUPERUSER_ID, {})
    backfill_start_dates(env)
