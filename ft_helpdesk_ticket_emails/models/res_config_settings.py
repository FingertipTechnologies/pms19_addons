from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    helpdesk_ticket_emails = fields.Boolean(
        related='company_id.helpdesk_ticket_emails', readonly=False,
    )
    helpdesk_ticket_email_to_pm = fields.Boolean(
        related='company_id.helpdesk_ticket_email_to_pm', readonly=False,
    )
    helpdesk_ticket_email_to_team_lead = fields.Boolean(
        related='company_id.helpdesk_ticket_email_to_team_lead', readonly=False,
    )
    helpdesk_ticket_email_to_assignee = fields.Boolean(
        related='company_id.helpdesk_ticket_email_to_assignee', readonly=False,
    )
    helpdesk_ticket_email_to_customer = fields.Boolean(
        related='company_id.helpdesk_ticket_email_to_customer', readonly=False,
    )
    helpdesk_ticket_email_user_ids = fields.Many2many(
        related='company_id.helpdesk_ticket_email_user_ids', readonly=False,
    )
