"""Backfill ft_is_trainee on timesheet lines that already existed.

``ft_is_trainee`` is stamped on creation and never recomputed, so rows written
before this version have no value at all and would every one of them read as
"not a trainee" — real training time silently missing from the Trainees
grouping on day one.

The flag is meant to record whether the employee was a trainee AT THE TIME the
line was logged, but that history does not exist for old rows.
hr.employee.job_id tracking was checked and is not usable: the recorded changes
are almost all from June 2026, when job positions were first being set up, and
include one employee cycling through eight positions in a single day. That is
somebody testing the field, not a career. So the backfill uses each employee's
CURRENT job position, which is the only defensible answer available.

The work itself lives in ``account.analytic.line._ft_backfill_trainee_id`` so it
can be re-run later — see the 18.0.0.0.3 migration for why that matters.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    # No version means a fresh install: there are no pre-existing rows to fix.
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.analytic.line']._ft_backfill_trainee_id()
