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
    'version': '19.0.1.5.0',
    'category': 'Services/Helpdesk',
    'summary': 'One notification email per ticket event, everyone in Cc',
    'description': """
        FingertipTech Helpdesk Ticket Emails
        =====================================
        Sends a single notification email when a ticket is created, escalated,
        closed/cancelled, changes stage, or receives a customer-visible reply.

        - Configured under Settings > FT Helpdesk > Ticket Emails
        - Recipients: Project Manager (PM), Team Lead, Assignee, Customer and a list of
          internal users, each independently switchable
        - Exactly one email per event with every recipient in Cc - never one
          email per person
        - Adds a Project Manager (PM) field on the helpdesk team
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'ft_helpdesk_core',
    ],
    'data': [
        'data/mail_template.xml',
        'views/team_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
