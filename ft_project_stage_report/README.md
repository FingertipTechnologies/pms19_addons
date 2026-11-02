# FT Implementation Project Stage Report

Stage-wise report for **Implementation** projects
(`project.project.ft_project_type == 'implementation'`): for every project and
every Implementation stage (KICKOFF, DISC, DEV, REG, SRV, UAT, DATA, TRA,
SUPPORT, CLOSED) one line with the planned date, the actual entry / exit
dates, **Days Worked**, **Overdue Days** and **Extension Days**.

Where: shown inside **Dashboards > Project** (the Project Dashboard of
`ft_project_dashboard`, administrators) as the **Implementation Stages**
section, right after *Project Performance*. There is no menu of its own (the
former *Project > Implementation Report* menus were removed in 19.0.1.1.0).

Since 19.0.1.2.0 the section is a **matrix**: one row per Implementation
project, one column per lifecycle stage in pipeline order (the stages come
with the data, nothing is hard-coded), and a **Total** column. The Project
cell carries the Project Manager's name under the project name. A
**Days Worked / Overdue Days** switch in the table chooses the number each
stage cell shows:

- **Days Worked** - the days the project spent in the stage (`6d`), `—` while
  the stage was never entered. A cell is red when that stage is overdue. Total
  = sum of Days Worked, with a small red *overdue* caption when any stage is.
- **Overdue Days** - only the excess days of the stage (`3d`, red), `—` when
  it is on time. Total = sum of Overdue Days, red when > 0, with an *overdue*
  caption (grey *0d overdue* when clean).

The project's current stage is bold with an indigo dot; every stage cell has a
hover tooltip with the reach-by (planned), entered and exited dates and the
extension days. Above the grid three figures summarise the rows shown: **Projects**,
**Total overdue days** (**Total days worked** in Days Worked mode) and
**Projects overdue**. The table follows the board's Project and Project
Manager pickers, has its own search over project / manager names (the
summary follows it), an **Include closed** toggle (projects in the CLOSED
stage and archived projects are hidden by default; included ones are dimmed)
and the Project header flips the name order. Clicking a row opens the
project. The switch and the toggle survive the round trip to a project form
(`sessionStorage`).

Data: `ft.project.stage.line.get_dashboard_matrix(scope)` returns the ordered
stage list and, per project, its totals and a cell per stage keyed by stage
id. `get_dashboard_rows(scope)` (one flat row per project + stage) remains
for list-shaped consumers; both go through the same scope helper
(`_dashboard_scope_lines`), so they always agree on which projects are in.

The list / pivot / graph views of `ft.project.stage.line` still exist behind
the two actions `action_ft_project_stage_report_days` /
`action_ft_project_stage_report_delays`: the project form carries a **Stage
Report** smart button (Implementation projects only) opening the project's
lines through the first one, and **Total Extension Days** under the Actual
Stage Dates group. The search view offers *Current Stage Only*, *Overdue
Stages*, *Extended Stages* and *Entered Stages* filters and groups by project /
stage.

## Definitions

| Column | Definition |
| --- | --- |
| Planned Date | The date by which the project must **reach** the stage, i.e. the date of the same name on the project form (`project_date_extension.STAGE_PLANNED_DATE_FIELD`): KICKOFF -> Start Date, DISC -> Kick-off Date, DEV -> BRD Approval Date, REG -> Regression Date, SRV -> Sandbox Review Date, UAT -> UAT Start Date, DATA -> Data Upload Date, TRA -> Training Date, SUPPORT -> Support Start Date, CLOSED -> Closed Date. It is read live from the project at every rebuild, so an approved Date Extension Request (which moves that project date and the later ones) is reflected: the planned dates here are the dates *after* approved extensions, and Extension Days shows how much each stage was extended. Go Live Date and Support End Date belong to no stage. |
| Actual Entry Date | The date the project first entered the stage (`pl_actual_<key>_date`, stamped by `ft_project_stage_dates`). Empty while it never has. |
| Actual Exit Date | The actual entry date of the next stage the project entered. Empty for the current stage. When nothing later was entered although the project sits in a later stage (imported data), the current stage's entry date when it is later than this one's, else today. |
| Current Stage | The project is in this stage now. |
| Days Worked | Calendar days the project spent in the stage: *exit date - entry date*, or *today - entry date* while it is the current stage. 0 when the stage was never entered. |
| Overdue Days | **Extension Days of the stage**: the Delay Days of the approved Date Extension Requests that targeted the stage (see below). Nothing else is counted: a stage with no approved extension is 0, whatever its planned date. |
| Extension Days | Sum of the **Delay Days** of the *approved* Date Extension Requests whose *Stage to be Extended* is this stage (`delay_days = max(extension_days, 0)`, so a preponement counts 0). A legacy request raised by date only is attributed to the stage that date belongs to. |
| Total Extension Days (project) | `project.project.pl_total_extension_days`: the sum of the Delay Days of the project's approved requests = the sum of Extension Days over its stage lines. Stored; recomputed whenever a request's state or delay days change. |

### Overdue example

Project in SUPPORT, today 28 Oct, no extensions: Kick-off Date 8 Apr, DISC
entered 10 Apr -> DISC **2**; Data Upload Date 19 Jul, DATA entered 15 Sep
-> DATA **58**; Support Start Date 23 Sep, SUPPORT entered 12 Oct -> SUPPORT
**19**; Closed Date 9 Oct, not reached -> CLOSED **19**; REG never entered
(skipped) -> 0. Total **98**. In the matrix the DISC, DATA, SUPPORT and
CLOSED cells are red.

### Extensions are overdue days

When a project cannot reach its next stage by the planned date, the Project
Manager raises a Date Extension Request on that stage and an Administrator
approves it (an overdue Implementation project cannot change stage at all
until then, see `ft_pms_planning_workflow`). The approved **Delay Days** are
the delay of that stage, so they are reported as its Overdue Days - the
extension moves the planned date, but it does not make the project on time.

Project in DEV, Regression Date (REG's reach-by date) 1 Jun:

1. A request on **REG**, +10 days, is approved on 25 May: Regression Date
   becomes 11 Jun. From the approval on, REG shows Extension **10**, Overdue
   **10** (the project is not in REG yet, and it is not past 11 Jun, so
   nothing comes on top).
2. REG is entered on 11 Jun, the extended date: Overdue stays **10**.
3. REG is entered on 14 Jun instead: Overdue **13** (10 extended + 3 days
   late even against the extended date).
4. No request was raised and the project sits in DEV on 5 Jun: Overdue
   **4** (today - 1 Jun), growing daily until the stage is reached or an
   extension is approved - whose days then replace that figure.

### No double counting

An approved extension of a stage shifts every later planned date by the same
number of days. Only the gap *requested on the targeted stage* is counted, on
that stage; the downstream shifts are never counted again on their own
stages.

Worked example - project in DISC, planned dates in step order:

1. Request on **DISC**, +3 days, approved: Kick-off Date moves by 3 and so
   do BRD Approval, Regression, ... Closed Date. Report: DISC 3, DEV 0,
   REG 0, ... Total 3; every later Planned Date is 3 days later.
2. Request on **DEV**, +5 days, approved: BRD Approval Date moves by 5 and so
   do the later dates. Report: DISC 3, **DEV 5**, REG 0, SRV 0, ... **Total 8**
   (not 3 + 8 + 8 + ...).
3. A preponement on REG (-1 day) is approved: it moves only the Regression
   Date and counts 0. Total stays 8.

The Overdue Days follow the same attribution: DISC 3, DEV 5, REG 0, total 8
(nothing else is added).

## When the lines are rebuilt

The lines are plain stored rows (not computed fields), because Days Worked of
the current stage and Overdue Days of the next stage not yet reached grow by
one every day while nothing on the project changes, and the pivot / graph need
stored values. They are deleted
and recreated by `ft.project.stage.line._rebuild_for_projects()`:

- on install (`post_init_hook`), for every Implementation project;
- nightly by the cron *Implementation stage report: refresh days* (01:00
  server time), for every Implementation project, archived ones included;
- when a project is created, or written with its stage, its project type, an
  actual entry date or a planned reach-by date (Start Date and Closed Date
  included; a project that stops being an Implementation project loses its
  lines);
- when a Date Extension Request becomes approved, or an approved one is
  changed, moved or deleted;
- on demand with the **Refresh** button in the report list (smart button
  views); the dashboard table refetches on every board reload.

The rebuild runs with sudo. Lines are readable by Project users, writable by
Settings administrators only, and restricted to the user's companies.
