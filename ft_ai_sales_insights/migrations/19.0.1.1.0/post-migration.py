"""Restore noupdate protection after the data file refreshed the purposes.

Counterpart to pre-migration: once this upgrade has rewritten the project
purposes, put the guard back so future upgrades again leave admin-edited
prompts alone.
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        UPDATE ir_model_data
           SET noupdate = true
         WHERE module = 'ft_ai_sales_insights'
           AND model = 'ft.ai.insights.purpose'
           AND name LIKE 'purpose_project_%%'
        """
    )
