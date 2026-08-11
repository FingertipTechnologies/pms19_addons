"""ProjectDataCollector — aggregates delivery data for the Project AI analyses.

Mirrors ``SalesDataCollector``: constructed with the environment, a filters dict
and a date range, and exposes a single ``collect()`` returning a compact,
JSON-serialisable payload.

Supported filters (all optional; "all"/None means unfiltered):
* ``project_id``  — scope to one project
* ``employee_id`` — scope to one developer/resource

Only *aggregates* leave the server — never raw task or timesheet rows. Every
query runs as the calling user, so record rules are enforced before anything is
sent to a provider.
"""
from __future__ import annotations

TOP_N = 15

# qa_testapp.ticket ("Bugs" in the PMS menu). Resolved through ``env`` at call
# time rather than declared as a manifest dependency, so this module still
# installs on a database without the QA app.
BUG_MODEL = "qa_testapp.ticket"
BUG_CLOSED_STATES = ("fixed", "closed")
BUG_OPEN_STATES = ("open", "in_progress", "reopened")


def _as_id(value):
    """Normalise a UI filter value to an int id, or None when unfiltered."""
    if value in (None, "", "all", False):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class ProjectDataCollector:
    def __init__(self, env, filters: dict = None, date_from=None, date_to=None):
        self.env = env
        self.filters = filters or {}
        self.date_from = date_from
        self.date_to = date_to
        self.project_id = _as_id(self.filters.get("project_id"))
        self.employee_id = _as_id(self.filters.get("employee_id"))
        # Task assignment is by user, timesheets are by employee; resolve once.
        self.user_id = None
        if self.employee_id:
            emp = self.env["hr.employee"].browse(self.employee_id)
            self.user_id = emp.user_id.id if emp.exists() and emp.user_id else None

    # ------------------------------------------------------------------
    def collect(self) -> dict:
        """Delivery payload. Milestones are NOT included — see ``milestones()``."""
        payload = {
            "period": {"from": str(self.date_from), "to": str(self.date_to)},
            "scope": self._scope(),
            "projects": self._projects(),
            "resources": self._resources(),
            "task_health": self._task_health(),
            "timesheets": self._timesheets(),
        }
        bugs = self._bugs()
        if bugs is not None:
            payload["bugs"] = bugs
        # CRM context is portfolio-level; it says nothing about one developer,
        # so it is omitted when the analysis is scoped to a person.
        if not self.employee_id:
            payload["accounts"] = self._accounts()
        return payload

    def _scope(self):
        """Echo the active scope so the model never over-generalises."""
        scope = {"project": "all projects", "developer": "all developers"}
        if self.project_id:
            proj = self.env["project.project"].browse(self.project_id)
            scope["project"] = proj.name if proj.exists() else str(self.project_id)
        if self.employee_id:
            emp = self.env["hr.employee"].browse(self.employee_id)
            scope["developer"] = emp.name if emp.exists() else str(self.employee_id)
            scope["note"] = (
                "Data is scoped to this developer only. Do not describe the "
                "portfolio as a whole."
            )
        return scope

    # ------------------------------------------------------------------
    def _ts_domain(self, extra=None):
        dom = [("project_id", "!=", False)]
        if self.date_from:
            dom.append(("date", ">=", self.date_from))
        if self.date_to:
            dom.append(("date", "<=", self.date_to))
        if self.project_id:
            dom.append(("project_id", "=", self.project_id))
        if self.employee_id:
            dom.append(("employee_id", "=", self.employee_id))
        return dom + (extra or [])

    def _task_domain(self, extra=None):
        dom = []
        if self.project_id:
            dom.append(("project_id", "=", self.project_id))
        if self.user_id:
            dom.append(("user_ids", "in", [self.user_id]))
        elif self.employee_id:
            # Developer selected but has no linked user: no task can match, so
            # report zero rather than silently falling back to everyone's tasks.
            dom.append(("id", "=", False))
        return dom + (extra or [])

    # ------------------------------------------------------------------
    # Completed / open are decided by the task's STAGE (Planned, Working,
    # Testing, Completed), not by the `state` field. Stages do not set state in
    # Odoo 18, so counting state '1_done' reported almost nothing as completed
    # and almost everything as open. The rules live on project.task
    # (bt_project_customization) and are shared with the project fields and the
    # PMS dashboard, so all three always agree on what "completed" means.
    # ------------------------------------------------------------------
    def _done_domain(self, extra=None, dated=False):
        """Tasks that reached a folded (Completed) stage. Excludes cancelled.

        ``dated=True`` restricts to work COMPLETED inside the report period,
        using the stage-completion date rather than write_date (which moves on
        any edit, so an old task touched yesterday looked freshly completed).
        """
        Task = self.env["project.task"]
        return Task._ft_delivery_domain(
            self._task_domain(extra),
            date_from=self.date_from if dated else None,
            date_to=self.date_to if dated else None,
        )

    def _open_domain(self, extra=None):
        """Tasks still in an unfolded stage (Planned / Working / Testing)."""
        return self.env["project.task"]._ft_open_domain(self._task_domain(extra))

    # ------------------------------------------------------------------
    # Drill-downs
    # ------------------------------------------------------------------
    def drilldowns(self, include_milestones=False) -> dict:
        """Clickable record lists behind the KPI tiles.

        Built from the same domain helpers that produce the numbers, so a tile
        and the list it opens can never disagree. Keys are offered to the model,
        which tags a KPI with one; unknown/absent keys simply aren't clickable.

        ``include_milestones`` mirrors the payload: a metric the report never
        received must not be offered as a clickable key.
        """
        dd = {
            "open_tasks": {
                "res_model": "project.task",
                "name": "Open Tasks",
                "domain": self._open_domain(),
            },
            "completed_tasks": {
                "res_model": "project.task",
                "name": "Completed Tasks",
                "domain": self._done_domain(),
            },
            "unassigned_tasks": {
                "res_model": "project.task",
                "name": "Unassigned Tasks",
                "domain": self._open_domain([("user_ids", "=", False)]),
            },
            "no_deadline_tasks": {
                "res_model": "project.task",
                "name": "Tasks Without a Deadline",
                "domain": self._open_domain([("date_deadline", "=", False)]),
            },
            "used_hours": {
                "res_model": "account.analytic.line",
                "name": "Timesheet Entries",
                "domain": self._ts_domain(),
            },
        }
        if self.date_to:
            dd["overdue_tasks"] = {
                "res_model": "project.task",
                "name": "Overdue Tasks",
                "domain": self._open_domain(
                    [("date_deadline", "<", str(self.date_to)),
                     ("date_deadline", "!=", False)]
                ),
            }
        if include_milestones:
            dd.update(self._milestone_drilldowns())
        dd.update(self._bug_drilldowns())
        return dd

    def _bug_drilldowns(self):
        """Bug tiles. Empty when the QA app isn't installed, so a key is never
        offered for a metric the payload didn't carry."""
        if BUG_MODEL not in self.env:
            return {}
        dd = {
            "open_bugs": {
                "res_model": BUG_MODEL, "name": "Open Bugs",
                "domain": self._bug_domain([("status", "in", BUG_OPEN_STATES)]),
            },
            "closed_bugs": {
                "res_model": BUG_MODEL, "name": "Closed Bugs",
                "domain": self._bug_domain([("status", "in", BUG_CLOSED_STATES)]),
            },
            "reopened_bugs": {
                "res_model": BUG_MODEL, "name": "Re-Opened Bugs",
                "domain": self._bug_domain([("reopen_count", ">", 0)]),
            },
            "client_bugs": {
                "res_model": BUG_MODEL, "name": "Client-Raised Bugs",
                "domain": self._bug_domain([("is_client", "=", True)]),
            },
        }
        if self.date_to:
            dd["overdue_bugs"] = {
                "res_model": BUG_MODEL, "name": "Overdue Bugs",
                "domain": self._bug_domain([
                    ("status", "in", BUG_OPEN_STATES),
                    ("target_deadline", "<", str(self.date_to) + " 23:59:59"),
                    ("target_deadline", "!=", False),
                ]),
            }
        return dd

    def _milestone_drilldowns(self):
        """Milestone billing tiles (project.custom.milestone only)."""
        base = [("project_id", "=", self.project_id)] if self.project_id else []
        if "project.custom.milestone" in self.env:
            model = "project.custom.milestone"
            dd = {
                "milestones_total": {"name": "Milestones", "domain": list(base)},
                "milestones_not_started": {
                    "name": "Milestones Not Started",
                    "domain": base + [("status", "=", "not_started")],
                },
                "milestones_completed_not_invoiced": {
                    "name": "Completed, Not Invoiced",
                    "domain": base + [("status", "=", "completed")],
                },
                "milestones_awaiting_payment": {
                    "name": "Invoiced, Awaiting Payment",
                    "domain": base + [("status", "in",
                                       ["invoice_raised", "partially_paid"])],
                },
                "milestones_paid": {
                    "name": "Paid Milestones",
                    "domain": base + [("status", "=", "paid")],
                },
                "milestones_no_due_date": {
                    "name": "Milestones Without a Due Date",
                    "domain": base + [("due_date", "=", False)],
                },
            }
            if self.date_to:
                dd["milestones_overdue"] = {
                    "name": "Overdue Milestones",
                    "domain": base + [("due_date", "!=", False),
                                      ("due_date", "<", str(self.date_to)),
                                      ("status", "!=", "paid")],
                }
        else:
            return {}
        for spec in dd.values():
            spec["res_model"] = model
        return dd

    # ------------------------------------------------------------------
    def _projects(self):
        """Project-wise used vs estimated hours, task counts and variance."""
        AAL = self.env["account.analytic.line"]
        Task = self.env["project.task"]
        used = {}
        for g in AAL.read_group(
            self._ts_domain(), ["unit_amount:sum"], ["project_id"],
            lazy=False, orderby="unit_amount desc", limit=TOP_N,
        ):
            if g.get("project_id"):
                used[g["project_id"][0]] = {
                    "project": g["project_id"][1],
                    "used_hours": round(g.get("unit_amount") or 0.0, 2),
                }
        if not used:
            return []
        proj_ids = list(used)
        for g in Task.read_group(
            self._task_domain([("project_id", "in", proj_ids)]),
            ["estimated:sum"], ["project_id"], lazy=False,
        ):
            if g.get("project_id"):
                used[g["project_id"][0]]["estimated_hours"] = round(
                    g.get("estimated") or 0.0, 2
                )
        rows = []
        for pid in proj_ids:
            rec = used[pid]
            rec.setdefault("estimated_hours", 0.0)
            rec["completed_tasks"] = Task.search_count(
                self._done_domain([("project_id", "=", pid)])
            )
            rec["pending_tasks"] = Task.search_count(
                self._open_domain([("project_id", "=", pid)])
            )
            rec["overdue_tasks"] = Task.search_count(self._open_domain([
                ("project_id", "=", pid),
                ("date_deadline", "<", str(self.date_to)),
                ("date_deadline", "!=", False),
            ])) if self.date_to else 0
            est = rec["estimated_hours"]
            # Positive = over estimate. Omitted when there is no estimate to
            # compare against, so the model never divides by a missing baseline.
            rec["variance_pct"] = (
                round((rec["used_hours"] - est) / est * 100, 1) if est else None
            )
            rows.append(rec)
        return rows

    def _resources(self):
        """Resource-wise logged hours and open/closed task load."""
        AAL = self.env["account.analytic.line"]
        Task = self.env["project.task"]
        Emp = self.env["hr.employee"]
        used = {}
        for g in AAL.read_group(
            self._ts_domain([("employee_id", "!=", False)]),
            ["unit_amount:sum"], ["employee_id"], lazy=False,
            orderby="unit_amount desc", limit=TOP_N,
        ):
            if g.get("employee_id"):
                used[g["employee_id"][0]] = {
                    "resource": g["employee_id"][1],
                    "used_hours": round(g.get("unit_amount") or 0.0, 2),
                }
        if not used:
            return []
        emps = Emp.browse(list(used))
        user_by_emp = {e.id: e.user_id.id for e in emps if e.user_id}
        rows = []
        for eid, rec in used.items():
            uid = user_by_emp.get(eid)
            if uid:
                # Scoped per resource, so this builds its own base rather than
                # going through _task_domain; the stage rules still come from
                # the shared helpers.
                base = [("user_ids", "in", [uid])]
                if self.project_id:
                    base.append(("project_id", "=", self.project_id))
                rec["completed_tasks"] = Task.search_count(
                    Task._ft_delivery_domain(base)
                )
                rec["pending_tasks"] = Task.search_count(
                    Task._ft_open_domain(base)
                )
            else:
                rec["completed_tasks"] = rec["pending_tasks"] = 0
            rows.append(rec)
        return rows

    def _task_health(self):
        """Task shape within scope: where the work sits, overdue, unassigned."""
        Task = self.env["project.task"]
        by_stage = []
        for g in Task.read_group(
            self._task_domain(), ["id"], ["stage_id"], lazy=False,
        ):
            stage = g.get("stage_id")
            by_stage.append({
                "stage": stage[1] if stage else "unset",
                "count": g["__count"],
            })
        health = {
            "open_tasks": Task.search_count(self._open_domain()),
            "completed_tasks": Task.search_count(self._done_domain()),
            "unassigned_tasks": Task.search_count(
                self._open_domain([("user_ids", "=", False)])
            ),
            "no_deadline_tasks": Task.search_count(
                self._open_domain([("date_deadline", "=", False)])
            ),
            # The real pipeline: Planned / Working / Testing / Completed, in the
            # project's own stage order. Replaces the old "by_state" breakdown,
            # which reported everything as "01_in_progress" because stages never
            # write state.
            "by_stage": by_stage,
        }
        if self.date_to:
            health["overdue_tasks"] = Task.search_count(
                self._open_domain([("date_deadline", "<", str(self.date_to)),
                                   ("date_deadline", "!=", False)])
            )
        if self.date_from and self.date_to:
            health["completed_in_period"] = Task.search_count(
                self._done_domain(dated=True)
            )
        return health

    def _timesheets(self):
        """Timesheet shape within scope (PMS > Timesheets).

        ``_projects``/``_resources`` already slice logged hours by project and by
        person; this answers *what the time went into* — which tasks, how it was
        spread over the period, and how much was booked to a project with no task
        attached (time that no task-level report will ever surface).
        """
        AAL = self.env["account.analytic.line"]
        total = 0.0
        for g in AAL.read_group(self._ts_domain(), ["unit_amount:sum"], [], lazy=False):
            total = round(g.get("unit_amount") or 0.0, 2)

        by_task = []
        for g in AAL.read_group(
            self._ts_domain([("task_id", "!=", False)]),
            ["unit_amount:sum"], ["task_id"], lazy=False,
            orderby="unit_amount desc", limit=TOP_N,
        ):
            if g.get("task_id"):
                by_task.append({
                    "task": g["task_id"][1],
                    "hours": round(g.get("unit_amount") or 0.0, 2),
                })

        by_month = []
        for g in AAL.read_group(
            self._ts_domain(), ["unit_amount:sum"], ["date:month"], lazy=False,
        ):
            label = g.get("date:month")
            if label:
                by_month.append({
                    "month": label,
                    "hours": round(g.get("unit_amount") or 0.0, 2),
                })

        no_task_hours = 0.0
        for g in AAL.read_group(
            self._ts_domain([("task_id", "=", False)]),
            ["unit_amount:sum"], [], lazy=False,
        ):
            no_task_hours = round(g.get("unit_amount") or 0.0, 2)

        return {
            "total_hours": total,
            "entry_count": AAL.search_count(self._ts_domain()),
            "hours_by_task": by_task,
            "hours_by_month": by_month,
            "hours_not_linked_to_task": no_task_hours,
        }

    # ------------------------------------------------------------------
    def _bug_domain(self, extra=None):
        """Scope bugs the same way tasks are scoped: project + assignee + period.

        Bugs are assigned to a *user*, so a developer filter uses the resolved
        ``user_id`` exactly as ``_task_domain`` does — and falls through to an
        impossible domain when the employee has no user, rather than silently
        reporting everyone's bugs.
        """
        dom = []
        if self.project_id:
            dom.append(("project_id", "=", self.project_id))
        if self.user_id:
            dom.append(("assignee_id", "=", self.user_id))
        elif self.employee_id:
            dom.append(("id", "=", False))
        # reported_date is a Datetime; span the whole closing day.
        if self.date_from:
            dom.append(("reported_date", ">=", str(self.date_from)))
        if self.date_to:
            dom.append(("reported_date", "<=", str(self.date_to) + " 23:59:59"))
        return dom + (extra or [])

    def _bugs(self):
        """Bug shape within scope (PMS > Bugs). ``None`` when the QA app is absent."""
        if BUG_MODEL not in self.env:
            return None
        Bug = self.env[BUG_MODEL]

        def _breakdown(field):
            rows = []
            for g in Bug.read_group(self._bug_domain(), ["id"], [field], lazy=False):
                val = g.get(field)
                if isinstance(val, tuple):
                    val = val[1]
                rows.append({field: val or "unset", "count": g["__count"]})
            return rows

        # Sorted in Python: read_group's orderby on a m2o sorts by id, which would
        # make "top" assignees an arbitrary slice rather than the busiest ones.
        by_assignee = [
            {"assignee": g["assignee_id"][1], "count": g["__count"]}
            for g in Bug.read_group(
                self._bug_domain([("assignee_id", "!=", False)]),
                ["id"], ["assignee_id"], lazy=False,
            )
            if g.get("assignee_id")
        ]
        by_assignee.sort(key=lambda r: r["count"], reverse=True)
        by_assignee = by_assignee[:TOP_N]

        bugs = {
            "total": Bug.search_count(self._bug_domain()),
            "open": Bug.search_count(
                self._bug_domain([("status", "in", BUG_OPEN_STATES)])
            ),
            "closed": Bug.search_count(
                self._bug_domain([("status", "in", BUG_CLOSED_STATES)])
            ),
            "reopened": Bug.search_count(
                self._bug_domain([("reopen_count", ">", 0)])
            ),
            "client_raised": Bug.search_count(self._bug_domain([("is_client", "=", True)])),
            "pending_approval": Bug.search_count(
                self._bug_domain([("approval_state", "=", "pending_approval")])
            ),
            "by_status": _breakdown("status"),
            "by_severity": _breakdown("severity"),
            "by_priority": _breakdown("priority"),
            "by_module": _breakdown("module_id"),
            "by_assignee": by_assignee,
        }
        if self.date_to:
            bugs["overdue"] = Bug.search_count(self._bug_domain([
                ("status", "in", BUG_OPEN_STATES),
                ("target_deadline", "<", str(self.date_to) + " 23:59:59"),
                ("target_deadline", "!=", False),
            ]))
        return bugs

    # ------------------------------------------------------------------
    def milestones(self):
        """Milestone BILLING — opt-in, requested only by revenue purposes.

        Reads ``project.custom.milestone`` exclusively. Stock ``project.milestone``
        is deliberately not consulted: it is unmaintained here (nothing reached,
        no deadlines), and reading it produced counts that looked like delivery
        delay but meant nothing.

        Note these records carry no usable dates, so this is a value/lifecycle
        picture, never a schedule one.
        """
        if "project.custom.milestone" not in self.env:
            return {"available": False}
        return self._custom_milestones()

    def _custom_milestones(self):
        """Status/value breakdown of project.custom.milestone."""
        Milestone = self.env["project.custom.milestone"]
        labels = dict(Milestone._fields["status"].selection)
        base = [("project_id", "=", self.project_id)] if self.project_id else []
        rows = Milestone.search_read(
            base, ["name", "status", "amount", "paid_amount", "due_date",
                   "hours_spent", "project_id"],
        )
        if not rows:
            return {"available": True, "model": "project.custom.milestone", "total": 0}

        # Settled = money is in. Delivered-but-unsettled is where value leaks.
        by_status = {}
        for r in rows:
            key = r.get("status") or "unset"
            agg = by_status.setdefault(
                key, {"status": key, "label": labels.get(key, key),
                      "count": 0, "amount": 0.0, "paid_amount": 0.0}
            )
            agg["count"] += 1
            agg["amount"] += r.get("amount") or 0.0
            agg["paid_amount"] += r.get("paid_amount") or 0.0
        for agg in by_status.values():
            agg["amount"] = round(agg["amount"], 2)
            agg["paid_amount"] = round(agg["paid_amount"], 2)

        total_amount = round(sum(r.get("amount") or 0.0 for r in rows), 2)
        total_paid = round(sum(r.get("paid_amount") or 0.0 for r in rows), 2)
        no_due = [r for r in rows if not r.get("due_date")]
        overdue = [
            r for r in rows
            if r.get("due_date")
            and self.date_to
            and str(r["due_date"]) < str(self.date_to)
            and r.get("status") != "paid"
        ]
        # Delivered but not yet invoiced -> unbilled revenue.
        completed_unbilled = [r for r in rows if r.get("status") == "completed"]
        # Invoiced but not fully collected.
        awaiting_payment = [
            r for r in rows if r.get("status") in ("invoice_raised", "partially_paid")
        ]
        return {
            "available": True,
            "model": "project.custom.milestone",
            "status_meaning": (
                "not_started -> completed (delivered) -> invoice_raised -> "
                "partially_paid -> paid (settled)"
            ),
            "total": len(rows),
            "total_amount": total_amount,
            "paid_amount": total_paid,
            "outstanding_amount": round(total_amount - total_paid, 2),
            "by_status": sorted(by_status.values(), key=lambda a: -a["count"]),
            "hours_spent": round(sum(r.get("hours_spent") or 0.0 for r in rows), 2),
            "overdue": len(overdue),
            "overdue_list": [
                {"name": r["name"], "due_date": str(r["due_date"]),
                 "status": labels.get(r.get("status"), r.get("status")),
                 "amount": r.get("amount") or 0.0,
                 "project": r["project_id"][1] if r.get("project_id") else ""}
                for r in overdue[:TOP_N]
            ],
            # Without a due date nothing can be judged late; say so explicitly so
            # the analysis reports missing tracking instead of inventing delay.
            "no_due_date": len(no_due),
            "completed_not_invoiced": {
                "count": len(completed_unbilled),
                "amount": round(sum(r.get("amount") or 0.0 for r in completed_unbilled), 2),
            },
            "awaiting_payment": {
                "count": len(awaiting_payment),
                "amount": round(
                    sum((r.get("amount") or 0.0) - (r.get("paid_amount") or 0.0)
                        for r in awaiting_payment), 2
                ),
            },
        }

    def _accounts(self):
        """CRM activity by expected close date, for delivery-vs-demand context."""
        if "crm.lead" not in self.env:
            return {"available": False}
        Lead = self.env["crm.lead"]
        base = [("type", "=", "opportunity")]
        if self.date_from:
            base.append(("date_deadline", ">=", self.date_from))
        if self.date_to:
            base.append(("date_deadline", "<=", self.date_to))
        by_stage = []
        total_count = total_value = 0
        for g in Lead.read_group(base, ["expected_revenue:sum"], ["stage_id"], lazy=False):
            cnt = g["__count"]
            val = round(g.get("expected_revenue") or 0.0, 2)
            total_count += cnt
            total_value += val
            by_stage.append({
                "stage": g["stage_id"][1] if g.get("stage_id") else "Undefined",
                "count": cnt,
                "expected_revenue": val,
            })
        activities = 0
        try:
            lead_model = self.env["ir.model"]._get("crm.lead").id
            act_dom = [("res_model_id", "=", lead_model)]
            if self.date_from:
                act_dom.append(("date_deadline", ">=", self.date_from))
            if self.date_to:
                act_dom.append(("date_deadline", "<=", self.date_to))
            activities = self.env["mail.activity"].search_count(act_dom)
        except Exception:  # pragma: no cover - defensive
            pass
        return {
            "available": True,
            "opportunities": total_count,
            "expected_revenue": round(total_value, 2),
            "by_stage": by_stage,
            "activities_due": activities,
        }
