from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # =====================
    # Helpdesk Ticket Emails
    # =====================
    # Stored on the company rather than in ir.config_parameter because the
    # notify list is a many2many (config_parameter only holds scalars) and
    # because a ticket already carries a company_id to scope the settings by.
    helpdesk_ticket_emails = fields.Boolean(
        string='Ticket Emails',
        help='Send a notification email when a ticket is created, escalated, '
             'closed, changes stage, or gets a customer-visible reply. One '
             'single email goes out per event with every recipient in Cc.',
    )
    helpdesk_ticket_email_to_pm = fields.Boolean(
        string='Notify Project Manager (PM)', default=True,
        help="Include the team's Project Manager (PM) in the recipients.",
    )
    helpdesk_ticket_email_to_team_lead = fields.Boolean(
        string='Notify Team Lead', default=True,
        help="Include the team's Team Leader in the recipients.",
    )
    helpdesk_ticket_email_to_assignee = fields.Boolean(
        string='Notify Assignee', default=True,
        help="Include the ticket's assigned user in the recipients.",
    )
    helpdesk_ticket_email_to_customer = fields.Boolean(
        string='Notify Customer', default=True,
        help="Include the ticket's customer in the recipients.",
    )
    # Deliberately a new field name and a new relation table rather than
    # repointing the old hr.employee m2m: the stored ids were employee ids, and
    # reusing the table would silently reinterpret them as user ids and mail
    # the wrong people.
    helpdesk_ticket_email_user_ids = fields.Many2many(
        'res.users', 'ft_helpdesk_ticket_email_user_rel',
        'company_id', 'user_id', string='Notify Users',
        domain="[('share', '=', False)]",
        help='Extra internal users copied on every ticket event email.',
    )
