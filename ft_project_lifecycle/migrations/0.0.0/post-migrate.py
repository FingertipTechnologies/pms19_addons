"""Backfill project Start Dates and reconcile Project Type against stage, on
every upgrade.

The ``0.0.0`` folder is Odoo's "run on any version change" hook (see
``odoo/modules/migration.py``), and in the ``post`` stage its scripts run last —
after every other module in the upgrade has had its say, including
bt_project_customization's project classification, which owns ft_project_type.
That ordering is the whole point of putting the repair here rather than in a
numbered folder: whatever sequence of migrations a given database happens to
need, this is the last thing to touch the type/stage pairing, so staging and
live converge on a consistent state no matter what they started from.

The repair itself is idempotent and logs one line when there is nothing to do,
which is what makes it safe to run on every upgrade forever.
"""

from odoo import api, SUPERUSER_ID

from odoo.addons.ft_project_lifecycle.hooks import (
    backfill_start_dates,
    repair_type_stage_mismatches,
)


def migrate(cr, version):
    # `version` is falsy on a fresh install, where post_init_hook runs the same
    # repair after it has placed the stages. Nothing to reconcile here.
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Start Date first, and it belongs here rather than only in post_init_hook:
    # the ORM version of this backfill never wrote a row (see the docstring in
    # hooks.py — core's write drops a lone date_start when the project has no
    # End Date), so every database that installed this module before the SQL
    # rewrite has projects with an empty Start Date that the install hook will
    # never revisit. Idempotent, so re-running it on every upgrade costs one
    # UPDATE that matches nothing once the backlog is cleared.
    backfill_start_dates(env)
    repair_type_stage_mismatches(env)
