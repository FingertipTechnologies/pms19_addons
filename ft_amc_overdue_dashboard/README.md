# FT AMC Task Overdue Dashboard

One table of every task on an AMC project, with how old each task is and how
many days it is past its **original** deadline, so the AMC team can see at a
glance what is slipping and by how much - and, for finished work, how late it
was delivered.

## Where it is

**Dashboards > Project** (the Project Dashboard of `ft_project_dashboard`),
as the **AMC Task Overdue** table below *Implementation Stages* and above
*Resource Status*. It has no menu of its own: it is a section of that board,
and the board's header **Project** and **Project Manager** pickers narrow it
exactly as they narrow every other section (the period picker does not apply:
overdue is a state, not an activity in a date range).

## What it shows

A one-line summary beside the table's tools, in place of KPI tiles:
`12 tasks · 7 overdue · 93 overdue days · as of 2026-10-28`.

| Figure | Meaning |
| --- | --- |
| tasks | Tasks in the table under the current filters (before the text search) |
| overdue | Of those, tasks with an Overdue Days figure (past their original deadline); also shown as the count badge on the *Overdue only* toggle |
| overdue days | Sum of Overdue Days over the table |

The table, one row per task:

| Column | Definition |
| --- | --- |
| Project Name | The AMC project the task belongs to |
| Task Name | The task; opens the task form |
| Stage | The task's current stage |
| Original Deadline | The first deadline the task was given (*Original Deadline* on the task, set once and never overwritten), as a calendar day in your timezone. This is what Overdue Days is measured from |
| Current Deadline | The task's Deadline as it stands today, i.e. after any revisions, as a calendar day in your timezone |
| Total Days | The task's age: whole calendar days since it was created, in your timezone (0 on the day of creation). The same figure as *Age (Days)* on the task list. For a completed task the age stops on the day it was completed |
| Overdue Days | Open task: calendar days from the Original Deadline day to today. Completed task: the figure frozen on the day it was completed (see below). Blank when the task is not yet past its original deadline, has no deadline, or was completed on time |

Rows are ordered most overdue first, then oldest; rows with no Overdue Days
come last.

### Original vs current deadline

Overdue is always counted from the **original** deadline, never from the
latest revised one, so moving a deadline out never makes a task look less late.
Every revision is still kept: the task's *Deadline Changes* log
(ft_pms_planning_workflow) and the chatter tracking on *Deadline* record each
change, and *Current Deadline* shows where the task stands now.

The original deadline is read-only and locked: once set, a write that would
change it is refused (except for system code running as superuser). For tasks
created before deadline tracking existed, installing this module recovers the
original deadline from the chatter's earliest *Deadline* change (the value the
task had before its first revision), or takes the current deadline when the
deadline was never changed.

### Completed tasks: a frozen figure

When a task is completed (moved into a Completed / folded stage, or closed by
the auto-complete cron), the number of calendar days from its original
deadline day to its completion day is stamped on the task as *Overdue at
Completion (Days)* (`ft_historical_overdue_days`) and never changes afterwards.
Overdue accumulation stops at completion.

Example: created 7 Sep, original deadline 10 Sep, deadline revised to 15 Sep,
completed 17 Sep: Overdue Days = 7, and still 7 when the board is opened in
October. Completed on or before the original deadline: blank.

Only if the task is reopened and completed again is the figure recomputed, for
the new completion day. Installing the module stamps the figure on every task
that was already completed.

Filters:

- **Project** and **Project Manager** (the dashboard's header pickers) - the
  table lists only the tasks of the picked project, or of the projects the
  picked manager runs (the *Project Manager* on the project form, whoever the
  tasks are assigned to). An Implementation or General project picked in the
  header leaves the table empty: only AMC projects are ever in scope.
- **Search** - narrows the table to rows whose project name or task name
  contains the text.
- **Overdue only** - keep only rows with an Overdue Days figure.
- **Include completed** - also list completed tasks (Status Done, or Deployed
  - `1_deployed`, the status `ft_amc_payment_milestone` adds after Done) with
  their frozen figure. Cancelled tasks are never listed, with or without this
  filter. Deploying a task does not re-stamp its figure.

Archived tasks, archived projects and task templates are never listed. Only
projects whose *Project Type* is **AMC** are in scope - Implementation and
General projects never appear, whatever their stage.

All day counts are local calendar days in the user's timezone, never UTC days,
following ft_task_hours_tracker's rule for task age and overdue checks. The
frozen figure of a completed task is counted in the timezone of whoever (or
whichever cron) completed it; the install-time backfill uses the company's
timezone, falling back to the administrator's.

## Who can see it

Whoever can open the Project Dashboard: its *Dashboards* menu is limited to
system administrators. The data provider (`ft.amc.overdue.dashboard`) itself
stays readable by *AMC Reporting Manager* (ft_amc_monthly_timesheet) and
*Project Manager* (Project > Administrator) as well, so another client could
call it for those groups. Record rules still apply - the table only ever
lists projects and tasks the person could open themselves.

## Install / upgrade

Depends on `project`, `bt_project_customization`, `ft_task_hours_tracker`,
`ft_pms_planning_workflow`, `ft_amc_monthly_timesheet` and
`ft_project_dashboard`.

1. Put the `ft_amc_overdue_dashboard` folder in the addons path.
2. Apps > Update Apps List, then install **FT AMC Task Overdue Dashboard**, or

       odoo-bin -d <db> -i ft_amc_overdue_dashboard

3. Later upgrades:

       odoo-bin -d <db> -u ft_amc_overdue_dashboard

   (the assets are rebuilt by the upgrade; a hard refresh of the browser may
   be needed afterwards). Upgrading from 19.0.1.1.0 removes the old
   *PMS > AMC Reports > Overdue Dashboard* menu and its client action.

The install runs a `post_init_hook` (`hooks.py`) that backfills the original
deadline of tasks that have none (from the chatter's deadline tracking: the
value before the first change, else the current deadline) and stamps *Overdue
at Completion (Days)* on every task already completed. Since 19.0.1.3.0 the
same backfill also runs on every upgrade (`migrations/19.0.1.3.0`), so a
database where the install hook did not take - every row then shows the
current deadline under *Original Deadline*, the fallback - is repaired by
`-u ft_amc_overdue_dashboard`. To run it by hand (for instance after
importing historical tasks), from an Odoo shell:

    from odoo.addons.ft_amc_overdue_dashboard.hooks import post_init_hook
    post_init_hook(env); env.cr.commit()

*Original Deadline* and *Current Deadline* are the same for a task whose
deadline was never changed; they differ only once the deadline has been
moved (the chatter and the task's Deadline Changes log keep the history).

Tests: `odoo-bin -d <db> -u ft_amc_overdue_dashboard --test-enable --test-tags /ft_amc_overdue_dashboard --stop-after-init`.
