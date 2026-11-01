# -*- coding: utf-8 -*-
"""Feedback Contacts now default to the project customer. Fill them in on
every existing project that has a customer but no feedback contact yet."""


def migrate(cr, version):
    cr.execute("""
        INSERT INTO ft_feedback_project_contact_rel (project_id, partner_id)
        SELECT p.id, p.partner_id
          FROM project_project p
         WHERE p.partner_id IS NOT NULL
           AND NOT EXISTS (
                SELECT 1 FROM ft_feedback_project_contact_rel r
                 WHERE r.project_id = p.id)
        ON CONFLICT DO NOTHING
    """)
