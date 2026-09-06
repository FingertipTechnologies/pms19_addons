"""Backfill ft_regression_date/ft_training_date from the retired pl_regression_date/
pl_training_date before the fields disappear from the model.

This version drops ``pl_regression_date``/``pl_training_date`` in favour of
bt_project_customization's ``ft_regression_date``/``ft_training_date`` (see
models/project_project.py) — two fields with the same label ("Regression
Date" / "Training Date") existed side by side on the form, one filled by
users, the other checked by Stage Validation, so a project could show a date
and still be told the date was missing. Any project that already has a value
in the old field but not the new one needs it copied across here, before the
old columns become unreachable through the ORM.

Pre, not post: both columns already exist at this point (bt_project_customization
loads first and its ft_regression_date/ft_training_date columns predate this
migration), and running as SQL means it doesn't depend on either field still
being registered on the model.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'project_project'
           AND column_name IN ('pl_regression_date', 'pl_training_date',
                                'ft_regression_date', 'ft_training_date')
    """)
    present = {row[0] for row in cr.fetchall()}
    if {'pl_regression_date', 'ft_regression_date'} <= present:
        cr.execute("""
            UPDATE project_project
               SET ft_regression_date = pl_regression_date
             WHERE ft_regression_date IS NULL
               AND pl_regression_date IS NOT NULL
        """)
    if {'pl_training_date', 'ft_training_date'} <= present:
        cr.execute("""
            UPDATE project_project
               SET ft_training_date = pl_training_date
             WHERE ft_training_date IS NULL
               AND pl_training_date IS NOT NULL
        """)
