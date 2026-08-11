"""Move the trainee stamp from a yes/no flag to the trainee's name.

Grouping the Timesheets list on the old ``ft_is_trainee`` boolean produced two
groups labelled "Yes" and "No", which answers "was this trainee time" but not
"whose". ``ft_trainee_id`` holds the employee instead, so the same Group By
lists each trainee by name and leaves everybody else's time under None.

The semantics are unchanged: still stamped from the job position held AT THE
TIME of entry, still frozen afterwards, still backfilled from current job
positions because no usable history exists.

``ft_is_trainee`` is deliberately NOT dropped. The column is orphaned rather
than deleted so that a database can be rolled back to the previous version
without losing anything; it costs one boolean per row and nothing reads it.
Drop it by hand once you are sure you are not going back:

    ALTER TABLE account_analytic_line DROP COLUMN ft_is_trainee;
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.analytic.line']._ft_backfill_trainee_id()
