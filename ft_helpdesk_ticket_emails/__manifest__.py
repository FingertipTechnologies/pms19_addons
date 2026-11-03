{
    'name': 'FT Helpdesk - Ticket Emails',
    # 19.0.1.4.0: with Ticket Emails on, the single Cc'd mail is the ONLY
    # mail per event. ft_helpdesk_core's separate mails are suppressed: the
    # customer's creation confirmation, the per-follower copies of a public
    # reply (the project manager's among them), the "you've been assigned"
    # mail and the project manager's new-ticket mail. The messages stay in
    # the chatter and the PM stays a follower. With Ticket Emails off the core
    # mails are sent exactly as before. Python only, no migration.
    # 19.0.1.5.0: the ticket's assignee can be copied on every event mail
    # (Settings > Ticket Emails > Assignee, on by default). On creation that
    # mail replaces the core "you've been assigned" mail; reassignments still
    # send it. New company field - upgrade the module.
    # 19.0.1.6.0: Email-to-Ticket Automation: processes incoming support emails,
    # extracts ticket numbers from subject (e.g. [TKT-000123]), updates existing
    # Chatter threads without duplicates, or creates new tickets when no reference
    # or an invalid reference is provided.
    'version': '19.0.1.6.0',
    'category': 'Services/Helpdesk',
    'summary': 'One notification email per ticket event and Email-to-Ticket incoming automation',
    'description': """
        FingertipTech Helpdesk Ticket Emails
        =====================================
        - Sends a single notification email when a ticket is created, escalated,
          closed/cancelled, changes stage, or receives a customer-visible reply.
        - Email-to-Ticket automation:
          * Automatically processes emails sent to the support email address.
          * Checks subject for valid ticket number (e.g. [TKT-000123]).
          * Updates existing ticket's Chatter with email body, sender, and attachments.
          * Automatically creates new support tickets when no or invalid ticket reference exists.
          * Prevents duplicate messages and duplicate tickets.
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
    ],
    'data': [
        'data/mail_alias_data.xml',
        'data/mail_template.xml',
        'views/team_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
