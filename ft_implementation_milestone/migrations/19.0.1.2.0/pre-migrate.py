# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
"""Flatten the milestone templates: one ft.milestone.template per milestone.

Up to 19.0.1.1.0 a template was a parent plan ("Standard Implementation")
holding ft.milestone.template.line rows with percentages. From 19.0.1.2.0 the
template IS the milestone (name, order, delivery stage, description) and
carries no percentage. This pre-migration, SQL only (no registry yet):

* copies every template line into ft_milestone_template as its own record,
  in plan order, keeping one record per name (first wins);
* deletes the old parent records (their lines go with them) and drops the
  line table and the plan-only columns;
* re-points the xmlids: the old parent / line xmlids are dropped and the new
  per-milestone xmlids of data/milestone_template_data.xml are attached to
  the migrated records that bear the same name, so the (noupdate) data file
  neither duplicates nor overwrites what the user has.
Percentages are not carried over on purpose: they are agreed per project.
"""
import json
import logging

_logger = logging.getLogger(__name__)

MODULE = "ft_implementation_milestone"
# Milestone name (en_US) -> xmlid in data/milestone_template_data.xml.
STANDARD_XMLIDS = {
    "advance": "milestone_template_advance",
    "brd approval": "milestone_template_brd",
    "after sandbox review": "milestone_template_sandbox",
    "before uat": "milestone_template_before_uat",
    "after uat": "milestone_template_after_uat",
    "before first user onboarding": "milestone_template_onboarding",
    "final project handover": "milestone_template_handover",
}


def _table_exists(cr, table):
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,))
    return bool(cr.fetchone())


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = %s AND column_name = %s
    """, (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version or not _table_exists(cr, "ft_milestone_template_line"):
        return
    if not _column_exists(cr, "ft_milestone_template", "stage_key"):
        cr.execute("ALTER TABLE ft_milestone_template ADD COLUMN stage_key varchar")

    cr.execute("SELECT id FROM ft_milestone_template")
    parent_ids = tuple(row[0] for row in cr.fetchall())

    # Lines in plan order; one record per (lower-cased en_US) name.
    cr.execute("""
        SELECT l.id, l.name, l.stage_key, l.description, t.active
          FROM ft_milestone_template_line l
          JOIN ft_milestone_template t ON t.id = l.template_id
         ORDER BY t.sequence, t.id, l.sequence, l.id
    """)
    new_ids_by_name = {}
    sequence = 10
    for _line_id, name, stage_key, description, active in cr.fetchall():
        key = ((name or {}).get("en_US") if isinstance(name, dict) else name) or ""
        key = key.strip().lower()
        if not key or key in new_ids_by_name:
            continue
        cr.execute("""
            INSERT INTO ft_milestone_template
                   (name, sequence, active, stage_key, description,
                    create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, %s, %s, %s, 1, now(), 1, now())
         RETURNING id
        """, (json.dumps(name) if isinstance(name, dict) else name,
              sequence, bool(active), stage_key, description))
        new_ids_by_name[key] = cr.fetchone()[0]
        sequence += 10

    # The old parents go (the lines cascade), then the line table itself.
    if parent_ids:
        cr.execute("DELETE FROM ft_milestone_template WHERE id IN %s", (parent_ids,))
    cr.execute("DROP TABLE ft_milestone_template_line CASCADE")
    for column in ("total_percentage",):
        if _column_exists(cr, "ft_milestone_template", column):
            cr.execute("ALTER TABLE ft_milestone_template DROP COLUMN %s" % column)

    # xmlids: drop the old ones, attach the new per-milestone ones by name.
    cr.execute("""
        DELETE FROM ir_model_data
         WHERE module = %s
           AND model IN ('ft.milestone.template', 'ft.milestone.template.line')
    """, (MODULE,))
    attached = 0
    for key, xmlid in STANDARD_XMLIDS.items():
        res_id = new_ids_by_name.get(key)
        if not res_id:
            continue
        cr.execute("""
            INSERT INTO ir_model_data
                   (module, name, model, res_id, noupdate,
                    create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, 'ft.milestone.template', %s, true, 1, now(), 1, now())
        """, (MODULE, xmlid, res_id))
        attached += 1
    _logger.info(
        "%s 19.0.1.2.0: %s milestone template(s) flattened from %s plan(s); "
        "%s standard xmlid(s) re-attached, the data file creates the rest.",
        MODULE, len(new_ids_by_name), len(parent_ids), attached)
