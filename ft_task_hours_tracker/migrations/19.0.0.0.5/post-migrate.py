"""Catch up any trainee mapped between the last upgrade and this one.

From this version on, hr.employee.write stamps an employee's existing time as
soon as they are given a Trainee job position, so the Trainee group fills in by
itself. Anyone mapped BEFORE that hook existed was never stamped, and nothing
would ever go back for them.

One last sweep closes that window. Idempotent and additive like every other
run of this backfill: it only fills empty stamps, so it cannot disturb a
trainee who has since been promoted.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.analytic.line']._ft_backfill_trainee_id()
