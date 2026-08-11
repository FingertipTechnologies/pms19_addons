from odoo import models, fields,api


from odoo import models, fields, api

class HrVersion(models.Model):
    _inherit = 'hr.version'

    # Make the Job Position mandatory (used to classify task/project hours).
    # Odoo 19 moved job_id off hr.employee onto hr.version, which hr.employee
    # now reaches through _inherits delegation, so the override lives here.
    job_id = fields.Many2one(required=True)


class HREmployee(models.Model):
    _inherit = 'hr.employee'

    @api.onchange('job_id')
    def _onchange_job_id(self):
        """
        When job_id is changed in hr.employee, update all related
        account.analytic.line records with the new jobposition_id
        """
        if self.job_id:
            analytic_lines = self.env['account.analytic.line'].search([
                ('employee_id', '=', self.id)
            ])
            for line in analytic_lines:
                line.jobposition_id = self.job_id