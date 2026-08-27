/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { browser } from "@web/core/browser/browser";
import { loadJS } from "@web/core/assets";
import { KpiCard } from "./kpi_card";
import { ChartCard } from "./chart_card";
import { DataTable } from "./data_table";
import { SearchSelect } from "./search_select";

const PERIODS = [
    { id: "today", label: "Today" },
    { id: "week", label: "This Week" },
    { id: "month", label: "This Month" },
    { id: "quarter", label: "This Quarter" },
    { id: "year", label: "This Year" },
    // No date bounds at all — the whole history of every project. The board
    // otherwise always had a range applied, with no way to step back and see a
    // project end to end. The server already accepts null dates everywhere, so
    // this is simply the absence of the two leaves rather than a special case.
    { id: "all", label: "All Time" },
    { id: "custom", label: "Custom" },
];

const DEFAULT_PERIOD = "month";

// Sentinel the person picker can hold instead of an hr.employee id.
// Must match FILTER_UNASSIGNED in models/project_dashboard.py.
const FILTER_UNASSIGNED = "unassigned";

// The three row filters on Project Performance, in render order. `group` matches
// the `hidden_group` the server stamps on each row, so which stage names belong
// to which toggle is decided server-side and never duplicated here — this list
// only supplies the labels.
// Full forms for the four abbreviated delivery columns, shown on hover. Defined
// once and spread into both Project Performance and Resource Performance, which
// carry the same four measures — one per project, one per person — so the two
// tables can never explain them differently.
const DELIVERY_COL_HELP = {
    de: "DE — Delivery Efficiency. Estimated ÷ Actual hours, as a percentage. "
        + "Target 90–110%: under 90% means the work took materially longer than "
        + "estimated, over 110% means the estimate was padded. Only counts tasks "
        + "carrying both an estimate and logged time.",
    otd: "OTD — On-Time Delivery. Delivered on time ÷ delivered with a deadline, "
        + "as a percentage. Target 95% or above. Tasks delivered without a "
        + "deadline cannot be judged and are excluded (see DWD).",
    rwr: "RWR — Rework Rate. Reopened ÷ delivered, as a percentage. Target 10% "
        + "or below. A task counts as reopened each time it is moved back out of "
        + "a completed stage, counted from when this feature was installed.",
    dwd: "DWD — Delivered Without Deadline. Delivered tasks that had no deadline "
        + "set, so OTD could not judge them. A high number means the OTD "
        + "percentage beside it rests on only part of the work.",
};

const PROJECT_STAGE_TOGGLES = [
    { group: "closed", label: "Closed" },
    { group: "amc", label: "AMC" },
    { group: "general", label: "General" },
];

// Drilling into a card opens a list view as a new action; coming back rebuilds
// this dashboard from scratch, which reset the header to its defaults and threw
// away the selection. Mirror the header into sessionStorage so the round trip
// returns to what the user was actually looking at. Only the period/range and
// the project/status scope are stored — the data itself is always refetched, so
// nothing stale is ever shown.
const SCOPE_KEY = "ft_project_dashboard.scope";

function readStoredScope() {
    try {
        const stored = JSON.parse(browser.sessionStorage.getItem(SCOPE_KEY) || "null");
        // Guard against a stale key from an older build naming a period that no
        // longer exists, which would leave the dashboard with no range at all.
        if (stored && PERIODS.some((p) => p.id === stored.period)) {
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

function fmt(date) {
    // -> 'YYYY-MM-DD' in local time.
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

export class ProjectDashboard extends Component {
    static template = "ft_project_dashboard.ProjectDashboard";
    static components = { KpiCard, ChartCard, DataTable, SearchSelect };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = useState({
            period: DEFAULT_PERIOD,
            dateFrom: null,
            dateTo: null,
            // Header scope. One Project picker and one Status picker for the
            // whole board, replacing the copies every section used to carry:
            // the same two questions asked five times over could be answered
            // five different ways at once, and nothing on screen said which
            // answer a given number came from.
            projectId: "",
            // Project Manager. A project-level scope like Project and Status —
            // it narrows the board to the projects this person runs, whoever
            // booked the time on them.
            managerId: "",
            stageId: "",
            data: null,
            loading: true,
            // Dropdown contents for the header pickers and the one person
            // picker each section carries. Fetched once — they do not depend on
            // the range or the scope.
            filterOptions: { projects: [], managers: [], stages: [], resources: [] },
            // Table text searches. These stay per-table: they are free text
            // over rows already on screen, not a question for the server.
            projectSearch: "",
            resourceSearch: "",
            resourceProjectSearch: "",
            projectHoursSearch: "",
            deliverySearch: "",
            // Project Performance hides Closed / AMC / General projects by
            // default, each behind its own toggle so they can be brought back
            // independently. Keyed by the `hidden_group` the server stamps on
            // each row, so adding a fourth group needs no change here.
            projectShowStage: { closed: false, amc: false, general: false },
            // The two filtered sections keep one person picker and nothing else.
            // Each holds an override: the figures the server recomputed for its
            // own picker, or null to read the header-scoped payload exactly as
            // it arrived.
            //
            // Hours Utilisation absorbed the old Task Hours Summary section, so
            // its override merges two server payloads behind the one picker —
            // see reloadHoursUtilisation.
            hoursPersonId: "",
            hoursOverride: null,
            hoursLoading: false,
            tasksPersonId: "",
            tasksOverride: null,
            tasksLoading: false,
        });

        // Monotonic request token per section. These queries are heavy enough
        // that flipping a dropdown twice can land the two responses out of
        // order, leaving the section showing figures for the previous pick; a
        // reply is only applied if no newer request has started since.
        this._reqSeq = { hours: 0, tasks: 0 };

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            const restored = readStoredScope();
            if (restored) {
                this.state.projectId = restored.projectId || "";
                this.state.managerId = restored.managerId || "";
                this.state.stageId = restored.stageId || "";
                if (restored.period === "custom") {
                    // _applyPeriod's "custom" branch reads the dates back off
                    // state, so they must be in place before it runs.
                    this.state.dateFrom = restored.dateFrom;
                    this.state.dateTo = restored.dateTo;
                }
            }
            // Named periods are recomputed against today rather than restored
            // from the stored dates: coming back to "This Year" should mean this
            // year now, not the year it was when the range was first picked.
            this._applyPeriod(restored?.period || DEFAULT_PERIOD);
            await this.loadData();
            // Filter choices are independent of the range and the scope, so they
            // are fetched once. A failure here only costs empty dropdowns, never
            // the board.
            try {
                this.state.filterOptions = await this.orm.call(
                    "ft.project.dashboard", "get_hours_filter_options", []
                );
            } catch (e) {
                console.warn("Filter options failed to load", e);
            }
        });
    }

    // ----------------------------------------------------------------
    // Header: date range
    // ----------------------------------------------------------------
    _persistScope() {
        writeStoredScope({
            period: this.state.period,
            dateFrom: this.state.dateFrom,
            dateTo: this.state.dateTo,
            projectId: this.state.projectId,
            managerId: this.state.managerId,
            stageId: this.state.stageId,
        });
    }

    _applyPeriod(period) {
        const now = new Date();
        let from = null;
        let to = fmt(now);
        switch (period) {
            case "today":
                from = fmt(now);
                break;
            case "week": {
                const d = new Date(now);
                const day = (d.getDay() + 6) % 7; // Monday = 0
                d.setDate(d.getDate() - day);
                from = fmt(d);
                break;
            }
            case "month":
                from = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
                break;
            case "quarter": {
                const q = Math.floor(now.getMonth() / 3);
                from = fmt(new Date(now.getFullYear(), q * 3, 1));
                break;
            }
            case "year":
                from = fmt(new Date(now.getFullYear(), 0, 1));
                break;
            case "all":
                // Both ends open. `to` is reset as well as `from`, since it
                // defaults to today above and would otherwise still cut off
                // anything dated in the future — deadlines especially.
                from = null;
                to = null;
                break;
            case "custom":
                // Keep whatever is already in the custom inputs.
                from = this.state.dateFrom;
                to = this.state.dateTo;
                break;
        }
        this.state.period = period;
        this.state.dateFrom = from;
        this.state.dateTo = to;
        this._persistScope();
    }

    async onPeriodChange(period) {
        this._applyPeriod(period);
        if (period !== "custom") {
            await this.loadData();
        }
    }

    onCustomDateChange(field, ev) {
        this.state[field] = ev.target.value || null;
    }

    async applyCustomRange() {
        this.state.period = "custom";
        // Set directly rather than via _applyPeriod, so persist here too.
        this._persistScope();
        await this.loadData();
    }

    // ----------------------------------------------------------------
    // Header: Project / Manager / Status scope
    // ----------------------------------------------------------------
    /** Compare a dropdown option id with the stored filter value.
     *
     *  Lives here rather than inline in the template because Owl resolves bare
     *  identifiers against the component, so JS globals like String() are not
     *  callable from a template expression. Option ids arrive as numbers and
     *  select values as strings, hence the coercion.
     */
    isFilterSelected(optionId, current) {
        return String(optionId) === String(current);
    }

    get hasScopeFilter() {
        return !!(this.state.projectId || this.state.managerId || this.state.stageId);
    }

    async onScopeChange(field, ev) {
        await this.onScopePick(field, ev.target.value);
    }

    /** Same as onScopeChange but taking the value directly, for SearchSelect,
     *  which hands back an id rather than a DOM event. */
    async onScopePick(field, value) {
        this.state[field] = value || "";
        this._persistScope();
        await this.loadData();
    }

    async clearScopeFilters() {
        this.state.projectId = "";
        this.state.managerId = "";
        this.state.stageId = "";
        this._persistScope();
        await this.loadData();
    }

    /** The header scope, in the shape get_dashboard_data expects. */
    _scopePayload() {
        return {
            project_id: this.state.projectId || false,
            manager_id: this.state.managerId || false,
            stage_id: this.state.stageId || false,
        };
    }

    // ----------------------------------------------------------------
    // Data loading
    // ----------------------------------------------------------------
    async loadData() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "ft.project.dashboard",
                "get_dashboard_data",
                [this.state.dateFrom, this.state.dateTo, this._scopePayload()]
            );
        } finally {
            this.state.loading = false;
        }
        // The payload that just arrived is already scoped, so a section with no
        // dropdown set reads correctly as it stands. One that HAS a PM or a
        // Developer picked is still holding figures computed for the PREVIOUS
        // header scope, so it has to be refetched or it would quietly contradict
        // every card around it.
        await this._reloadFilteredSections();
    }

    async _reloadFilteredSections() {
        await Promise.all([
            this.reloadHoursUtilisation(),
            this.reloadTasksSummary(),
        ]);
    }

    async refresh() {
        await this.loadData();
    }

    // ----------------------------------------------------------------
    // Drill-downs
    // ----------------------------------------------------------------
    openTimesheets(billableOnly) {
        const domain = [["project_id", "!=", false]];
        if (this.state.dateFrom) domain.push(["date", ">=", this.state.dateFrom]);
        if (this.state.dateTo) domain.push(["date", "<=", this.state.dateTo]);
        // The header scope has to reach the drill-down too, or the list opens
        // wider than the card that was clicked.
        if (this.state.projectId) {
            domain.push(["project_id", "=", parseInt(this.state.projectId, 10)]);
        }
        if (this.state.managerId) {
            domain.push(["project_id.user_id", "=", parseInt(this.state.managerId, 10)]);
        }
        if (this.state.stageId) {
            domain.push(["project_id.stage_id", "=", parseInt(this.state.stageId, 10)]);
        }
        if (billableOnly) domain.push(["project_id.allow_billable", "=", true]);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: billableOnly ? "Billable Timesheets" : "Timesheets",
            res_model: "account.analytic.line",
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    // Generic KPI drill-down: opens the record list the server prepared for
    // this card, so the list length always equals the number on the card. No-op
    // for cards with no backing records (sums, N/A) — those pass no action.
    openKpi(key) {
        const action = this.kpis.actions && this.kpis.actions[key];
        if (!action) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: action.name,
            res_model: action.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: action.domain || [],
            target: "current",
        });
    }

    /** Drill-down for a Tasks Summary card.
     *
     *  Reads from `tasks` rather than `kpis` so a filtered section opens the
     *  filtered list: when a filter is active the actions come back with the
     *  refetched figures, so the list always matches the number clicked.
     */
    openTaskKpi(key) {
        const action = this.tasks.actions && this.tasks.actions[key];
        if (!action) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: action.name,
            res_model: action.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: action.domain || [],
            target: "current",
        });
    }

    onProjectHoursSegment(index) {
        const ids = this.projectHoursData?.meta?.project_ids;
        const pid = ids?.[index];
        if (pid) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "project.project",
                res_id: pid,
                views: [[false, "form"]],
                target: "current",
            });
        }
    }

    // Convenience getters for the template
    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }
    get tables() {
        return this.state.data?.tables || {};
    }

    // ----------------------------------------------------------------
    // Column definitions for the three full-width tables. DataTable handles
    // sorting / pagination / rows-per-page / scroll from these.
    // ----------------------------------------------------------------
    // Project Performance. Existing columns kept; DE / OTD / RWR / DWD added,
    // same four measures as Resource Performance but per project. Delivered
    // rides along as the denominator behind the three percentages.
    get projectColumns() {
        return [
            { key: "project", label: "Project Name" },
            { key: "status", label: "Status" },
            { key: "start_date", label: "Start Date", date: true },
            { key: "uat_date", label: "UAT Date", date: true },
            { key: "end_date", label: "End Date", date: true },
            { key: "estimated", label: "Estimated Hrs", numeric: true },
            { key: "actual", label: "Actual Hrs", numeric: true },
            { key: "delivered", label: "Delivered", numeric: true,
              help: "Tasks this project delivered in the selected period — the "
                  + "denominator behind DE, OTD and RWR. Shown so a percentage "
                  + "drawn from two tasks is not read as if it came from two "
                  + "hundred." },
            { key: "de_rate", label: "DE (%)", numeric: true, help: DELIVERY_COL_HELP.de },
            { key: "otd_rate", label: "OTD (%)", numeric: true, help: DELIVERY_COL_HELP.otd },
            { key: "rwr_rate", label: "RWR (%)", numeric: true, help: DELIVERY_COL_HELP.rwr },
            { key: "dwd", label: "DWD", numeric: true, help: DELIVERY_COL_HELP.dwd },
        ];
    }
    get resourceColumns() {
        return [
            { key: "employee", label: "Resource Name", group: true, cls: "ftpd_res_name" },
            { key: "role", label: "Role", group: true },
            { key: "project", label: "Project Name" },
            { key: "status", label: "Project Status" },
            { key: "days_left", label: "Days Left", numeric: true },
            { key: "hours_spent", label: "Hours Spent", numeric: true },
            { key: "estimated", label: "Estimated Hrs", numeric: true },
        ];
    }

    // Resource Performance: the original counts kept, with the three PM KPIs
    // added alongside them.
    //   DE  (%) = Estimated / Actual                target 90-110%
    //   OTD (%) = On time / Delivered w/ deadline   target >= 95%
    //   RWR (%) = Reopened / Delivered              target <= 10%
    //   DWD     = Delivered Without Deadline — the tasks OTD could not judge
    //
    // Every original column is kept. On-Time % and OTD (%) carry the same
    // number, as do No Deadline and DWD — both pairs are shown because both
    // labels were asked for.
    get deliveryColumns() {
        return [
            { key: "employee", label: "Resource Name", group: true, cls: "ftpd_res_name" },
            { key: "role", label: "Role", group: true },
            { key: "delivered", label: "Delivered", numeric: true,
              help: "Tasks this person delivered in the selected period — the "
                  + "denominator behind DE, OTD and RWR." },
            { key: "on_time", label: "On Time", numeric: true,
              help: "Delivered on or before the deadline, compared by calendar "
                  + "day in your timezone." },
            { key: "late", label: "Late", numeric: true,
              help: "Delivered after the deadline." },
            { key: "on_time_rate", label: "On-Time %", numeric: true,
              help: "On Time ÷ (On Time + Late). Carries the same number as "
                  + "OTD (%); both labels are shown because both were asked for." },
            { key: "no_deadline", label: "No Deadline", numeric: true,
              help: "Delivered with no deadline set, so neither On Time nor Late "
                  + "could apply. Same number as DWD." },
            { key: "de_rate", label: "DE (%)", numeric: true, help: DELIVERY_COL_HELP.de },
            { key: "otd_rate", label: "OTD (%)", numeric: true, help: DELIVERY_COL_HELP.otd },
            { key: "rwr_rate", label: "RWR (%)", numeric: true, help: DELIVERY_COL_HELP.rwr },
            { key: "dwd", label: "DWD", numeric: true, help: DELIVERY_COL_HELP.dwd },
            { key: "overdue_open", label: "Open & Overdue", numeric: true,
              help: "Tasks still open whose deadline has passed. A snapshot of "
                  + "now, deliberately not filtered by the selected period — it "
                  + "is the check on OTD, which only counts work that finished." },
        ];
    }

    // ----------------------------------------------------------------
    // Table searches. Rows arrive from the server already scoped by the header,
    // so all that is left here is free-text narrowing of what is on screen.
    // Nothing in this section drops rows by date or by project any more: doing
    // that in the browser hid rows without changing the aggregates inside them,
    // so the figures answered one question while the rows answered another.
    // ----------------------------------------------------------------
    // Dropping rows here is safe in a way it would not be elsewhere on the
    // board: every figure in this table belongs to the row it sits on, so
    // hiding a row removes its numbers with it. There is no cross-row total
    // that could keep counting what is no longer on screen — the pager's
    // "Showing x of N" recounts from the filtered set.
    get projectRows() {
        const q = (this.state.projectSearch || "").trim().toLowerCase();
        let rows = this.tables.project_status || [];
        // A row with no hidden_group is always visible; one with a group shows
        // only while that group's own toggle is on.
        rows = rows.filter(
            (r) => !r.hidden_group || this.state.projectShowStage[r.hidden_group]
        );
        if (q) {
            rows = rows.filter((r) => (r.project || "").toLowerCase().includes(q));
        }
        return rows;
    }
    onProjectSearch(ev) {
        this.state.projectSearch = ev.target.value || "";
    }
    onProjectShowStage(group, ev) {
        this.state.projectShowStage[group] = ev.target.checked;
    }

    /** The three toggles with the row count each is currently holding back.
     *  The counts come off the unfiltered payload, so they stay put as boxes are
     *  ticked and explain an empty-looking table rather than leaving it looking
     *  broken. */
    get projectStageToggles() {
        const rows = this.tables.project_status || [];
        return PROJECT_STAGE_TOGGLES.map((toggle) => ({
            ...toggle,
            count: rows.filter((r) => r.hidden_group === toggle.group).length,
        }));
    }

    get resourceRows() {
        const q = (this.state.resourceSearch || "").trim().toLowerCase();
        const pq = (this.state.resourceProjectSearch || "").trim().toLowerCase();
        let rows = this.tables.resource_status || [];
        if (q) {
            rows = rows.filter((r) => (r.employee || "").toLowerCase().includes(q));
        }
        if (pq) {
            rows = rows.filter((r) => (r.project || "").toLowerCase().includes(pq));
        }
        return rows;
    }
    onResourceSearch(ev) {
        this.state.resourceSearch = ev.target.value || "";
    }
    onResourceProjectSearch(ev) {
        this.state.resourceProjectSearch = ev.target.value || "";
    }

    get deliveryRows() {
        const q = (this.state.deliverySearch || "").trim().toLowerCase();
        const rows = this.tables.delivery || [];
        if (!q) return rows;
        return rows.filter((r) => (r.employee || "").toLowerCase().includes(q));
    }
    onDeliverySearch(ev) {
        this.state.deliverySearch = ev.target.value || "";
    }

    // ----------------------------------------------------------------
    // The two filtered sections — PM / Developer, recomputed server-side.
    // ----------------------------------------------------------------
    /** Cards read from here: the filtered figures when a dropdown is set,
     *  otherwise the header-scoped ones that shipped with the payload.
     *
     *  Hours Utilisation's three rows all read from this one getter, including
     *  the `th_*` task hour totals absorbed from the old Task Hours Summary
     *  section — one section, one override, so the rows can never end up
     *  showing two different filter states at once. */
    get hours() {
        return this.state.hoursOverride || this.kpis;
    }

    get tasks() {
        return this.state.tasksOverride || this.kpis;
    }

    get hasHoursFilter() {
        return this._hasFilter("hours");
    }

    get hasTasksFilter() {
        return this._hasFilter("tasks");
    }

    // Both sections carry one picker each, so the plumbing is written once and
    // keyed by prefix. Date, Project and Status are deliberately absent: they
    // belong to the header and reach the server through _filterPayload instead.
    _filterFields(prefix) {
        return [`${prefix}PersonId`];
    }

    _hasFilter(prefix) {
        return this._filterFields(prefix).some((f) => !!this.state[f]);
    }

    /** The header's range and scope, narrowed by one section's picker. */
    _filterPayload(prefix) {
        return {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
            project_id: this.state.projectId || false,
            manager_id: this.state.managerId || false,
            stage_id: this.state.stageId || false,
            person_id: this.state[`${prefix}PersonId`],
        };
    }

    /** Every active employee, with Unassigned offered first.
     *
     *  One list rather than the old separate PM and Developer lists: which
     *  dropdown you reached for no longer changes what the answer means, so
     *  there is no reason to split the people up. The job title is in the label
     *  because it is no longer implied by the picker you used. */
    get resourceOptions() {
        return [{ id: FILTER_UNASSIGNED, name: "Unassigned" }].concat(
            this.state.filterOptions.resources || []
        );
    }

    onHoursFilter(value) {
        this.state.hoursPersonId = value || "";
        this.reloadHoursUtilisation();
    }

    onTasksFilter(value) {
        this.state.tasksPersonId = value || "";
        this.reloadTasksSummary();
    }

    clearHoursFilters() {
        this._clearFilters("hours");
    }

    clearTasksFilters() {
        this._clearFilters("tasks");
    }

    _clearFilters(prefix) {
        for (const f of this._filterFields(prefix)) {
            this.state[f] = "";
        }
        this.state[`${prefix}Override`] = null;
        // Bump the token so a reply still in flight for the cleared filter
        // cannot land afterwards and put the section back into a filtered state
        // the dropdowns no longer show. That reply will now skip its own
        // clean-up, so the spinner has to be cleared here or it never stops.
        this._reqSeq[prefix] += 1;
        this.state[`${prefix}Loading`] = false;
    }

    /** Hours Utilisation is measured off two different models — timesheet lines
     *  for the role and activity rows, task records for the hour totals — so it
     *  takes two calls, merged into the one override behind its one filter bar. */
    async reloadHoursUtilisation() {
        await this._reloadSection("hours", [
            "get_hours_utilisation",
            "get_task_hours_summary",
        ]);
    }

    async reloadTasksSummary() {
        await this._reloadSection("tasks", "get_tasks_summary");
    }

    /** Refetch one section for its own dropdowns. Nothing set hands the section
     *  back to the header-scoped payload rather than calling the server. */
    async _reloadSection(prefix, methods) {
        if (!this._hasFilter(prefix)) {
            this.state[`${prefix}Override`] = null;
            // Same as _clearFilters: invalidating an in-flight reply means that
            // reply will not clear the spinner, so do it here.
            this._reqSeq[prefix] += 1;
            this.state[`${prefix}Loading`] = false;
            return;
        }
        const token = ++this._reqSeq[prefix];
        this.state[`${prefix}Loading`] = true;
        try {
            const names = Array.isArray(methods) ? methods : [methods];
            const payload = this._filterPayload(prefix);
            const parts = await Promise.all(
                names.map((m) =>
                    this.orm.call("ft.project.dashboard", m, [payload])
                )
            );
            // A newer pick started while these were in flight — its reply is the
            // one that matches the dropdowns, so drop this result.
            if (token !== this._reqSeq[prefix]) {
                return;
            }
            // Disjoint key sets (plain figures vs `th_`-prefixed ones), so the
            // merge cannot have one call overwrite the other's numbers.
            this.state[`${prefix}Override`] = Object.assign({}, ...parts);
        } catch (e) {
            // Keep the last good figures rather than blanking the cards.
            console.warn(`${prefix} section reload failed`, e);
        } finally {
            if (token === this._reqSeq[prefix]) {
                this.state[`${prefix}Loading`] = false;
            }
        }
    }

    // ----------------------------------------------------------------
    // Project Hours Analysis chart — search filter + horizontal scroll.
    // ----------------------------------------------------------------
    get projectHoursData() {
        const d = this.charts.project_hours;
        if (!d || !d.labels) return d || { labels: [], datasets: [] };
        const q = (this.state.projectHoursSearch || "").trim().toLowerCase();
        if (!q) return d;
        const keep = [];
        d.labels.forEach((l, i) => {
            if ((l || "").toLowerCase().includes(q)) keep.push(i);
        });
        const ids = (d.meta && d.meta.project_ids) || [];
        return {
            labels: keep.map((i) => d.labels[i]),
            datasets: d.datasets.map((ds) => ({ ...ds, data: keep.map((i) => ds.data[i]) })),
            meta: { project_ids: keep.map((i) => ids[i]) },
        };
    }
    // Width per project group so many bars scroll horizontally rather than
    // squashing together; a sensible floor keeps a short list full-width.
    get projectHoursMinWidth() {
        const n = (this.projectHoursData.labels || []).length;
        return Math.max(n * 90, 640);
    }
    onProjectHoursSearch(ev) {
        this.state.projectHoursSearch = ev.target.value || "";
    }

    // Dual-axis options for the Progress Trend bar chart. The server buckets the
    // range into days/weeks/months, so every label it sends is meant to be shown.
    get trendOptions() {
        return {
            interaction: { mode: "index", intersect: false },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { autoSkip: false, maxRotation: 45, minRotation: 0 },
                },
                y: {
                    type: "linear", position: "left", beginAtZero: true,
                    title: { display: true, text: "Hours" },
                },
                y1: {
                    type: "linear", position: "right", beginAtZero: true,
                    grid: { drawOnChartArea: false },
                    title: { display: true, text: "Tasks" },
                },
            },
        };
    }
}

registry.category("actions").add("ft_project_dashboard", ProjectDashboard);
