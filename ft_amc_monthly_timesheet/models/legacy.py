"""Fields of the previous module version (19.0.1.x), kept unused.

Databases that still run the old version's views (module not yet upgraded)
reference these fields; the web client refuses to render a view whose field
is missing from the model. Their columns already exist there, so declaring
them needs no upgrade. Remove this file once every database is upgraded.
"""
import pytz

from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    amc_contract_state = fields.Selection([
        ('draft', 'Draft'), ('active', 'Active'), ('expired', 'Expired'),
        ('cancelled', 'Cancelled')], string='AMC contract state (legacy)', copy=False)
    amc_contract_start = fields.Date(string='AMC contract start (legacy)')
    amc_contract_end = fields.Date(string='AMC contract end (legacy)')
    amc_reporting_start = fields.Date(string='First reporting month (legacy)')
    amc_sender_email = fields.Char(string='Report sender email (legacy)', copy=False)
    amc_report_tz = fields.Selection(
        selection=[(tz, tz) for tz in pytz.all_timezones],
        string='Reporting timezone (legacy)')

    def action_amc_prepare_previous_month(self):
        return self.action_amc_generate_previous_month()


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    amc_approval_state = fields.Selection([
        ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
        string='AMC Approval (legacy)', copy=False)
