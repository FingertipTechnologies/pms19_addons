/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { browser } from "@web/core/browser/browser";
import { loadJS } from "@web/core/assets";
import { KpiCard } from "./kpi_card";
import { ChartCard } from "./chart_card";
import { FunnelChart } from "./funnel_chart";
import { TableCard } from "./table_card";
import { MonthBoard } from "./month_board";

// The probability at which crm.lead is won and the form paints its WON ribbon.
// Mirrors WON_PROBABILITY in models/sales_dashboard.py — the drill-downs below
// have to select the same records their cards counted.
const WON_PROBABILITY = 100;

// Each month board and the status domain a click on one of its months opens.
// Keeps the drill-down in step with what the server counted for that board.
// One entry per board KIND; every window (last / next / selected period) of the
// same kind counts the same records, so they share a kind.
//
// The domains themselves are built by _statusDomain() rather than declared here,
// because "lost" depends on which stages are Lost — data the server sends with
// the payload. Hard-coding active=false here is what let an unarchived lost deal
// fall out of the Lost drill-down while the card still counted it.
const BOARD_DOMAINS = {
    pipeline_last_months: { name: "Pipeline", kind: "open" },
    pipeline_next_months: { name: "Pipeline", kind: "open" },
    pipeline_period_months: { name: "Pipeline", kind: "open" },
    closed_last_months: { name: "Won Opportunities", kind: "won" },
    closed_period_months: { name: "Won Opportunities", kind: "won" },
    lost_last_months: { name: "Lost Opportunities", kind: "lost" },
    lost_period_months: { name: "Lost Opportunities", kind: "lost" },
};

// The breakdown card shows one of these at a time, chosen from a dropdown.
// Stage-wise and executive-wise answer the same question ("where is the
// revenue?") along different axes, so they share a slot rather than both
// occupying screen height permanently.
const BREAKDOWNS = [
    { id: "stage", label: "Stage-wise" },
    { id: "executive", label: "Executive-wise" },
];

// Which window the three month boards show.
//
// "Last 6 Months" and "Next 6 Months" are fixed windows and must not overlap —
// in July that is Feb..Jul and Aug..Jan, which is why the server starts the
// forward window at NEXT month. "Selected Period" follows the filter instead,
// so This Year renders January through December (zero months included) rather
// than stopping at the current month.
const MONTH_VIEWS = [
    { id: "last", label: "Last 6 Months" },
    { id: "next", label: "Next 6 Months" },
    { id: "period", label: "Selected Period" },
];

// Board key per (kind, window). "Next 6 Months" only exists for the pipeline —
// there is nothing already won or lost in the future — so the other two kinds
// stay on their trailing window when it is selected.
const BOARD_KEYS = {
    pipeline: { last: "pipeline_last_months", next: "pipeline_next_months", period: "pipeline_period_months" },
    closed: { last: "closed_last_months", next: "closed_last_months", period: "closed_period_months" },
    lost: { last: "lost_last_months", next: "lost_last_months", period: "lost_period_months" },
};

// Columns for the executive-wise report. Declared once here rather than inline
// in the template so the table stays a data-driven component.
const EXEC_COLUMNS = [
    { key: "name", label: "Sales Executive", type: "text" },
    { key: "count", label: "Opportunities", type: "number" },
    { key: "amount", label: "Expected Revenue", type: "money" },
    { key: "won", label: "Sales Closed", type: "number" },
    { key: "lost", label: "Lost", type: "number" },
    { key: "conversion", label: "Conversion Ratio", type: "percent" },
];

// Period presets, in two pill groups.
//
// "current" spans the whole calendar period the user is standing in — This
// Month covers the month, future days included (see _applyPeriod).
// "trailing" looks backwards and always ends today or earlier, and is itself
// two different things that must not be confused:
//   * Last Month / Last 2 Months are CALENDAR months — in August that is July,
//     and June + July. They never include any part of the current month.
//   * Last 30/60/90 Days are ROLLING windows recomputed from today on every
//     load, so the dashboard does not have to be reopened to move with the date.
const PERIODS = [
    { id: "today", label: "Today", group: "current" },
    { id: "week", label: "This Week", group: "current" },
    { id: "month", label: "This Month", group: "current" },
    { id: "quarter", label: "This Quarter", group: "current" },
    { id: "year", label: "This Year", group: "current" },
    { id: "last_month", label: "Last Month", group: "trailing" },
    { id: "last_two_months", label: "Last 2 Months", group: "trailing" },
    { id: "last_30_days", label: "Last 30 Days", group: "trailing" },
    { id: "last_60_days", label: "Last 60 Days", group: "trailing" },
    { id: "last_90_days", label: "Last 90 Days", group: "trailing" },
    { id: "custom", label: "Custom", group: "trailing" },
];

// Rolling-window presets and their length in days, so the three share one
// implementation instead of three near-identical switch arms.
const ROLLING_DAYS = {
    last_30_days: 30,
    last_60_days: 60,
    last_90_days: 90,
};

function fmt(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

// Day 0 of the following month = the last day of month `m`. Leap years and
// 30/31-day months come out right without a table of month lengths.
function endOfMonth(year, month) {
    return new Date(year, month + 1, 0);
}

// The breadcrumb restores props.state, but the browser Back button rebuilds the
// action from the URL as a brand-new controller with no exported state. Mirror
// the filter into sessionStorage so both routes come back to the same period.
const FILTER_KEY = "ft_sales_dashboard.filter";

function readStoredFilter() {
    try {
        return JSON.parse(browser.sessionStorage.getItem(FILTER_KEY) || "null");
    } catch {
        return null;
    }
}

function writeStoredFilter(filter) {
    try {
        browser.sessionStorage.setItem(FILTER_KEY, JSON.stringify(filter));
    } catch {
        // Storage unavailable/full: filters just won't persist.
    }
}

export class SalesDashboard extends Component {
    static template = "ft_sales_dashboard.SalesDashboard";
    static components = { KpiCard, ChartCard, FunnelChart, TableCard, MonthBoard };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        // Rendered as one dropdown with two optgroups. Eleven presets laid out
        // as pills took two rows of the header and pushed the salesperson
        // filter and the custom-range inputs onto a third; collapsed into a
        // select they cost one control's width and the grouping survives as
        // the optgroup headings.
        this.periodGroups = [
            { label: "Current period", items: PERIODS.filter((p) => p.group === "current") },
            { label: "Trailing period", items: PERIODS.filter((p) => p.group === "trailing") },
        ];
        this.execColumns = EXEC_COLUMNS;
        this.breakdowns = BREAKDOWNS;
        this.monthViews = MONTH_VIEWS;

        // props.state covers the breadcrumb; sessionStorage covers browser Back
        // (which rebuilds the action fresh). Either way we land on the period
        // the user last chose rather than the default.
        const restored = this.props.state || readStoredFilter();
        this.state = useState({
            period: restored?.period || "month",
            dateFrom: restored?.dateFrom ?? null,
            dateTo: restored?.dateTo ?? null,
            // Selected salesperson: null = the whole team, UNASSIGNED_USER (-1)
            // = opportunities with nobody on them. Restored with the period so
            // the breadcrumb and the Back button both return to the same view.
            userId: restored?.userId ?? null,
            // Which axis the breakdown card shows, and which way the pipeline
            // board looks. Restored with the filter so returning via the
            // breadcrumb lands on the same view the user left.
            breakdown: restored?.breakdown || "stage",
            monthView: restored?.monthView || "last",
            data: null,
            loading: true,
        });

        useSetupAction({
            getLocalState: () => this._filter(),
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            // Only compute a range on a fresh open; a restored one already has
            // its dates (and recomputing would discard a custom range).
            if (!restored?.period) {
                this._applyPeriod("month");
            }
            await this.loadData();
        });
    }

    // Each CALENDAR preset spans its WHOLE period, not "start of period ->
    // today".
    //
    // Ending every range at today is what made This Year stop at July and what
    // hid an opportunity dated the 31st from This Month while today was the
    // 31st but the range had already been cut. A period filter answers "how
    // does this month/quarter/year look", so it has to cover the month,
    // quarter or year — the future part of it included. Last Month and Last 2
    // Months are whole calendar months for the same reason, and being wholly in
    // the past they are already complete.
    //
    // The rolling presets are the deliberate exception: "Last 30 Days" is a
    // window ending today, so it must NOT run to the end of any calendar unit.
    _applyPeriod(period) {
        const now = new Date();
        const y = now.getFullYear();
        const m = now.getMonth();
        let from = null;
        let to = fmt(now);
        switch (period) {
            case "today":
                from = fmt(now);
                break;
            case "week": {
                // Monday-based week, Monday to Sunday.
                const start = new Date(now);
                start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
                const end = new Date(start);
                end.setDate(end.getDate() + 6);
                from = fmt(start);
                to = fmt(end);
                break;
            }
            case "month":
                from = fmt(new Date(y, m, 1));
                to = fmt(endOfMonth(y, m));
                break;
            case "quarter": {
                const q = Math.floor(m / 3);
                from = fmt(new Date(y, q * 3, 1));
                to = fmt(endOfMonth(y, q * 3 + 2));
                break;
            }
            case "year":
                from = fmt(new Date(y, 0, 1));
                to = fmt(new Date(y, 11, 31));
                break;
            case "last_month": {
                // The previous CALENDAR month, whole: in August, 1–31 July.
                // new Date(y, m - 1, 1) rolls the year back on its own, so
                // January correctly resolves to the previous December.
                const start = new Date(y, m - 1, 1);
                from = fmt(start);
                to = fmt(endOfMonth(start.getFullYear(), start.getMonth()));
                break;
            }
            case "last_two_months": {
                // The previous two CALENDAR months, whole: in August, 1 June to
                // 31 July. The current month is excluded, so this and This
                // Month never count the same deal twice.
                const start = new Date(y, m - 2, 1);
                const last = new Date(y, m - 1, 1);
                from = fmt(start);
                to = fmt(endOfMonth(last.getFullYear(), last.getMonth()));
                break;
            }
            case "last_30_days":
            case "last_60_days":
            case "last_90_days": {
                // Rolling window ending TODAY, inclusive of today — so "Last 30
                // Days" is today and the 29 days before it, 30 days in total,
                // and it moves forward by itself every day.
                const start = new Date(now);
                start.setDate(start.getDate() - (ROLLING_DAYS[period] - 1));
                from = fmt(start);
                to = fmt(now);
                break;
            }
            case "custom":
                from = this.state.dateFrom;
                to = this.state.dateTo;
                break;
        }
        this.state.period = period;
        this.state.dateFrom = from;
        this.state.dateTo = to;
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
        await this.loadData();
    }

    // The salesperson options, straight from the payload. During the very first
    // load there is no payload yet and the control shows "All Salespeople"
    // alone; every later reload keeps the previous data in place, so the list
    // does not blink empty while a filter is being applied.
    get salespeople() {
        return this.state.data?.salespeople || [];
    }

    /** Selected salesperson's name, for the card titles. Null = whole team. */
    get salespersonName() {
        const found = this.salespeople.find((p) => p.id === this.state.userId);
        return found ? found.name : null;
    }

    async onSalespersonChange(ev) {
        // Empty string = "All Salespeople". Compared against "" rather than
        // tested for falsiness, because the Unassigned sentinel is a number and
        // a plain truthiness check would throw it away along with the blank.
        const raw = ev.target.value;
        this.state.userId = raw === "" ? null : Number(raw);
        await this.loadData();
    }

    _filter() {
        return {
            period: this.state.period,
            dateFrom: this.state.dateFrom,
            dateTo: this.state.dateTo,
            userId: this.state.userId,
            breakdown: this.state.breakdown,
            monthView: this.state.monthView,
        };
    }

    // View switches are presentation only — the payload already carries every
    // breakdown and every month window, so there is nothing to re-fetch.
    setBreakdown(id) {
        this.state.breakdown = id;
        writeStoredFilter(this._filter());
    }

    setMonthView(id) {
        this.state.monthView = id;
        writeStoredFilter(this._filter());
    }

    /** Board key for a kind ("pipeline" | "closed" | "lost") in the current window. */
    boardKey(kind) {
        const keys = BOARD_KEYS[kind];
        return keys[this.state.monthView] || keys.last;
    }

    board(kind) {
        return this.boards[this.boardKey(kind)] || {};
    }

    /** Window label for a card title, matching the button the user picked. */
    _windowLabel(kind) {
        // Closed/Lost have no forward window; say what they actually show.
        const id = kind !== "pipeline" && this.state.monthView === "next"
            ? "last"
            : this.state.monthView;
        const view = MONTH_VIEWS.find((v) => v.id === id);
        return (view || MONTH_VIEWS[0]).label;
    }

    get pipelineBoard() {
        return this.board("pipeline");
    }
    get closedBoard() {
        return this.board("closed");
    }
    get lostBoard() {
        return this.board("lost");
    }
    get pipelineTitle() {
        return `Opportunity Pipeline — ${this._windowLabel("pipeline")}`;
    }
    get closedTitle() {
        return `Opportunities Closed — ${this._windowLabel("closed")}`;
    }
    get lostTitle() {
        return `Opportunities Lost — ${this._windowLabel("lost")}`;
    }

    async loadData() {
        // Every load reflects an applied filter, so this is the one choke point
        // where persisting it is always correct.
        writeStoredFilter(this._filter());
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "ft.sales.dashboard",
                "get_dashboard_data",
                [this.state.dateFrom, this.state.dateTo, this.state.userId]
            );
        } finally {
            this.state.loading = false;
        }
    }

    async refresh() {
        await this.loadData();
    }

    // Drill-downs
    //
    // active_test: false on EVERY drill-down. Lost opportunities are archived,
    // and the server counts them (see _leads() in models/sales_dashboard.py);
    // a list view that quietly re-applies the active filter would open fewer
    // records than the card counted, which is exactly the mismatch being fixed.
    // Domains that pin active=true are unaffected by it.
    // The salesperson filter is applied HERE, at the single choke point every
    // drill-down goes through, rather than in each of the seven callers below.
    // Adding it per-caller is the version that eventually ships a list showing
    // the whole team from a card that counted one person.
    //
    // The leaves come from the payload (the server's own _user_domain), so the
    // Unassigned option opens `user_id = false` rather than the -1 sentinel the
    // control carries. Appending them is safe next to a domain that leads with
    // "|": Odoo ANDs the top-level expressions of a domain list.
    _openLeads(domain, name) {
        const who = this.salespersonName;
        this.action.doAction({
            type: "ir.actions.act_window",
            name: (name || "Opportunities") + (who ? ` — ${who}` : ""),
            res_model: "crm.lead",
            views: [[false, "list"], [false, "form"]],
            domain: [...(domain || []), ...this._userDomain()],
            context: { active_test: false },
            target: "current",
        });
    }

    /** The selected salesperson as domain leaves, as the server resolved them. */
    _userDomain() {
        return this.state.data?.user_domain || [];
    }

    // Drill-downs mirror the server, including WHICH date field each figure is
    // measured on — otherwise a drill-down opens a different set of records
    // from the one the KPI counted.
    //
    // The bounds themselves come straight from the payload rather than being
    // rebuilt here. create_date and date_closed are stored in UTC while the
    // filter names days in the user's Odoo timezone, and the browser cannot
    // reliably reproduce that conversion (its own timezone need not match the
    // Odoo user's). Taking the server's resolved window removes the whole class
    // of card-says-15-list-shows-14 mismatch instead of trying to keep two
    // implementations in step.
    _fieldDomain(field) {
        const [from, to] = this.state.data?.bounds?.[field] || [null, null];
        const domain = [];
        if (from) {
            domain.push([field, ">=", from]);
        }
        if (to) {
            domain.push([field, "<=", to]);
        }
        return domain;
    }

    // The Opportunities card, the funnel and the executive table. Which field
    // that is comes from the payload (GENERATED_FIELD on the server) rather than
    // being hard-coded here, so the cards and their drill-downs cannot end up
    // measured on two different dates.
    _generatedDomain() {
        return this._fieldDomain(this.state.data?.generated_field || "date_deadline");
    }

    // The population BOTH left-hand cards describe: every stage, live records
    // only, dated by the generated field. Mirrors _generated_domain() on the
    // server. active=true is explicit here rather than left to the list view's
    // default, because _openLeads passes active_test:false — without it the
    // drill-down would list the archived deals the cards deliberately exclude.
    _generatedPopulation() {
        return [["active", "=", true], ...this._generatedDomain()];
    }

    /** Stage ids that mean "lost", as resolved by the server for this payload. */
    get lostStageIds() {
        return this.state.data?.lost_stage_ids || [];
    }

    // The status half of a domain, mirroring _open_domain / _won_domain /
    // _lost_domain on the server. Lost is "archived OR in a Lost stage", and
    // open therefore has to exclude the Lost stages, or a deal dragged to Lost
    // without being archived would be counted by both.
    _statusDomain(kind) {
        const lost = this.lostStageIds;
        if (kind === "lost") {
            return ["|", ["active", "=", false], ["stage_id", "in", lost]];
        }
        if (kind === "won") {
            // Won by either of Odoo's two routes: the Won stage, or Probability
            // at 100 with the stage left where it was. The form's WON ribbon
            // tests only the second, so a stage-only test here would open a
            // drill-down that contradicts the records inside it.
            return [
                "&",
                ["active", "=", true],
                "|",
                ["probability", ">=", WON_PROBABILITY],
                ["stage_id.is_won", "=", true],
            ];
        }
        return [
            ["active", "=", true],
            ["probability", "<", WON_PROBABILITY],
            ["stage_id.is_won", "=", false],
            ["stage_id", "not in", lost],
        ];
    }

    // Pipeline Value: Expected Closing.
    _deadlineDomain() {
        return this._fieldDomain("date_deadline");
    }

    // Sales Closed / Opportunities Lost: Closed Date.
    _closedDomain() {
        return this._fieldDomain("date_closed");
    }

    openOpportunities() {
        this._openLeads(
            [["type", "=", "opportunity"], ...this._generatedPopulation()],
            "Opportunities"
        );
    }

    // Everything not won. Mirrors _not_won_domain() on the server, the OR
    // included: ("stage_id.is_won", "=", false) on its own resolves to
    // "stage_id IN (the not-won stages)", which silently drops an opportunity
    // that has no stage at all.
    _notWonDomain() {
        return [
            "&",
            ["probability", "<", WON_PROBABILITY],
            "|",
            ["stage_id", "=", false],
            ["stage_id.is_won", "=", false],
        ];
    }

    // Pipeline Value counts the Opportunities population MINUS the won deals —
    // money still to come, not money already banked — so the drill-down carries
    // the same exclusion. Without it the list disagrees with the card it was
    // opened from, and by exactly the value of the won deals in the period.
    openPipeline() {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ...this._generatedPopulation(),
                ...this._notWonDomain(),
            ],
            "Pipeline Value"
        );
    }

    openWon() {
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ...this._statusDomain("won"),
                ...this._closedDomain(),
            ],
            "Won Opportunities"
        );
    }

    openLost() {
        // The "|" of the lost domain must lead the leaves it joins, so the
        // status domain goes first and the date leaves AND onto it.
        this._openLeads(
            [
                ["type", "=", "opportunity"],
                ...this._statusDomain("lost"),
                ...this._closedDomain(),
            ],
            "Lost Opportunities"
        );
    }

    // Click a funnel band -> open exactly the opportunities it counts. The
    // trailing "Lost" band holds the live records sitting in a Lost stage; the
    // bands are drawn from the same population as the Opportunities card, which
    // excludes archived records, so the band filters on stage, not on active.
    openStage(stage) {
        const isLost = stage.stageId === "lost";
        const domain = [
            ["type", "=", "opportunity"],
            ...(isLost
                ? [["stage_id", "in", this.lostStageIds]]
                : [["stage_id", "=", stage.stageId || false]]),
            ...this._generatedPopulation(),
        ];
        this._openLeads(domain, stage.label || "Opportunities");
    }

    // Click a month card -> that month's opportunities for that board. The
    // board's own date field is used (Expected Closing for pipeline, Closed
    // Date for won/lost), so the list matches the number on the card.
    openBoardMonth(boardKey, month) {
        const spec = BOARD_DOMAINS[boardKey];
        const board = this.boards[boardKey] || {};
        const field = board.date_field || "date_deadline";
        // month.from / month.to are the window the server BUCKETED this card in,
        // already resolved to UTC for the Datetime boards. Rebuilding the month
        // bounds here would ignore the user's timezone and open a window shifted
        // by the offset — the card and its list would disagree by whatever sits
        // within 5h30m of the month boundary.
        const bounds = [];
        if (month.from) {
            bounds.push([field, ">=", month.from]);
        }
        if (month.to) {
            bounds.push([field, "<=", month.to]);
        }

        this._openLeads(
            [["type", "=", "opportunity"], ...this._statusDomain(spec.kind), ...bounds],
            `${spec.name} — ${month.label}`
        );
    }

    // Click an opportunity inside a month card -> open that record.
    openLead(lead) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: lead.name,
            res_model: "crm.lead",
            res_id: lead.id,
            views: [[false, "form"]],
            // Lost leads are archived; without this the form refuses to open.
            context: { active_test: false },
            target: "current",
        });
    }

    get kpis() {
        return this.state.data?.kpis || {};
    }
    get charts() {
        return this.state.data?.charts || {};
    }
    get boards() {
        return this.state.data?.boards || {};
    }
    get executives() {
        return this.state.data?.executives?.rows || [];
    }
    // Totals row for the executive table. Rendered as a pinned footer rather
    // than an extra row so sorting or scrolling can never separate a total
    // from the rows it totals.
    get executiveTotal() {
        return this.state.data?.executives?.total || null;
    }
}

registry.category("actions").add("ft_sales_dashboard", SalesDashboard);
