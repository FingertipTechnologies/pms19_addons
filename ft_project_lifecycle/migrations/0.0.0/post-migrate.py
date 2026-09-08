"""Adopt the existing stages into the lifecycle, backfill Start Dates and
reconcile Project Type against stage, on every version change.

The ``0.0.0`` folder is Odoo's "run on any version change" hook, and in the
``post`` stage its scripts run last — after every other module in the upgrade
has had its say, including bt_project_customization's project classification,
which owns ft_project_type. That ordering is the whole point of putting the
repair here rather than in a numbered folder: whatever sequence of migrations a
given database happens to need, this is the last thing to touch the type/stage
pairing, so staging and live converge on a consistent state no matter what they
started from.

"Version change", precisely, and not "every ``-u``".
``MigrationManager.migrate_module`` gates 0.0.0 on
``parsed_installed_version < current_version`` (odoo/modules/migration.py), so
re-running ``-u ft_project_lifecycle`` against a database already carrying this
manifest's version executes nothing at all — silently, with no line in the log
to say so. Anyone re-running these repairs against a database that has already
taken this version has to bump the manifest to arm them again, or call
``env['project.project']._pl_finish_stage_migration()`` from ``odoo shell``.

ADOPTION, NOT MIGRATION
-----------------------
This used to create the lifecycle stages as new records and move every
project onto them. That moved 76 projects
that had not changed phase — an AMC contract in "Closed" became "Completed", a
General project in "Discovery" became "Started" — and rewrote the stage history
of the whole database in the process.

The requirement is the opposite: the new names are ABBREVIATIONS of the stages
that already exist. Discovery IS DISC, Development IS DEV. So
``adopt_legacy_stages`` re-points each xmlid at the stage that is already there,
renames it, and gives it the sequence and type flags — leaving every project's
``stage_id`` untouched. The only projects that move are the ones whose stage is
being merged into another, and active non-Implementation projects sitting on an
Implementation-only stage.

The old move-and-retire functions have been deleted. A database that already
took that route is undone from the ``ft_pl_stage_backup`` table, which records
every project's stage before the first migration touched it.
"""

import logging

from odoo import api, SUPERUSER_ID

from odoo.addons.ft_project_lifecycle.hooks import (
    adopt_legacy_stages,
    backfill_start_dates,
    legacy_pipeline_debris,
    repair_type_stage_mismatches,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # `version` is falsy on a fresh install, where post_init_hook runs the same
    # steps after it has placed the stages. Nothing to reconcile here.
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    # Start Date first, and it belongs here rather than only in post_init_hook:
    # the ORM version of this backfill never wrote a row (see the docstring in
    # hooks.py — core's write drops a lone date_start when the project has no
    # End Date), so every database that installed this module before the SQL
    # rewrite has projects with an empty Start Date that the install hook will
    # never revisit. Idempotent, so re-running it costs one UPDATE that matches
    # nothing once the backlog is cleared.
    backfill_start_dates(env)

    stages, projects = legacy_pipeline_debris(cr)
    if stages or projects:
        _logger.info(
            "ft_project_lifecycle: %s project(s) on %s unadopted stage(s); "
            "adopting the existing stages into the lifecycle.",
            projects, stages)
    adopt_legacy_stages(env)

    repair_type_stage_mismatches(env)
