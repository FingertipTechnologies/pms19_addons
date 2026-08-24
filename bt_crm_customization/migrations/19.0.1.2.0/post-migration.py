"""Backfill the new business "Created Date" on the leads that predate the field.

``lead_created_date`` is introduced in 19.0.1.2.0 with a default of "today", and
Odoo writes that default into every existing row when it adds the column - so
without this every lead already in the database would claim it was created on
the day of the upgrade. They are re-stamped from the technical ``create_date``,
which is the value the default would have produced had the field always been
there.

The overwrite is unconditional on purpose: the field is brand new at this
version, so any value present is the default Odoo has just written, never
something a user typed. `version` is falsy on a fresh install (no rows to fix).
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE crm_lead
           SET lead_created_date = create_date::date
         WHERE create_date IS NOT NULL
           AND (lead_created_date IS NULL
                OR lead_created_date != create_date::date)
    """)
