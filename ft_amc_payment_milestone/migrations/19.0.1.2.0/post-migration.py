# -*- coding: utf-8 -*-
"""19.0.1.2.0, after the module is updated: Deployed becomes a value of the
task Status (``project_task.state = '1_deployed'``, right after Done).

Up to 19.0.1.1.0 a deployed task carried only the ``ft_deployed`` flag and
stayed in Status Done. The flag remains the source of truth, so every task
that is deployed is moved to the new Status here, in SQL: the ORM would route
the write through this module's own guard (su is exempt, but a plain UPDATE
is cheaper and posts no tracking message on the historical tasks). Cancelled
deployed tasks do not exist (the action refuses them), but the state filter
keeps the migration from ever rewriting a cancellation. Idempotent.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE project_task
           SET state = '1_deployed'
         WHERE ft_deployed IS TRUE
           AND state = '1_done'
    """)
    _logger.info("ft_amc_payment_milestone 19.0.1.2.0: %s deployed task(s) moved to "
                 "Status 'Deployed'", cr.rowcount)
