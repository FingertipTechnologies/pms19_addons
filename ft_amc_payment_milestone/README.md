# AMC Payment Milestones (`ft_amc_payment_milestone`)

Monthly payment milestones for AMC projects (PMS requirements 36-50), built on
the existing `project.custom.milestone` model so they show in the project's
**Milestones** tab and in **Project > Milestones > Project Milestones**.

## Flow

```
1st of the month      cron creates "Support Services for <Month Year>" (status
                      Not Started) for every eligible AMC project - with or
                      without any work.

during the month      PM / TL / admin approve AMC tasks (existing Approve button),
                      approve the weekly timesheets, and mark completed tasks
                      "Deployed" (new, bulk-capable).
                      Approved + completed + Deployed  ->  task attached to the
                      milestone of its DEPLOYMENT month; its APPROVED timesheet
                      hours are counted there ("Hours").

7th (configurable)    cron marks the Not Started milestones of the previous
                      month Completed (send switch on), which
                        1. generates the task Excel and attaches it to the
                           milestone, then
                        2. e-mails the month's timesheet (PDF + Excel) and that
                           task Excel to the customer.
                      "Mark Completed & Send" does the same by hand, any time.

after                 Client Approved -> Invoice Raised -> Part Paid -> Paid
```

## Statuses

`Not Started -> Completed -> Client Approved -> Invoice Raised -> Part Paid -> Paid`

Keys: `not_started`, `completed`, `customer_approved` (label "Client
Approved"), `invoice_raised`, `partially_paid` (label "Part Paid"), `paid`.
The whole selection of `status` is re-stated by this module (a method
selection, so the ORM does not warn about an overridden list) because
`selection_add` cannot relabel a value; every key of
`project_custom_milestone` is kept, so `project_date_extension`
(`_DONE_STATUSES`) and `ft_ai_sales_insights` keep working. There is **no
internal approval step** any more (the `internal_approved` value of
19.0.1.0.0 is gone, see *Migration*).

* The sequence is **enforced only for AMC monthly milestones**
  (`is_amc_monthly`), one step at a time, or back to Not Started; Paid may
  also follow Invoice Raised directly. Every other milestone keeps today's
  free editing of the Status field (list and form).
* **Mark Completed & Send** and **Generate Task Excel** are reserved to the
  AMC report managers (`ft_amc_monthly_timesheet` MANAGER_GROUPS: AMC
  Reporting Manager, Project Manager group, Administrator) and the project's
  own Project Manager. The later steps are open to anyone who can edit
  milestones.
* **Completed means "sent"**: entering Completed generates the task Excel and
  sends the e-mail (see below); if the e-mail cannot be sent the status change
  is refused (manual) or left at Not Started with the error on the chatter
  (cron). A month with no deployed task completes without an e-mail and says
  so on the chatter (the Excel is still attached, with no task row).

## Naming

* Name: `Support Services for September 2026` (month name + year of the
  billing period)
* Milestone ID: `SS-2026-09`
* Due Date = last day of the billing month (never changed afterwards; it does
  not feed the project's Kick-off Date, unlike other milestones).
* One milestone per (project, month): `UNIQUE(project_id, amc_period_start)`.

## Eligibility (requirements 36, 37, 50)

A milestone is created for an **active AMC project** that is not a template,
not in the CLOSED stage, not On Hold, whose Start/End dates cover the month -
regardless of any task, timesheet, approval, deployment, or the project's
"Send monthly AMC timesheet" switch. Entry point:
`project.project._amc_ensure_monthly_milestone(period_start)` (idempotent,
sudo), used by:

* cron **AMC: Create Monthly Payment Milestones** (daily; ensures the current
  month, so running on the 1st or later is the same);
* the install hook (previous + current month);
* the **Create This Month's Milestone** button on the project's AMC Monthly
  Timesheet tab;
* the deployment link (month of the deployment).

## Deployed task status (requirements 46-49)

`project.task.ft_deployed` / `ft_deployed_date` / `ft_deployed_by_id`, set
only by **Mark Deployed** / **Undo Deployed** (task form header, bulk buttons
in the All Tasks list header, menu **AMC Reports > AMC Tasks to Deploy**).
Rules, all-or-nothing on a selection:

* AMC project, final (Completed) stage, not cancelled, not already deployed;
* rights: the people `_pwf_amc_is_global_approver` accepts (Administrator, PM /
  Project Coordinator jobs, Team Lead jobs) plus the project's Project Manager.
  QA cannot deploy. Direct writes of the three fields are refused.

### Deployed as a Status value (`state = '1_deployed'`)

"Deploy is different from completed": Deployed is also a value of the task's
standard **Status** (`project.task.state`), placed right **after Done**
(`In Progress, Changes Requested, Approved, Done, Deployed, Cancelled,
Waiting`). It is registered as a **closed** state (added to core project's
`CLOSED_STATES` at import), so `is_closed`, the Open / Closed filters, the
subtask / milestone / sale-order counters, task dependencies and the rotting
rules treat a deployed task exactly like a done one. `ft_deployed` stays the
source of truth; the Status follows it:

| Transition | `ft_deployed` | `state` | stage |
|---|---|---|---|
| **Mark Deployed** (Done task in a final stage) | True | `1_deployed` | unchanged (Completed), `date_end` untouched |
| **Undo Deployed** | False | `1_done` | unchanged |
| Reopen (task leaves a final stage) | False | `01_in_progress` (bt_project_customization, as for Done) | the new stage |
| Completed again later | False | `1_done` (bt_project_customization) | Completed |

Deployed is reachable **only through the buttons**: a direct write of
`state = '1_deployed'` (Status widget, multi-edit, import, RPC) is refused.
Moving a deployed task's Status to anything else (Done, In Progress,
Cancelled...) is an undo and goes through the Undo rules: allowed for the
same people as **Undo Deployed** (the flag is cleared, the milestone detached
while still open, then the requested status is written); refused otherwise.
Status widget: Deployed shows a cloud-upload icon in green
(`static/src/js/task_state_deployed.js` patches project's
`ProjectTaskStateSelection` maps; the value is deliberately not added to the
widget's dropdown). The Deployment badge (`ft_deploy_state`: Deployed / To
Deploy) is kept: "To Deploy" has no Status equivalent.

Other modules that read `state` treat `1_deployed` like `1_done`
(`ft_amc_overdue_dashboard`: completed task with its frozen overdue figure,
not re-stamped by the deployment; `bt_project_customization`: create / reopen
stamping). Upgrade: the 19.0.1.2.0 post-migration moves every task with
`ft_deployed` to `state = '1_deployed'`.

### Hours rule (requirement 49) - approved timesheets only

A task that is **AMC-approved, completed and Deployed** is attached
(`custom_milestone_id`) to the AMC milestone of the month it was marked
Deployed in (company time zone). The milestone's **Hours** (`amc_hours`,
mirrored into `hours_spent`) is the sum of the task's timesheet lines that
are **approved in the weekly timesheet review**
(`account.analytic.line.ft_approval_state == 'approved'`,
`ft_pms_planning_workflow`), employee set, whatever month they were logged
in - pending and rejected lines do not count. Per task:
`project.task._ft_amc_approved_hours()`. A task worked in October and
November and deployed in December is billed in December; October and
November bill nothing for it.

* Approval arriving after deployment attaches the task; reset / rejection,
  Undo Deployed and reopening (leaving the final stage) detach it **while the
  milestone is Not Started**. Once the month has been sent to the customer the
  link is kept and a note is posted on the task and the milestone.
* `project_date_extension`'s "no timesheet after the milestone due date" check
  is skipped for tasks on an AMC monthly milestone (a December deployment
  legitimately carries October lines).

## Task Excel

`project.custom.milestone._amc_build_task_excel()` renders, with xlsxwriter
(the library `ft_amc_monthly_timesheet` uses for its own Excel), one sheet:

* header block: milestone name, Project, Customer, Billing period, Milestone
  status;
* one row per deployed task attached to the milestone (archived included):
  **Task, Stage, Deployed On, Approved By** (`pwf_amc_approved_by_id`),
  **Approved Hours** (approved timesheet lines), **Billable Hours**
  (`ft_billable_hours`, `ft_task_hours_tracker`);
* a total row (approved and billable hours).

The row data is available separately through `_amc_task_excel_rows()`. The
file is an `ir.attachment` named `Support Services for September 2026 -
Tasks.xlsx` (res_model / res_id = the milestone), linked in the milestone's
existing **Attachments** (`attachment_ids`) and referenced by
`amc_task_excel_id`: that Many2one is the marker that tells the generated
file from anything uploaded by hand, so a regeneration deletes exactly the
previous generated file and leaves user uploads alone (nothing is added to
`ir.attachment`). Generated:

* automatically when the milestone becomes Completed, before the e-mail;
* by the **Generate Task Excel** button on the milestone form (managers / the
  project's PM), any time;
* by the report's `_build_attachments` when a month with a milestone is sent
  from the report form before the milestone was ever completed (only if
  missing).

## E-mail (requirements 43, 44) and timing

* Per-milestone switch **Send e-mail to customer** (`amc_send_email`),
  defaulted from the project's "Send monthly AMC timesheet" when the milestone
  is created. The milestone switch rules: on -> sent even if the project switch
  is off; off -> nothing sent, status unaffected (the Excel is still attached
  to the milestone).
* The e-mail is `ft_amc_monthly_timesheet`'s report of (project, month). For a
  month that has an AMC milestone the report lists the **milestone's tasks**
  with their **approved hours** (whole-task rule, approved lines only, so the
  PDF / Excel totals equal the milestone's Hours) instead of "approved tasks,
  entries dated in the month"; months without a milestone are unchanged. The
  milestone's task Excel is added to the mail next to the report's PDF and
  Excel (`_send_email` override in `models/monthly_report.py`).
* cron **AMC: Send Monthly Milestone Timesheets** (daily): from the send day
  (Settings > Project > AMC Monthly Timesheet > *Milestone E-mail Day*,
  `ir.config_parameter` `ft_amc_payment_milestone.send_day`, default **7**),
  every milestone of a finished month that is still **Not Started** with the
  switch on is marked Completed (= Excel + e-mail). A failure leaves it Not
  Started with the error on the chatter; the next run retries. Milestones with
  the switch off are left alone (manual flow). No reminder activities.
* The original day-5 cron (`_cron_send_monthly_reports`) **skips months that
  have an AMC milestone**, so a month is never mailed twice; it still mails
  months without a milestone (history, ineligible projects).

## Views

* Milestone form: header with status bar and the AMC buttons (Mark Completed
  & Send, Client Approved, Invoice Raised, Part Paid, Paid, Generate Task
  Excel, Reset); "AMC Support Milestone" group (period, hours, tasks, switch,
  sent on, task Excel, report link) and a **Tasks** page (task, stage,
  approval, approved by, deployed on, approved hours, billable hours), both
  for AMC monthly milestones only.
* Central milestone list: Billing Period, Approved Hours, Tasks, E-mail
  Customer columns; search filters *AMC Monthly*, *To Send*, *Sent /
  Completed*, *Overdue*; group by Project / Status / Billing Period.
* Project **Milestones** tab: for AMC projects only **Name, Hours
  (`hours_spent`), Status** are visible - Amount, Due Date and Attachments are
  hidden with `column_invisible="parent.ft_project_type == 'amc'"` (and
  `ft_implementation_milestone`'s `%` column shows on implementation projects
  only). Status and Hours read-only on AMC monthly rows. Billing period,
  task count and the send switch are on the milestone form and the central
  list.
* Task list: Deployment badge (Deployed / To Deploy) on AMC rows; search
  filters *Deployed* (`state = '1_deployed'`), *To Deploy*. The milestone's
  Tasks page shows the task Status (Done / Deployed / Cancelled).

## Migration (19.0.1.0.0 -> 19.0.1.1.0)

* `pre-migration.py`: milestones in `internal_approved` are reset to
  `not_started` in SQL before the selection shrinks; the "AMC milestone
  awaiting internal approval" To-Dos of the old cron are deleted.
* `post-migration.py`: AMC monthly milestones still named
  `AMC Support – <Month YYYY>` / coded `AMC-YYYY-MM` are renamed to
  `Support Services for <Month YYYY>` / `SS-YYYY-MM` (hand-edited names are
  left alone); a note is posted on each.

## Migration (19.0.1.1.0 -> 19.0.1.2.0)

* `post-migration.py`: tasks with `ft_deployed = True` (and Status Done) get
  `state = '1_deployed'` in SQL; no tracking message is posted.

## Tests

`tests/test_amc_payment_milestone.py` (post_install): creation / naming /
idempotence / kick-off untouched, eligibility, hook and cron, status set and
labels (no `internal_approved`), sequence and rights (Completed straight from
Not Started), Deployed rights and bulk all-or-nothing, Deployed as a Status
value (selection order after Done, closed / `is_closed` search, stage and
`date_end` untouched, undo -> Done, reopen -> In Progress, direct Status
writes refused or treated as undo by right, AMC overdue dashboard row with
the frozen figure when that module is installed), deployment-month hours
across months, approved-only hours (pending / rejected / un-approved lines
ignored), approval-after-deployment, undo / reopen (un)linking, task Excel
(row data, workbook content parsed with openpyxl or the sheet XML, button
rights, regeneration replacing only the generated file, empty month),
e-mail on Completed (approved lines only, Excel on the milestone and on the
mail next to the report's PDF / Excel; without the switch; failure refused),
day-7 cron (6th: nothing; 7th: Not Started -> Completed with Excel + mail,
switch off untouched, current month untouched; 8th: no duplicate; next month
picked up next run; failure keeps Not Started), day-5 cron skip,
timesheet-date check bypass.
