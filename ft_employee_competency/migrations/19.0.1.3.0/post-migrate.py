from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    # The assessment template is noupdate, so the upgrade does not rewrite it,
    # and its body still counts the lines through line_count - a field this
    # version removes. Left alone, every new assessment would fail to mail.
    template = env.ref(
        'ft_employee_competency.mail_template_assessment_assigned',
        raise_if_not_found=False,
    )
    if template:
        cr.execute("""
            UPDATE mail_template
               SET body_html = replace(body_html::text,
                                       'object.line_count or 0',
                                       'len(object.line_ids)')::jsonb
             WHERE id = %s
        """, [template.id])
        template.invalidate_recordset(['body_html'])

    # The sample job matrix from the specification. Fresh installs load it
    # from competency_master_data.xml; an existing database only gets it here.
    env['hr.job']._seed_competency_sample_matrix()
