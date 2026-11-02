# Project Date Extension (`project_date_extension`)

Approval workflow to reschedule a project's planned lifecycle dates.

## Raising a request (PM)

1. **Project** and its **Current Stage** (read-only).
2. **Stage to be Extended** — dropdown of the project's lifecycle stages from the
   current stage onward (only stages whose planned date is set on the project).
   Choosing a stage selects its planned date automatically.
3. **Current Date** — the planned date of that stage, i.e. the date by which the
   project must have **reached** it (frozen when the stage is chosen).
4. **Rescheduled Date** — the new planned date.
5. **Extension Days** — computed, `Rescheduled − Current`, signed. Negative means a
   **Preponement**.
6. **Impact on later dates** — preview of every later planned date and where approval
   will move it.

Stage → planned date (`STAGE_PLANNED_DATE_FIELD` in
`models/project_date_extension_request.py`, helper `_stage_planned_date_field(stage)`;
keyed by upper-cased stage name). A stage's date is the date the project must have
reached that stage by — its planned start — exactly as the dates are named on the
project form and as `bt_project_customization.FT_OVERDUE_MILESTONES` (plus
`ft_project_lifecycle._ft_overdue_milestones()` for DATA) reads them for the Overdue
flag. One set of dates, one meaning: the form, the Overdue flag, this screen and the
stage report all agree, and a test keeps the two maps from drifting.

| Stage | Planned date moved (the date the stage must be reached by) |
|---|---|
| KICKOFF | Start Date (`date_start`) |
| DISC | Kick-off Date (`kick_start_meeting_date`) |
| DEV | BRD Approval Date (`brd_approval_date`) |
| REG | Regression Date (`ft_regression_date`) |
| SRV | Sandbox Review Date (`sandbox_review_date`) |
| UAT | UAT Start Date (`uat_start_date`) |
| DATA | Data Upload Date (`pl_data_upload_date`) |
| TRA | Training Date (`ft_training_date`) |
| SUPPORT | Support Start Date (`support_start_date`) |
| CLOSED | Closed Date (`date`) |

Before 19.0.1.7.0 the map paired each stage with the *next* stage's date ("planned
end of the stage": DEV → Regression Date, REG → Sandbox Review Date, …), so the request
screen showed a stage under the wrong name. The 19.0.1.7.0 migration re-derives
`stage_to_extend_id` on every existing request from the date it actually moves.

Go Live Date and Support End Date are no stage's date. They, and projects with no
applicable stage (AMC / General), are reachable through the **Date to Extend**
picker, which the form always shows: it is filled in and locked while a stage is
chosen, and picked by hand (leave the stage empty) otherwise. `date_to_extend_id`
stays the field approval moves; `stage_to_extend_id` fills it.

## Extension vs preponement

| | Extension (`extension_days > 0`) | Preponement (`is_preponement`) |
|---|---|---|
| Selected date | set to the Rescheduled Date | set to the Rescheduled Date |
| Later planned dates | all set ones shift forward by the same days | **not moved** |
| `delay_days` (what reports sum) | = extension days | 0 |
| Order check | skipped (the whole tail moves together) | enforced: the new date may not fall before the previous set lifecycle date (`ValidationError` at submit and at approval) |

## Approval

Approvers (group *Date Extension Approver*) approve / reject through the decision
wizard (comment required; the approver may adjust the **Approved Rescheduled Date**).
The shift is measured against the project's **live** date at approval time: if the date
moved between request and approval, `current_date` is refreshed first, so later dates
move by the real gap and `extension_days` / `delay_days` record what actually happened.

`delay_days` is arithmetic on every request regardless of state; reports should
filter `state = 'approved'`.

## Tests

`odoo -c <conf> -d <test_db> -i project_date_extension --test-tags /project_date_extension --stop-after-init`

The suite looks the Implementation stages up by name and skips itself when they or the
lifecycle date fields are not installed.
