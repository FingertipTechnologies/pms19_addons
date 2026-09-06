"""Retire the HOLD stage in favour of the On Hold checkbox.

Post, not pre: the move writes ``pl_on_hold``, and that column only exists once
the module's models have been loaded.

Runs before ``migrations/0.0.0/post-migrate.py`` — numbered scripts go first in
the post stage, ``0.0.0`` last — which is the order this needs. A project still
sitting on HOLD is a type/stage mismatch as far as the reconciler is concerned,
and it would "repair" it by guessing before this script had the chance to place
it properly from the chatter.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.ft_project_lifecycle.hooks import move_hold_stage_to_flag


def migrate(cr, version):
    # Fresh installs never had a HOLD stage to retire: the data file ships it
    # archived and flagless, and post_init_hook calls the same function anyway.
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    move_hold_stage_to_flag(env)
