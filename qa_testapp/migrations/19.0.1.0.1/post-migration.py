def migrate(cr, version):
    cr.execute("""
        UPDATE ir_attachment att
           SET res_model = 'qa_testapp.ticket', res_id = rel.ticket_id
          FROM qa_testapp_ticket_attachment_rel rel
         WHERE rel.attachment_id = att.id
           AND (att.res_model IS DISTINCT FROM 'qa_testapp.ticket'
                OR att.res_id IS DISTINCT FROM rel.ticket_id)
    """)
