# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Swap the Standard Implementation template to the seven named milestones.

19.0.1.0.0 shipped four placeholder lines (Advance 30, BRD Approval 20, UAT
Sign-off 30, Go-Live 20). The business then named the real set: Advance, BRD
Approval, After Sandbox Review, Before UAT, After UAT, Before First User
Onboarding, Final Project Handover. The data file is noupdate, so an upgrade
alone would leave the old lines in place and ADD the five new xmlids next to
them (a nine-line template well over 100%).

Pre-migration, so it runs before the data file is loaded:
* template still exactly the placeholder set -> its lines and their xmlids are
  deleted; the loader then recreates the whole seven-line plan;
* template edited by hand -> the edited lines are moved to a copy named
  "<name> (edited)" and their xmlids dropped, so the standard template is
  emptied for the loader and nothing the user typed is lost.
Plain SQL: the registry is not available in a pre-migration.
"""
import logging

_logger = logging.getLogger(__name__)

MODULE = "ft_implementation_milestone"
PLACEHOLDER = {("Advance", 30.0), ("BRD Approval", 20.0),
               ("UAT Sign-off", 30.0), ("Go-Live", 20.0)}


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT res_id FROM ir_model_data
         WHERE module = %s AND name = 'milestone_template_standard'
           AND model = 'ft.milestone.template'
    """, (MODULE,))
    row = cr.fetchone()
    if not row:
        return
    template_id = row[0]
    cr.execute("""
        SELECT id, name->>'en_US', percentage
          FROM ft_milestone_template_line WHERE template_id = %s
    """, (template_id,))
    lines = cr.fetchall()
    if not lines:
        return
    line_ids = tuple(line[0] for line in lines)
    current = {(name, float(pct or 0)) for _id, name, pct in lines}
    if current == PLACEHOLDER:
        cr.execute(
            "DELETE FROM ft_milestone_template_line WHERE id IN %s", (line_ids,))
        _logger.info("%s: placeholder template lines replaced by the named "
                     "milestones.", MODULE)
    else:
        cr.execute("""
            INSERT INTO ft_milestone_template
                   (name, sequence, active, description, total_percentage,
                    create_uid, create_date, write_uid, write_date)
            SELECT jsonb_build_object('en_US', (name->>'en_US') || ' (edited)'),
                   sequence + 1, active, description, total_percentage,
                   create_uid, create_date, write_uid, write_date
              FROM ft_milestone_template WHERE id = %s
         RETURNING id
        """, (template_id,))
        copy_id = cr.fetchone()[0]
        cr.execute("""
            UPDATE ft_milestone_template_line SET template_id = %s
             WHERE id IN %s
        """, (copy_id, line_ids))
        _logger.info("%s: edited template lines kept on a copy (id %s); the "
                     "standard template receives the named milestones.",
                     MODULE, copy_id)
    # Drop the lines' xmlids either way, so the loader creates fresh records
    # for every line of the data file (including the two reused names).
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = %s AND model = 'ft.milestone.template.line'
           AND res_id IN %s
    """, (MODULE, line_ids))
