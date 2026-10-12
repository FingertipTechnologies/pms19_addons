from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Assessment = env['employee.competency.assessment']
    Line = env['employee.competency.assessment.line']

    # Previous Level is computed now instead of copied once at generation, and
    # a field turned computed is not recomputed by the upgrade on its own. The
    # baseline link is refreshed first: reviews raised while the previous one
    # was still open never picked it up.
    env.add_to_compute(Assessment._fields['previous_assessment_id'], Assessment.search([]))
    env.add_to_compute(Line._fields['previous_rating'], Line.search([]))
    env.flush_all()

    # BR-018: results already approved before this version reach the
    # employees' skills too.
    employees = Assessment.search([('state', '=', 'done')]).employee_id
    employees._rebuild_competency_profile()
    employees._sync_employee_skills()
