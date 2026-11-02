# -*- coding: utf-8 -*-
"""19.0.1.1.0, before the registry loads the new field definitions.

The ``internal_approved`` status disappears from project.custom.milestone's
selection in this version (no internal approval step any more). Rows still
holding it are reset to ``not_started`` here, in SQL, while the old value is
still a valid one: once the module update reflects the shrunken selection the
value is simply unknown to the ORM (the value came from this module's own
definition, so no ``ondelete`` fallback runs for it) and a later read / write
of such a row would fail validation. Not Started is the right landing spot:
these milestones were waiting for the (now removed) approval before being
sent, which is exactly what Not Started means from 19.0.1.1.0 on - the day-7
cron picks them up when their send switch is on.

The "AMC milestone awaiting internal approval" To-Dos the 19.0.1.0.0 cron
scheduled on those milestones are dropped as well: the step they asked for
no longer exists. Matched on the model and the summary (a Char, stored
untranslated in the scheduling user's language - root, so English - with a
LIKE on the distinctive part to be safe).
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE project_custom_milestone
           SET status = 'not_started'
         WHERE status = 'internal_approved'
    """)
    _logger.info("ft_amc_payment_milestone 19.0.1.1.0: %s milestone(s) reset from "
                 "internal_approved to not_started", cr.rowcount)
    cr.execute("""
        DELETE FROM mail_activity
         WHERE res_model = 'project.custom.milestone'
           AND summary ILIKE %s
    """, ('%awaiting internal approval%',))
    _logger.info("ft_amc_payment_milestone 19.0.1.1.0: %s 'awaiting internal approval' "
                 "activity(ies) removed", cr.rowcount)
