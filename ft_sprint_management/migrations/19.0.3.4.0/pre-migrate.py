"""Drop the week's Status column.

A week no longer has a status of its own. It could not have one honestly once
the Weeks list became the All Projects overview: those weeks span every project
at once, and the projects inside them sit at four different stages, so no
single Planned/Working/Testing/Completed could be true of the row.

The column has to go, not just the field. ``state`` was ``required=True``,
which is a NOT NULL constraint in Postgres; leaving the column behind after the
field is removed would mean the ORM no longer writes it and every new week
INSERT would fail on that constraint.

Pre, not post: the column must be gone before the registry is built, so nothing
in the loading process reads a field the model no longer declares.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("ALTER TABLE qa_testapp_sprint DROP COLUMN IF EXISTS state")
    _logger.info("Dropped qa_testapp_sprint.state — weeks no longer carry a status.")
