# Project Stage Dates (`ft_project_stage_dates`)

KICKOFF stage, automatic **actual** stage-entry dates and the **Technical
Architect** planning-date rights for Implementation projects.

## Install / upgrade

- **Depends on:** project, mail, bt_project_customization, ft_task_hours_tracker,
  ft_project_lifecycle, project_date_extension, ft_pms_planning_workflow.
- **Install:** `odoo -c <conf> -d <db> -i ft_project_stage_dates`
  (also upgrade `bt_project_customization`, which gains the `kickoff` stage key:
  `-u bt_project_customization`).
- **Tests:** `odoo -c <conf> -d <test_db> -i ft_project_stage_dates --test-tags /ft_project_stage_dates --stop-after-init`
- **After install,** add the architects to Settings > Users > Project > *Technical Architect*.

## What it does

| # | Requirement | Implementation |
|---|---|---|
| R1 | A KICKOFF stage before DISC; new Implementation projects start in it | `data/project_project_stage_data.xml`: stage **KICKOFF**, sequence 5, `pl_for_implementation`. `ft_project_lifecycle.create()` homes a new project on the lowest-sequence stage of its type, so a new Implementation project lands in KICKOFF with no further code. **Existing projects are not moved.** Classified as key `kickoff` (`bt_project_customization.FT_STAGE_MARKERS`); no entry date requirement, no stage gate. Leaving it for DISC needs what DISC always needed: a Kick-off Date and a milestone. |
| R2 | Capture the actual date a project enters each stage | `pl_actual_<key>_date` for `kickoff, disc, dev, reg, srv, uat, data, tra, support, closed` ("KICKOFF Entered On", ...). Stamped with today (user timezone) on create and on every `stage_id` / type change, **only when empty: the first entry is kept** when a project moves back and forward (the chatter keeps every move). |
| R3 | Actual dates are system-generated and read-only | Fields are `readonly`, `copy=False`, shown in a read-only "Actual Stage Dates" group under Dates (Implementation only). Server guard: any `create`/`write` naming one of them raises *"Actual stage dates are recorded automatically ..."* unless superuser or the stamping context (`pl_stamping_actual_dates`). |
| R4 | Technical Architect may edit the planned dates in early stages | Group **Technical Architect** (`group_technical_architect`, implies Project / User). `_check_date_edit_permission` (project_date_extension) lets a member edit the planned lifecycle dates directly while **every** project in the write is an Implementation project in **KICKOFF or DISC** (`EARLY_STAGE_KEYS`). The Date Extension Approver keeps its rights; everyone else still goes through the Date Extension Request flow. The form mirrors this through `ft_can_edit_project_dates`. |
| — | Backfill on install | `post_init_hook` fills the empty actual dates of existing Implementation projects from the `stage_id` chatter tracking (earliest message per project and stage key, read in the company timezone), then the current stage from the latest tracking date or the creation date, and DISC (the first stage that existed before KICKOFF) from the creation date for projects on or past it. KICKOFF is never backfilled from the creation date. Idempotent (`COALESCE`), logs counts. |

## Side effects worth knowing

- **Kick-off Date and Closed Date are now protected and sequenced.**
  `project_date_extension` matches its twelve steps by field *label*;
  `kick_start_meeting_date` ("Kick Start Meeting Date") and core `date`
  ("Expiration Date") never matched, so neither was protected nor held to the
  order. `_sequenced_date_fields` is overridden to add them by technical name
  at step 2 and step 12. Consequences:
  - a non-approver can no longer set them directly (before: silently allowed);
  - the step order now requires Start <= Kick-off <= BRD Approval and
    Support End <= Closed Date. The milestone -> Kick-off sync in
    `project_date_extension` writes with `skip_date_sequence_check`, so a
    Kick-off Date it set to a late milestone can sit after BRD Approval; such a
    project will be refused on its **next** edit of any lifecycle date until the
    dates are put back in order.
- **Closed Date stamping on CLOSED** (`ft_project_lifecycle._pl_stamp_lifecycle_dates`)
  is run under sudo and without the sequence check from this module, so a
  Project Manager who is not an approver can still close a project and a
  project closed before its planned Support End Date is not refused. The uid is
  unchanged, so the chatter still names the person who moved the stage.
- The five lifecycle dates `ft_project_lifecycle` adds to the Dates group
  (Regression, Data Upload, Training, Go Live, Support End) were editable in
  the form for everyone (the server refused the save); they now carry the same
  `readonly="not ft_can_edit_project_dates"` as the other seven.

## For other modules (stage report)

```python
from odoo.addons.ft_project_stage_dates.models.project_project import (
    PL_ACTUAL_STAGE_KEYS,   # ('kickoff', 'disc', 'dev', 'reg', 'srv', 'uat', 'data', 'tra', 'support', 'closed')
    PL_ACTUAL_DATE_FIELDS,  # {'kickoff': 'pl_actual_kickoff_date', ...}
    EARLY_STAGE_KEYS,       # ('kickoff', 'disc')
)
project._pl_actual_date_field('dev')   # 'pl_actual_dev_date' (False for an unknown key)
project._pl_actual_entry_dates()       # [(key, stage, date_or_False), ...] in pipeline order
project._pl_in_early_stage()           # Implementation project in KICKOFF / DISC
```

`backfill_actual_stage_dates(env)` in `hooks.py` can be re-run from `odoo shell`.
