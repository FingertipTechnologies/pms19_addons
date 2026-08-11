"""Re-run the ft_is_trainee backfill now that employees have Trainee positions.

The 18.0.0.0.2 backfill was correct but arrived too early to do anything: on the
databases it ran against, no employee had been mapped to a Trainee job position
yet, so it found nothing to flag and returned. Mapping people afterwards does
not fix that by itself — the flag is frozen at entry time on purpose, so
nothing recomputes it.

That leaves the Trainees grouping reading zero even though the training hours
are sitting right there. This runs the same backfill again, against the job
positions as they now stand.

The backfill only ever sets the flag, never clears it, so re-running cannot
undo a stamp made earlier or reclassify somebody who has since been promoted.

If HR maps another batch of employees after this, no further migration is
needed — run the backfill directly instead:

    odoo shell -d <database>
    >>> env['account.analytic.line']._ft_backfill_trainee_id()
    >>> env.cr.commit()
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.analytic.line']._ft_backfill_trainee_id()
