# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AdoptionRecalculateWizard(models.TransientModel):
    _name = 'adoption.recalculate.wizard'
    _description = 'Recalculate Adoption Summaries and Scores'

    date_from = fields.Date(required=True, default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date(required=True, default=lambda s: fields.Date.context_today(s) - timedelta(days=1))
    rescore = fields.Boolean(default=True, string='Also recalculate monthly scores')
    result = fields.Text(readonly=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise UserError(_('"From" must not be after "To".'))
            if (rec.date_to - rec.date_from).days > 400:
                raise UserError(_('Please choose at most 400 days at a time.'))

    def action_run(self):
        self.ensure_one()
        if not self.env.user.has_group('adoption_intelligence.group_adoption_admin'):
            raise UserError(_('Only Adoption Intelligence administrators can recalculate.'))
        yesterday = fields.Date.context_today(self) - timedelta(days=1)
        end = min(self.date_to, yesterday)
        summary = self.env['adoption.daily.summary']
        outcome = summary.recalculate_range(self.date_from, end) if self.date_from <= end else {'days': 0, 'busy': False}
        lines = [_('Days recalculated: %s', outcome['days'])]
        if outcome.get('busy'):
            lines.append(_('Another aggregation is running; try again in a moment.'))
        elif self.rescore:
            Score = self.env['adoption.user.score']
            month = self.date_from.replace(day=1)
            count = 0
            while month <= end:
                start, mend = Score._period_bounds('month', month)
                count += Score.calculate_period(start, mend, 'month')
                month = mend + timedelta(days=1)
            lines.append(_('User scores written: %s', count))
        self.result = '\n'.join(lines)
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new'}
