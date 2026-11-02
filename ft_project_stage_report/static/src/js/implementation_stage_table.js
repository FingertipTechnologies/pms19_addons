/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { ProjectDashboard } from "@ft_project_dashboard/js/project_dashboard";

const MODEL = "ft.project.stage.line";

// The two measures of the matrix. They replaced the former "Days Worked" /
// "Overdue / Delays" menus (same lines, different number in each cell), so
// the choice is a switch inside the table rather than two pages.
export const VIEWS = [
    { id: "days", label: "Days Worked" },
    { id: "overdue", label: "Overdue Days" },
];
const DEFAULT_VIEW = VIEWS[0].id;

// Opening a project from a row leaves the dashboard and rebuilds it on the
// way back, which would reset this table to its defaults. Mirror the view
// and the Include-closed toggle into sessionStorage so the round trip lands
// on the same table. The text search and the sort direction are deliberately
// not stored: they are momentary narrowings, and the rows themselves are
// always refetched.
const SCOPE_KEY = "ft_project_stage_report.scope";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

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

/** "6d" for a day count (0 included); "—" when there is none. */
function fmtDays(v) {
    if (v === null || v === undefined || v === "") return "—";
    return `${v}d`;
}

/** 'YYYY-MM-DD' -> 'DD Mon YYYY' without touching the timezone (same
 *  rendering DataTable gives its date columns, so tooltips match the rest
 *  of the board). */
function fmtDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
    if (!m) return iso || "";
    return `${m[3]} ${MONTHS[parseInt(m[2], 10) - 1]} ${m[1]}`;
}

/**
 * "Implementation Stages" matrix of the Project Dashboard: one row per
 * Implementation project, one column per lifecycle stage (in pipeline
 * order) and a Total, fed by ft.project.stage.line.get_dashboard_matrix.
 *
 * Rendered by its own template rather than through the shared DataTable:
 * the column set is data-driven (the stages come with the payload), every
 * cell is red or not on its OWN value and the Project / Total cells carry a
 * second line, none of which DataTable's per-column rendering can express.
 * The markup and the ftpd_* classes are DataTable's, so it reads as one
 * more section of the board.
 *
 * Props (all owned by the dashboard, which is why they are props and not
 * local state):
 *  - projectId   : string, '' = every project (the header's Project picker)
 *  - managerId   : string, '' = every manager (the header's PM picker)
 *  - reloadToken : anything whose identity changes when the dashboard
 *                  refetches (it passes state.data), so a Refresh on the
 *                  board refetches this table too even though its rows come
 *                  from a different model.
 */
export class ImplementationStageTable extends Component {
    static template = "ft_project_stage_report.ImplementationStageTable";
    static props = {
        projectId: { type: String, optional: true },
        managerId: { type: String, optional: true },
        reloadToken: { optional: true },
    };
    static defaultProps = { projectId: "", managerId: "" };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.views = VIEWS;
        this.state = useState({
            loading: true,
            // Persisted.
            view: DEFAULT_VIEW,
            includeClosed: false,
            // Client-side narrowing (not persisted).
            search: "",
            sortDir: "asc",
            // Payload of get_dashboard_matrix.
            stages: [],
            projects: [],
        });

        onWillStart(async () => {
            const restored = readStoredScope();
            if (restored) {
                // A view id stored by an older release ("delays") is simply
                // not in VIEWS any more and falls back to the default.
                if (VIEWS.some((v) => v.id === restored.view)) {
                    this.state.view = restored.view;
                }
                this.state.includeClosed = !!restored.includeClosed;
            }
            await this.loadData(this.props);
        });

        // The dashboard keeps this component mounted while its header scope
        // changes, so the new scope arrives as new props, not a new mount.
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
            view: this.state.view,
            includeClosed: this.state.includeClosed,
        });
    }

    /** The scope, in the shape get_dashboard_matrix expects. */
    _scopePayload(props) {
        return {
            project_id: props.projectId ? parseInt(props.projectId, 10) : false,
            manager_id: props.managerId ? parseInt(props.managerId, 10) : false,
            include_closed: !!this.state.includeClosed,
        };
    }

    onViewChange(viewId) {
        if (viewId === this.state.view) return;
        this.state.view = viewId;
        this._persistScope();
        // Same cells, other number shown: no refetch needed.
    }

    async onIncludeClosed(ev) {
        this.state.includeClosed = !!ev.target.checked;
        this._persistScope();
        await this.loadData(this.props);
    }

    onSearch(ev) {
        this.state.search = ev.target.value || "";
    }

    onSortToggle() {
        this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
    }

    get sortIcon() {
        return this.state.sortDir === "asc" ? "fa-caret-up" : "fa-caret-down";
    }

    // ----------------------------------------------------------------
    // Data loading
    // ----------------------------------------------------------------
    async loadData(props) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(MODEL, "get_dashboard_matrix", [
                this._scopePayload(props),
            ]);
            this.state.stages = (data && data.stages) || [];
            this.state.projects = this._normalise((data && data.projects) || []);
        } catch (e) {
            // A failed fetch must not take the whole dashboard down with it:
            // show an empty table and leave the error in the console.
            console.warn("Implementation Stages table load failed", e);
            this.state.stages = [];
            this.state.projects = [];
        } finally {
            this.state.loading = false;
        }
    }

    /** Coerce the payload into exactly what the template reads: strings
     *  never False, numbers never missing, cells always an object. */
    _normalise(projects) {
        return projects.map((p) => ({
            ...p,
            project_name: p.project_name || "",
            manager_name: p.manager_name || "",
            total_days_worked: p.total_days_worked || 0,
            total_overdue_days: p.total_overdue_days || 0,
            is_overdue: !!p.is_overdue,
            cells: p.cells || {},
        }));
    }

    // ----------------------------------------------------------------
    // Derived
    // ----------------------------------------------------------------
    get isOverdueView() {
        return this.state.view === "overdue";
    }

    /** Projects after the text search (a case-insensitive substring match
     *  over the project and the Project Manager names), in name order; the
     *  Project header flips the direction. */
    get rows() {
        const q = this.state.search.trim().toLowerCase();
        let rows = this.state.projects;
        if (q) {
            rows = rows.filter((p) =>
                [p.project_name, p.manager_name].some((v) =>
                    String(v || "").toLowerCase().includes(q)
                )
            );
        }
        // The server already sorts ascending by name; only reverse when
        // asked, keeping the server's tie-break (project id) intact.
        return this.state.sortDir === "asc" ? rows : [...rows].reverse();
    }

    /** The three figures above the grid, over the rows SHOWN (so a search
     *  narrows them too). The middle one follows the view: the total of the
     *  number the cells currently display. */
    get stats() {
        const rows = this.rows;
        const overdueDays = rows.reduce((s, p) => s + p.total_overdue_days, 0);
        const workedDays = rows.reduce((s, p) => s + p.total_days_worked, 0);
        return {
            projects: rows.length,
            totalLabel: this.isOverdueView ? "Total overdue days" : "Total days worked",
            totalValue: fmtDays(this.isOverdueView ? overdueDays : workedDays),
            totalDanger: this.isOverdueView && overdueDays > 0,
            projectsOverdue: rows.filter((p) => p.is_overdue).length,
        };
    }

    get emptyText() {
        if (this.state.loading) return "Loading…";
        if (this.state.search.trim() && this.state.projects.length) {
            return "No project matches the search.";
        }
        return this.state.includeClosed
            ? "No Implementation projects match the current scope."
            : "No open Implementation projects match the current scope.";
    }

    // ----------------------------------------------------------------
    // Cells
    // ----------------------------------------------------------------
    /** The project's cell for a stage, or null when it has no line for it. */
    cellFor(project, stage) {
        return project.cells[String(stage.id)] || null;
    }

    /** Text of a stage cell. Days Worked: the days once the stage was
     *  entered, "—" before. Overdue Days: only the excess days, "—" when
     *  there are none (an on-time stage must not read as a number). */
    cellText(cell) {
        if (!cell) return "—";
        if (this.isOverdueView) {
            return cell.overdue_days > 0 ? fmtDays(cell.overdue_days) : "—";
        }
        return cell.reached ? fmtDays(cell.days_worked) : "—";
    }

    /** Whether the cell is painted red: the stage is overdue, except in Days
     *  Worked view when nothing has been worked yet ("0d"): a red 0 reads as
     *  a wrong figure, so that cell stays neutral and carries an overdue
     *  icon instead (cellFlag). */
    cellDanger(cell) {
        if (!cell || !(cell.overdue_days > 0)) return false;
        if (!this.isOverdueView && cell.reached && !cell.days_worked) return false;
        return true;
    }

    /** Overdue stage shown without the red pill (neutral 0d): mark it with
     *  a small red icon so the overdue state is still visible. */
    cellFlag(cell) {
        return !!cell && cell.overdue_days > 0 && !this.cellDanger(cell);
    }

    cellClass(cell) {
        return {
            "ftpsr_cell_val--pill": this.cellDanger(cell),
            "ftpsr_cell_val--current": !!cell && cell.is_current,
        };
    }

    /** Hover text of a stage cell: the dates behind the number. The planned
     *  date is the date the project must REACH the stage by (after approved
     *  Date Extensions), hence "Reach by"; overdue is the approved extension
     *  days of the stage plus entry minus that date, or today minus it for
     *  the next stage not reached yet. */
    cellTitle(cell, stage) {
        const parts = [stage.name + (cell && cell.is_current ? " (current stage)" : "")];
        if (!cell) {
            parts.push("No data for this stage");
            return parts.join(" · ");
        }
        if (cell.planned_date) parts.push(`Reach by ${fmtDate(cell.planned_date)}`);
        if (cell.actual_entry_date) parts.push(`Entered ${fmtDate(cell.actual_entry_date)}`);
        if (cell.actual_exit_date) parts.push(`Exited ${fmtDate(cell.actual_exit_date)}`);
        if (cell.extension_days) parts.push(`Extension ${fmtDays(cell.extension_days)}`);
        if (cell.overdue_days > 0) parts.push(`Overdue ${fmtDays(cell.overdue_days)}`);
        if (!cell.reached) parts.push("Not entered yet");
        return parts.join(" · ");
    }

    // ----------------------------------------------------------------
    // Total column
    // ----------------------------------------------------------------
    totalText(project) {
        return fmtDays(this.isOverdueView
            ? project.total_overdue_days
            : project.total_days_worked);
    }

    /** The total is red only when it IS an overdue figure: in Days Worked
     *  view the number is neutral and the red "overdue" caption below does
     *  the warning. */
    totalDanger(project) {
        return this.isOverdueView && project.total_overdue_days > 0;
    }

    /** Caption under the total. Days Worked: "overdue" (red) only when some
     *  stage is, nothing otherwise. Overdue Days: always present, so the
     *  column reads the same on every row; grey "0d overdue" when clean. */
    totalSub(project) {
        if (project.is_overdue) return "overdue";
        return this.isOverdueView ? "0d overdue" : "";
    }

    totalTitle(project) {
        const sub = project.is_overdue
            ? `${fmtDays(project.total_overdue_days)} overdue in total`
            : "No overdue stage";
        return this.isOverdueView
            ? `Overdue days over every stage · ${sub}`
            : `Days worked over every stage · ${sub}`;
    }

    // ----------------------------------------------------------------
    // Drill-down
    // ----------------------------------------------------------------
    openProject(project) {
        if (!project || !project.project_id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: project.project_name || "Project",
            res_model: "project.project",
            res_id: project.project_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

// Make the component available to the dashboard template, which our XML
// extends (t-inherit) to drop <ImplementationStageTable/> after the Project
// Performance row. Spread, not assign, so a sibling module registering its
// own section keeps working whichever of us loads first.
ProjectDashboard.components = { ...ProjectDashboard.components, ImplementationStageTable };
