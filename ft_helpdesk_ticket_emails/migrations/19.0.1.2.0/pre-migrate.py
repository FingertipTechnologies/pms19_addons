"""Release the mail template so the new subject line can land.

The template was first shipped inside <data noupdate="1">, which stamped
ir_model_data.noupdate = true for it. That flag lives in the database and keeps
protecting the record even after the attribute is dropped from the XML, so
without this the upgrade would silently keep the old subject.
"""


def migrate(cr, version):
    cr.execute("""
        UPDATE ir_model_data
           SET noupdate = false
         WHERE module = 'ft_helpdesk_ticket_emails'
           AND name = 'mt_ticket_event_email_template'
    """)
