from odoo import models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    def write(self, vals):
        """Claim past time for the Trainee group when somebody is marked a trainee.

        Giving an employee a Trainee job position is almost always a
        correction rather than a change: they were already a trainee, the
        system simply had no record of it. The hours they logged up to that
        point are training hours, so they are stamped here instead of sitting
        unclassified until somebody remembers to run the backfill by hand.

        The reverse move needs no handling at all, which is the point of
        stamping the value rather than computing it. Promote a trainee and the
        backfill does nothing: it only ever fills an empty stamp, never clears
        one. Every hour they logged while training keeps its stamp, and the
        time they log from then on carries their new position instead.

        Scoped to the employees actually being written, so this stays a
        single-employee UPDATE rather than a sweep of the whole timesheet
        table on every HR edit.
        """
        res = super().write(vals)
        if 'job_id' in vals:
            self.env['account.analytic.line']._ft_backfill_trainee_id(
                employees=self)
        return res
