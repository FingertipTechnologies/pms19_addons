"""Take the "Include Archived" default off the opportunity actions again.

19.0.1.3.12 shipped a crm_action_overrides.xml that rewrote the context of
three core window actions (crm.crm_lead_action_pipeline,
crm.crm_lead_opportunities, crm.crm_case_form_view_salesteams_opportunity)
to add ``'search_default_include_archived': 1``. That release was reverted,
but those records belong to the crm / sale_crm modules, so dropping our file
does not put their old context back: any database upgraded while .12 was
installed keeps opening the pipeline with archived records included.

This strips just that one key from every crm.lead window action that still
carries it and leaves everything else in the context untouched, so a context
someone else may have edited since is preserved. Databases that never ran
.12 simply match nothing. ``version`` is falsy on a fresh install, where there
is nothing to undo.
"""
import re

KEY_PATTERN = re.compile(r"\s*'search_default_include_archived'\s*:\s*[^,}]+,?")


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        SELECT id, context
          FROM ir_act_window
         WHERE res_model = 'crm.lead'
           AND context LIKE '%%search_default_include_archived%%'
    """)
    for action_id, context in cr.fetchall():
        cleaned = KEY_PATTERN.sub('', context)
        cr.execute("UPDATE ir_act_window SET context = %s WHERE id = %s", (cleaned, action_id))
