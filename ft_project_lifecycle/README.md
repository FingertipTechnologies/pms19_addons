# Project Lifecycle (`ft_project_lifecycle`)

Adds a **Project Type** to `project.project` and drives a project-level Kanban
stage lifecycle from it, plus milestone dates.

## What it does

| # | Requirement | Implementation |
|---|-------------|----------------|
| 1 | Project Type field (General / Implementation / AMC) | Owned by `bt_project_customization` as `ft_project_type`. This module reads it and does **not** declare one of its own. |
| 2 | Project-level Kanban stages DISC, DEV, REG, SRV, UAT, DATA, TRA, SUPPORT, Started, Working, Completed, CLOSED | `project.project.stage` records in `data/`. The *Project Stages* feature is switched on for every project user, so Projects Kanban is grouped by these stages. |
| 3 | Milestone date fields | Folded into the existing PMS **Dates** group (from `ft_task_hours_tracker`). The genuinely new dates (Regression, Data Upload, Training, Support End, Hold, AMC) are `pl_*` fields; the rest reuse the fields already shown there (Kick Start Meeting Date is relabelled **Kick-off Date**, End Date → **Closed Date**). |
| 4 | Auto Start Date on creation | `create()` defaults `date_start` to the creation date. |
| 5 | Backfill Start Date for existing projects | `post_init_hook` sets `date_start` from `create_date` where empty. |
| 6 | Full DISC→…→SUPPORT only for Implementation | Stages flagged `pl_for_implementation`; enforced by the stage domain + a constraint. |
| 7 | Flow for General | **Started → Working → Completed** (plus CLOSED). |
| 8 | AMC-specific flow | **Started → Working → Completed** (plus CLOSED), never the Implementation stages. |
| 9 | No Implementation→AMC conversion | `write()` blocks changing an Implementation project's type to AMC. |
| 10 | End Date reused as Closed Date | The core `date` field is relabelled **Closed Date** and auto-stamped when a project reaches CLOSED. |
| 11 | Kanban arrow to open the form | An arrow button (`type="open"`) added to each project card. |

## Design decisions worth confirming

- **Started / Working / Completed are one shared set of three records**, flagged
  for both General and AMC, not two parallel sets. The Projects Kanban is a
  single board, so duplicating them would show two identical "Started" columns;
  the Project Type filter is what separates the two. Which stage applies to
  which type is fully data-driven via the `pl_for_general /
  pl_for_implementation / pl_for_amc` flags on `project.project.stage`, so this
  is adjustable without code.
- **CLOSED is shared by all three types.** It is not part of any workflow — a
  project is archived *from* wherever it was — so it carries all three flags.

- **Being parked is a checkbox, not a stage.** `pl_on_hold` on the project form,
  beside Project Type. HOLD was a stage every type could reach, which meant
  parking a project overwrote the stage it was parked *from* — the one fact
  needed to resume it, recoverable only by reading chatter by hand. A flag sits
  alongside `stage_id`, so a project is "in DEV *and* parked" and comes back to
  DEV on its own. `pl_hold_date` follows the flag in both directions, cleared on
  the way out so a second hold stamps a fresh date.

  The HOLD stage record is **archived and stripped of its three type flags,
  never deleted**: seven tables carry a foreign key to `project.project.stage`,
  including the frozen `project_status` on ~20,000 timesheet lines.
  `hooks.move_hold_stage_to_flag` empties it first, recovering each parked
  project's pre-hold stage from `mail_tracking_value` (11 of the 19 parked
  projects on the live copy) and falling back to the Project Type's first stage
  for the rest — every fallback named in the log.
- **Every pre-existing project is migrated onto the new stages by Project Type**
  (`hooks.migrate_existing_stages`), not just the four core defaults. Each
  project's previous stage is first copied into the permanent `ft_pl_stage_backup`
  table, so the whole move is reversible with a single `UPDATE ... FROM`. The old
  stages are **archived, never deleted** — timesheet lines hold a frozen
  `project_status` pointing at them.
