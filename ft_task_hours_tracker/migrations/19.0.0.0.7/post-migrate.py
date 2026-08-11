"""Stamp the trainees whose catch-up silently did nothing.

18.0.0.0.5 added a hook meant to claim an employee's past time for the Trainee
group the moment HR gives them a Trainee job position. It never worked: the
backfill it calls reads hr_employee.job_id in raw SQL, and hr.employee.write
had only just set that field in the ORM cache, so the UPDATE matched no rows
and reported stamping zero lines. Every successful stamp since then came from a
migration sweep instead, which runs in its own transaction with the job
position already in the table.

So anyone mapped to a Trainee job position AFTER the last upgrade still has no
stamp on any of their history, and Group By -> Trainee shows only the time they
logged after being mapped. That is the reported bug, and this sweep closes it
for the employees already affected. The flush added to _ft_backfill_trainee_id
in this same version is what stops it recurring.

Idempotent and additive like every other run of this backfill: it only fills
empty stamps, so it cannot disturb a trainee who has since been promoted, and
it touches nothing but ft_trainee_id — no hours, dates, tasks or descriptions.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['account.analytic.line']._ft_backfill_trainee_id()
