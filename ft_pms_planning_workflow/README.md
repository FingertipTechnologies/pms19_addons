# PMS Planning & Stage Workflow (`ft_pms_planning_workflow`)

All changes for the "PMS Updates 1" deck live in this addon. No other addon or Odoo core file is modified.

## Install / upgrade

- **Depends on:** project, mail, hr_timesheet, sale_timesheet, bt_project_customization, ft_project_lifecycle,
  ft_sprint_management, ft_task_hours_tracker, ft_customer_feedback.
- **Install:** `odoo -c <conf> -d <db> -i ft_pms_planning_workflow`
- **Upgrade:** `odoo -c <conf> -d <db> -u ft_pms_planning_workflow`
- **Tests:** `odoo -c <conf> -d <test_db> -i ft_pms_planning_workflow --test-tags /ft_pms_planning_workflow --stop-after-init`
- **After install,** go to Settings → Project → *Stage change notifications* and pick the internal contacts
  (Sunil, Shebin, Rakesh, Ameen) and the `info@…` address. Nothing is pre-filled.
- **Projects list.** The list view of the *Projects* menu (`project.open_view_project_all_group_stage_tree_view`)
  is pointed at this addon's view `pwf_project_list_view`. That bypasses the DB-only customization
  "project.project.list.custom.fingertip".
  - Running `-u project` alone resets this until this addon is upgraded again.
  - Uninstalling restores `project.project_list_view_group_stage`.
- **Planner buttons.** A "Project Status" icon button sits before the view switcher in every view of the
  *Projects* menu; a "Task Planner" icon button sits before the view switcher in every view of *All Tasks*.

## Rules implemented

| Topic | Rule |
|---|---|
| Day colour | grey < 4 h · yellow 4 to < 6 h · green 6 to 8 h (6 and 8 are green) · red > 8 h · plain light grey = no planned work (different from 0 h, which is grey) |
| Planned effort (Project Status) | Each task's estimate is split equally between its assignees, then spread evenly over Mon–Fri of its Week (or of its deadline's week). Weekends carry no load. Tasks with neither a Week nor a deadline are counted as "unscheduled". |
| Cumulative / Employee-wise | **Cumulative:** a project's day = total planned hours ÷ number of people allocated that day. **Employee-wise:** that person's hours on the project, coloured by their total across all projects that day. A dot marks a collision (load on more than one project). |
| Avg. Daily Effort | (Estimated − Actual) ÷ working days (Mon–Fri) from today to End Date, inclusive. States: no end date, no estimate, overdue, exhausted. |
| Filters | Project, PM (project manager field), Resource (task assignees). Days: next/last 5–60, this week/month/quarter, ±15/30/60, or a custom range of up to 180 days. Default: next 60 days. Option lists cascade. Closed projects are not excluded. |
| Task Planner | A task belongs to a week through its Week (`sprint_id`). The board starts at the current week, or at the clicked week. Order by stage: overdue → not started → working → completed. The Status selector shows Open (default), Completed only, or All. **Totals** (estimate-based): Estimated, Open, Completed. Actual (timesheet hours) is shown separately. |
| Week move | Drag a card (or use the ⇄ menu); no reason is asked. The deadline moves to the new week's Sunday. The deadline from before the first move is kept in **Original Deadline**. Each move is logged with old and new week and deadline, who and when (reason optional), in the task's Week Moves tab. |
| Stage gates | Apply to Implementation projects and are enforced on the server (form, kanban drag, import, RPC, create, copy, type conversion). A forward move must satisfy every gated stage it passes. **DEV:** BRD evidence + finance. **SRV:** QA sign-off of the regression (Current Status and Open Issues are optional notes). **UAT:** sandbox evidence + finance + admin approval. **DATA:** Customer UAT sign-off / completion e-mail screenshot + finance. **TRA:** that screenshot carried forward. **SUPPORT:** that screenshot + finance. **CLOSED:** internal feedback screenshot + external review (Partner Portal) screenshot + finance + Retrospective; Google review optional. |
| UAT | Needs sandbox review evidence and a pending request approved by an Administrator. Approving re-checks every prerequisite, refuses a stale request and moves the stage. |
| Lock | `pwf_locked` is evaluated automatically. It locks on CLOSED or HOLD, when On Hold is ticked, or when a stage date is overdue. It unlocks automatically when the stage moves, hold is cleared or the date is extended. Evaluation runs on save and in a daily cron. An Administrator can lock or unlock manually; a manual unlock lasts until the next stage change. A locked project takes no new tasks or timesheets. |
| Testing task type | Assignees must be QA (tester job or QA Group) or a Project Coordinator. Estimate ≤ 40 h and logged hours ≤ 40 h (40 is accepted). The deadline must fall inside the task's single Week; timesheet dates are not restricted. |
| Finance clearance | One flag per stage (DEV, UAT, DATA, SUPPORT, CLOSED), recording who cleared it and when. Only the **PMS Finance Clearance** group can grant or revoke it (Grant / Revoke buttons, which work even when the user cannot edit the project); Administrators are not included. The server enforces this. |
