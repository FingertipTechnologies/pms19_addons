"""Point every existing task at the week its deadline falls in.

19.0.3.2.0 keeps ``sprint_id`` in step with ``date_deadline`` as tasks are
written. This does the same for the tasks already in the database, which is
most of them: the link was only ever set by dragging a card, so the full-screen
Week Board grouped the entire backlog into "None" while the board in the Tasks
tab — which groups by the deadline — showed those same tasks spread across
their weeks.

Runs after 19.0.3.0.0, which created the week records this links to.

Through the ORM rather than in SQL, which is the opposite of the usual call for
a backfill this size, for one reason: the week a deadline belongs to has to be
decided in the READER'S timezone. date_deadline is a naive UTC timestamp, and
in IST every deadline before 05:30 local belongs to the previous UTC day — so
a SQL `::date` would file those tasks a week early. _sync_week_from_deadline
already answers that question correctly, and re-answering it in SQL would mean
maintaining the same rule twice.

The write it performs is safe at this size because it is grouped: one write per
(project, week), carrying every task that belongs to it, not one per task. And
``ft_skip_week_sync`` stops the write moving the deadline to that week's Sunday
— the very value being followed here.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})

    tasks = env['project.task'].search([
        ('project_id', '!=', False),
        ('date_deadline', '!=', False),
        ('sprint_id', '=', False),
    ])
    if not tasks:
        _logger.info("No tasks needed linking to a week.")
        return

    tasks._sync_week_from_deadline()
    linked = env['project.task'].search_count([
        ('id', 'in', tasks.ids), ('sprint_id', '!=', False)])
    _logger.info(
        "Linked %s of %s unlinked tasks to the week their deadline falls in. "
        "The remainder fall in no week that exists for their project.",
        linked, len(tasks))
