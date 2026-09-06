# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Clean up project.lifecycle.date after the pl_* -> ft_* field rename.

ft_project_lifecycle renamed Regression/Training to ft_regression_date /
ft_training_date. Older lifecycle-date rows still pointed at the dropped
pl_regression_date / pl_training_date, so the "Date to Extend" cascade
could not find them and skipped them. Remove any lifecycle date whose
field_name is not in the current canonical set (ORM unlink cleans the
xmlids too); the data file (noupdate="0") refreshes the correct rows on
the same upgrade.
"""
from odoo import SUPERUSER_ID, api

CANONICAL_FIELDS = {
    "date_start",
    "kick_start_meeting_date",
    "brd_approval_date",
    "ft_regression_date",
    "sandbox_review_date",
    "uat_start_date",
    "pl_data_upload_date",
    "ft_training_date",
    "go_live_date",
    "support_start_date",
    "pl_support_end_date",
    "date",
}


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    stale = env["project.lifecycle.date"].search(
        [("field_name", "not in", list(CANONICAL_FIELDS))]
    )
    if stale:
        stale.unlink()
