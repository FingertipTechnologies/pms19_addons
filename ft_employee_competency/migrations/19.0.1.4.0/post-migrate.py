from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    # The profile now carries its history - previous level, change, first
    # assessed, times assessed - which only a rebuild from the completed
    # reviews can fill in for the entries that already exist.
    employees = env['employee.competency.assessment'].search([
        ('state', '=', 'done'),
    ]).employee_id
    employees._rebuild_competency_profile()
