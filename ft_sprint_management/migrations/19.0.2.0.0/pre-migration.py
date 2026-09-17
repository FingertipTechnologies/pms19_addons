"""Turn the existing Sprints into Weeks.

Runs before the new field definitions are applied, on the columns as they
already stand:

  * ``start_date`` becomes required, so any row still missing one would block
    the NOT NULL that Odoo adds. They are given the Monday of their end date,
    or of today when neither is set.
  * A week runs Monday to Sunday. Sprints were free to start on any day and
    ended seven days later (the following Monday), so every row is snapped
    back to its Monday and re-closed on the Sunday. ``end_date`` is a stored
    computed field: it is only recomputed when ``start_date`` is written
    through the ORM, so it is set here rather than left to drift.
  * "Sprint 1" reads "Week 1". Only the word is replaced, so any numbering or
    wording around it survives.
"""


def migrate(cr, version):
    if not version:
        return

    cr.execute("""
        UPDATE qa_testapp_sprint
           SET start_date = COALESCE(end_date, CURRENT_DATE)
         WHERE start_date IS NULL
    """)

    # date_trunc('week', ...) is the ISO week, which starts on Monday.
    cr.execute("""
        UPDATE qa_testapp_sprint
           SET start_date = date_trunc('week', start_date)::date,
               end_date = (date_trunc('week', start_date)
                           + INTERVAL '6 days')::date
         WHERE start_date IS NOT NULL
    """)

    cr.execute("""
        UPDATE qa_testapp_sprint
           SET name = regexp_replace(name, 'sprint', 'Week', 'gi')
         WHERE name ILIKE '%sprint%'
    """)
