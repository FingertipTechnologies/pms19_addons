# -*- coding: utf-8 -*-
from odoo import fields, models, tools
from odoo.tools.sql import column_exists


class FtStagewiseTime(models.Model):
    _name = 'ft.stagewise.time'
    _description = 'Stage-wise Timesheet Time'
    _auto = False
    _order = 'project_id, stage_sequence'
    _rec_name = 'stage_id'
    _depends = {
        'account.analytic.line': ['project_id', 'project_status',
                                  'unit_amount', 'employee_id', 'date'],
    }

    project_id = fields.Many2one(
        'project.project', string='Project', readonly=True)
    stage_id = fields.Many2one(
        'project.project.stage', string='Project Stage', readonly=True)
    stage_sequence = fields.Integer(string='Stage Sequence', readonly=True)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', readonly=True)
    entry_date = fields.Date(string='Date', readonly=True)
    hours_spent = fields.Float(
        string='Hours Spent', readonly=True, aggregator='sum')
    entry_count = fields.Integer(
        string='Entries', readonly=True, aggregator='sum')

    def init(self):
        if not column_exists(self.env.cr, 'account_analytic_line',
                             'project_status'):
            self.env.cr.execute(
                "ALTER TABLE account_analytic_line "
                "ADD COLUMN IF NOT EXISTS project_status integer")

        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    MIN(aal.id)          AS id,
                    aal.project_id       AS project_id,
                    aal.project_status   AS stage_id,
                    st.sequence          AS stage_sequence,
                    NULL::integer        AS employee_id,
                    NULL::date           AS entry_date,
                    SUM(aal.unit_amount) AS hours_spent,
                    COUNT(aal.id)        AS entry_count
                FROM account_analytic_line aal
                JOIN project_project_stage st ON st.id = aal.project_status
                WHERE aal.project_id IS NOT NULL
                  AND aal.project_status IS NOT NULL
                GROUP BY aal.project_id, aal.project_status, st.sequence
            )
        """ % (self._table,))