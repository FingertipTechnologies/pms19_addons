# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Re-derive "Stage to be Extended" on existing Date Extension Requests.

19.0.1.7.0 changes which project date a stage extends. Until now
STAGE_PLANNED_DATE_FIELD paired a stage with the NEXT stage's date ("planned
end": DEV -> Regression Date, REG -> Sandbox Review Date, ...); it now pairs
it with the date by which the project must have REACHED the stage (DEV -> BRD
Approval Date, REG -> Regression Date, ...), the way the dates are named on
the project form and read by the Overdue flag.

On a request the DATE (date_to_extend_id) is the truth: it is what the
requester actually chose and what approval moved on the project. The stage
is only a label on it - and under the old pairing it was the wrong label (a
request that moved the Regression Date was tagged DEV; it is REG's date). So
every request that has a date gets its stage re-derived from that date under
the NEW map, replacing whatever 1.6.0 back-filled or the user picked. Dates
that are no stage's date any more (Go Live, Support End) get no stage; they
stay reachable through the legacy hand-picked date.

Plain SQL on purpose: stage_to_extend_id is what the stored computed
date_to_extend_id is derived FROM, so writing the stage through the ORM
would recompute the date from the new stage - the same row, but we want the
date untouched as a matter of principle - and both fields are tracked, so
the ORM would also post a tracking message on every historical request.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    from odoo.addons.project_date_extension.models.project_date_extension_request import (
        STAGE_PLANNED_DATE_FIELD,
        _stage_key,
    )
    # Invert the map: project date field -> normalised stage key. Then pick
    # the stage record for each key among ALL stages (archived included: an
    # old request may point at a retired stage, and its date must still
    # resolve); the first by (sequence, id) wins when two stages share a name.
    key_by_field = {fname: key for key, fname in STAGE_PLANNED_DATE_FIELD.items()}
    stage_by_key = {}
    stages = env["project.project.stage"].with_context(active_test=False).search(
        [], order="sequence, id"
    )
    for stage in stages:
        stage_by_key.setdefault(_stage_key(stage), stage)
    stage_by_field = {
        fname: stage_by_key[key]
        for fname, key in key_by_field.items()
        if key in stage_by_key
    }
    requests = env["project.date.extension.request"].search(
        [("date_to_extend_id", "!=", False)]
    )
    for req in requests:
        stage = stage_by_field.get(req.date_to_extend_id.field_name)
        new_id = stage.id if stage else None
        if new_id == (req.stage_to_extend_id.id or None):
            continue
        cr.execute(
            "UPDATE project_date_extension_request SET stage_to_extend_id = %s WHERE id = %s",
            (new_id, req.id),
        )
