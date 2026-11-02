/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { DataTable } from "@ft_project_dashboard/js/data_table";
import { ProjectDashboard } from "@ft_project_dashboard/js/project_dashboard";

const MODEL = "ft.amc.overdue.dashboard";

// Opening a task from a row leaves the dashboard and rebuilds it on the way
// back, and the dashboard also unmounts every section while it refetches, so
// this component is re-created far more often than it is updated. Mirror the
// server-side scope (overdue-only, include-completed) into sessionStorage so
// each rebuild lands on the same view. The text search is deliberately not
// stored: it is a momentary narrowing, and the rows themselves are always
// refetched.
const SCOPE_KEY = "ft_amc_overdue_dashboard.scope";

function readStoredScope() {
    try {
        const stored = JSON.parse(browser.sessionStorage.getItem(SCOPE_KEY) || "null");
        if (stored && typeof stored === "object") {
            return stored;
        }
    } catch {
        // Unreadable/corrupt storage: fall back to the defaults.
    }
    return null;
}

function writeStoredScope(scope) {
    try {
        browser.sessionStorage.setItem(SCOPE_KEY, JSON.stringify(scope));
    } catch {
        // Storage unavailable/full: the selection just won't persist.
    }
}

/** "10d" for a day count; "—" when there is none. */
function fmtDays(v) {
    if (v === null || v === undefined || v === "") return "—";
    return `${v}d`;
}

/**
 * "AMC Task Overdue": one full-width table of every task on an AMC project,
 * with its age and the days it is past its ORIGINAL deadline, embedded in
 * ft_project_dashboard's Project Dashboard (below Implementation Stages, above
 * Resource Status — see the template extension in amc_overdue_dashboard.xml).
 *
 * It is a section of that board, not a page of its own: the board's header
 * Project and Project Manager pickers scope it like every other section, and
 * the counts the old KPI tiles carried now sit compactly beside the table's
 * own toggles instead of taking a row of cards.
 *
 * Props:
 *  - projectId   : string, '' = all — the dashboard's header Project picker.
 *  - managerId   : string, '' = all — the dashboard's header Project Manager
 *                  picker (a res.users id: project.project.user_id).
 *  - reloadToken : anything that changes when the dashboard refetches (its
 *                  `state.data`), so this table refetches in step with the
 *                  sections around it even when it stays mounted.
 */
export class AmcOverdueTable extends Component {
    static template = "ft_amc_overdue_dashboard.AmcOverdueTable";
    static components = { DataTable };
    static props = {
        projectId: { type: String, optional: true },
        managerId: { type: String, optional: true },
        reloadToken: { optional: true },
    };
    static defaultProps = { projectId: "", managerId: "" };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            // Server-side scope (persisted).
            overdueOnly: false,
            includeClosed: false,
            // Client-side narrowing (not persisted).
            search: "",
            data: { kpis: {}, rows: [], today: null },
        });

        onWillStart(async () => {
            const restored = readStoredScope();
            if (restored) {
                this.state.overdueOnly = !!restored.overdueOnly;
                this.state.includeClosed = !!restored.includeClosed;
            }
            await this.loadData(this.props);
        });

        // The dashboard normally unmounts its content while it refetches (so
        // this component is rebuilt and onWillStart runs again), but nothing
        // here relies on that: a scope or reload change that reaches a mounted
        // instance refetches too. The scope is compared explicitly rather than
        // reloading on every update, because the parent re-renders for reasons
        // (a search box elsewhere, a toggle on another table) that say nothing
        // about this table's rows.
        onWillUpdateProps(async (next) => {
            if (
                next.projectId !== this.props.projectId ||
                next.managerId !== this.props.managerId ||
                next.reloadToken !== this.props.reloadToken
            ) {
                await this.loadData(next);
            }
        });
    }

    // ----------------------------------------------------------------
    // Scope
    // ----------------------------------------------------------------
    _persistScope() {
        writeStoredScope({
            overdueOnly: this.state.overdueOnly,
            includeClosed: this.state.includeClosed,
        });
    }

    /** The scope, in the shape get_dashboard_data expects. `props` is passed
     *  in rather than read from `this.props` because onWillUpdateProps has
     *  the NEXT props before they are applied. */
    _filtersPayload(props) {
        return {
            // The dashboard's header pickers hold '' for "all" and a string id
            // otherwise; the server treats any falsy value as no narrowing.
            project_id: props.projectId || null,
            manager_id: props.managerId || null,
            include_closed: !!this.state.includeClosed,
            overdue_only: !!this.state.overdueOnly,
        };
    }

    async onToggle(field, ev) {
        this.state[field] = !!ev.target.checked;
        this._persistScope();
        await this.loadData(this.props);
    }

    onSearch(ev) {
        this.state.search = ev.target.value || "";
    }

    // ----------------------------------------------------------------
    // Data loading
    // ----------------------------------------------------------------
    async loadData(props) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(MODEL, "get_dashboard_data", [], {
                filters: this._filtersPayload(props),
            });
            this.state.data = this._normalise(data);
        } finally {
            this.state.loading = false;
        }
    }

    /** Coerce the payload into exactly what the table and the counts read, so
     *  a missing key or an array of assignee names never reaches the template.
     *  (assignees is still sent by the server but has no column.) */
    _normalise(data) {
        const d = data || {};
        const rows = (d.rows || []).map((r) => {
            const assignees = Array.isArray(r.assignees) ? r.assignees.join(", ") : (r.assignees || "");
            // Only a positive count is "overdue": null/0 render as "—" with no
            // badge, whichever the server sends for an on-time task. For a
            // completed task the server sends the figure frozen on the day of
            // completion; it is shown as-is, never recomputed here.
            const overdue = r.overdue_days > 0 ? r.overdue_days : null;
            return {
                ...r,
                assignees,
                stage: r.stage || "",
                original_deadline: r.original_deadline || null,
                deadline: r.deadline || null,
                completed_on: r.completed_on || null,
                total_days: r.total_days === null || r.total_days === undefined ? null : r.total_days,
                overdue_days: overdue,
            };
        });
        return {
            kpis: d.kpis || {},
            rows,
            today: d.today || null,
        };
    }

    // ----------------------------------------------------------------
    // Derived
    // ----------------------------------------------------------------
    get kpis() {
        return this.state.data.kpis || {};
    }

    /** The old KPI tiles, as one line of text beside the toggles:
     *  "12 tasks · 7 overdue · 93 overdue days · as of 2026-10-28". The task
     *  count is the server's (before the text search), so it agrees with the
     *  "Overdue only" badge whatever is typed in the search box. */
    get summary() {
        const k = this.kpis;
        if (k.total_tasks === undefined) return "";
        const parts = [
            `${k.total_tasks} task${k.total_tasks === 1 ? "" : "s"}`,
            `${k.overdue_tasks || 0} overdue`,
            `${k.overdue_days || 0} overdue days`,
        ];
        if (this.state.data.today) {
            parts.push(`as of ${this.state.data.today}`);
        }
        return parts.join(" · ");
    }

    /** Rows after the text search: a case-insensitive substring match over
     *  the project and task names. */
    get rows() {
        const q = this.state.search.trim().toLowerCase();
        const rows = this.state.data.rows || [];
        if (!q) return rows;
        return rows.filter((r) =>
            [r.project_name, r.task_name].some((v) =>
                String(v || "").toLowerCase().includes(q)
            )
        );
    }

    /** Original Deadline is the first deadline the task was given (what
     *  Overdue Days is measured from); Current Deadline is the latest one. */
    get columns() {
        return [
            { key: "project_name", label: "Project Name" },
            { key: "task_name", label: "Task Name", cls: "ftpd_wrap" },
            { key: "stage", label: "Stage" },
            { key: "original_deadline", label: "Original Deadline", date: true },
            { key: "deadline", label: "Current Deadline", date: true },
            { key: "total_days", label: "Total Days", numeric: true,
              render: (row) => fmtDays(row.total_days) },
            { key: "overdue_days", label: "Overdue Days", numeric: true, badge: true,
              render: (row) => fmtDays(row.overdue_days) },
        ];
    }

    // ----------------------------------------------------------------
    // Drill-down
    // ----------------------------------------------------------------
    openTask(row) {
        if (!row || !row.id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: row.task_name || "Task",
            res_model: "project.task",
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

// Make <AmcOverdueTable/> resolvable from the Project Dashboard's template,
// which amc_overdue_dashboard.xml extends. The static `components` map is
// what OWL consults for a sub-component tag; adding to it here, at module
// load, is enough because the dashboard is not rendered until an action
// opens it. Spread rather than assigned so the dashboard's own components
// (and any added by another module) stay registered.
ProjectDashboard.components = { ...ProjectDashboard.components, AmcOverdueTable };
