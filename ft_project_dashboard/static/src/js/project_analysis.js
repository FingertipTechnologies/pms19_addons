/** @odoo-module **/

import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { KpiCard } from "./kpi_card";
import { SearchSelect } from "./search_select";
import { PERIODS, computeRange } from "./date_range";

// The board offers twelve ranges because it is a board — somebody scanning
// every project wants This Week as readily as This Year. One project's Analysis
// tab is read a different way: the question is almost always "how has this
// project gone", with a month or a quarter asked for occasionally. So the
// twelve are cut to six, which also keeps the row from wrapping inside a form
// notebook that is far narrower than the dashboard.
const TAB_PERIOD_IDS = ["month", "last_month", "quarter", "year", "all", "custom"];

// All Time, not This Month. The dashboard defaults to a month because it is
// answering "how are we doing right now" across every project at once. This tab
// opens on one project and the first question about a project is how it has
// gone in total — a monthly default would show a project delivered last year as
// a page of zeroes, which reads as broken rather than as finished.
const DEFAULT_PERIOD = "all";

// Sentinel the person picker can hold instead of an hr.employee id.
// Must match FILTER_UNASSIGNED in models/project_dashboard.py.
const FILTER_UNASSIGNED = "unassigned";

/**
 * The Analysis page on the project form.
 *
 * Renders the Project Dashboard's two card sections — Hours Utilisation and
 * Tasks Summary — scoped to the one project the form is showing.
 *
 * Every figure comes from the same ``ft.project.dashboard`` methods the board
 * calls, with ``project_id`` pinned to this record. Nothing is computed
 * here: a card on this tab and the same card on the dashboard scoped to this
 * project are the same query, so the two screens cannot drift apart.
 */
export class ProjectAnalysis extends Component {
    static template = "ft_project_dashboard.ProjectAnalysis";
    static components = { KpiCard, SearchSelect };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS.filter((p) => TAB_PERIOD_IDS.includes(p.id));
        this.state = useState({
            period: DEFAULT_PERIOD,
            dateFrom: null,
            dateTo: null,
            personId: "",
            resources: [],
            hours: {},
            tasks: {},
            loading: true,
            // Set when the form is on a project that has never been saved.
            // Every figure below is a server query keyed on the record id, and
            // there is no id yet — saying so beats an unexplained page of zeroes.
            unsaved: false,
            // The tab is rendered inside a form the user may not be able to
            // read every part of; a failure here must not take the form down
            // with it, so it is caught and shown in place.
            error: null,
        });

        // Monotonic request token. Flipping the period or the resource twice in
        // quick succession can land the replies out of order, leaving the tab
        // showing figures for the previous pick; a reply is only applied if no
        // newer request has started since.
        this._seq = 0;

        onWillStart(() => {
            this._applyPeriod(DEFAULT_PERIOD);
            return this.load();
        });
        // The form reuses this component when the user pages to the next
        // project with the pager, so the record id has to be watched rather
        // than read once at start-up.
        onWillUpdateProps((next) => {
            if (next.record?.resId !== this.props.record?.resId) {
                this.state.personId = "";
                // The incoming id explicitly, `false` included: props have not
                // been swapped yet at this point, so falling back to
                // this.projectId here would paint the project just left behind
                // onto a record that has none.
                return this.load(next.record?.resId || false);
            }
        });
    }

    // ----------------------------------------------------------------
    // Scope
    // ----------------------------------------------------------------
    get projectId() {
        return this.props.record?.resId || false;
    }

    /** The tab's range and person, in the shape the section methods expect.
     *
     *  The project is passed in rather than read off the props: on a pager step
     *  the id that matters is the incoming one, and props have not been swapped
     *  yet when that reload starts. It is this record either way — the tab has
     *  no project picker, which is the whole difference between it and the
     *  board. */
    _payload(projectId) {
        return {
            date_from: this.state.dateFrom,
            date_to: this.state.dateTo,
            project_id: projectId,
            person_id: this.state.personId || false,
        };
    }

    _applyPeriod(period) {
        const { dateFrom, dateTo } = computeRange(period, this.state);
        this.state.period = period;
        this.state.dateFrom = dateFrom;
        this.state.dateTo = dateTo;
    }

    async onPeriodChange(period) {
        this._applyPeriod(period);
        // Custom waits for Apply — reloading on the click would query whatever
        // half-filled pair of dates the inputs happen to be holding.
        if (period !== "custom") {
            await this.load();
        }
    }

    onCustomDateChange(field, ev) {
        this.state[field] = ev.target.value || null;
    }

    async applyCustomRange() {
        this.state.period = "custom";
        await this.load();
    }

    async onPersonChange(value) {
        this.state.personId = value || "";
        await this.load();
    }

    get hasPersonFilter() {
        return !!this.state.personId;
    }

    async clearPersonFilter() {
        this.state.personId = "";
        await this.load();
    }

    async refresh() {
        await this.load();
    }

    // ----------------------------------------------------------------
    // Data
    // ----------------------------------------------------------------
    async load(projectId = this.projectId) {
        if (!projectId) {
            this.state.unsaved = true;
            this.state.loading = false;
            return;
        }
        this.state.unsaved = false;
        const token = ++this._seq;
        this.state.loading = true;
        const payload = this._payload(projectId);
        try {
            // Hours Utilisation is measured off two different models — timesheet
            // lines for the role and activity rows, task records for the hour
            // totals — so it takes two calls, merged behind the one filter bar.
            // Same split as the board, for the same reason.
            const [hours, hoursSummary, tasks, resources] = await Promise.all([
                this.orm.call("ft.project.dashboard", "get_hours_utilisation", [payload]),
                this.orm.call("ft.project.dashboard", "get_task_hours_summary", [payload]),
                this.orm.call("ft.project.dashboard", "get_tasks_summary", [payload]),
                // Refetched with the rest rather than once at start-up, because
                // paging to another project changes who its people are.
                this.orm.call("ft.project.dashboard", "get_project_resources", [payload]),
            ]);
            // A newer pick started while these were in flight — its reply is the
            // one that matches the controls, so drop this result.
            if (token !== this._seq) {
                return;
            }
            // Disjoint key sets (plain figures vs `hs_`-prefixed ones), so the
            // merge cannot have one call overwrite the other's numbers.
            this.state.hours = { ...hours, ...hoursSummary };
            this.state.tasks = tasks;
            this.state.resources = resources;
            this.state.error = null;
        } catch (e) {
            if (token !== this._seq) {
                return;
            }
            this.state.error = e.message?.data?.message || e.message || String(e);
        } finally {
            if (token === this._seq) {
                this.state.loading = false;
            }
        }
    }

    // ----------------------------------------------------------------
    // Cards
    // ----------------------------------------------------------------
    get hours() {
        return this.state.hours || {};
    }

    get tasks() {
        return this.state.tasks || {};
    }

    /** Every person who booked time on this project, with Unassigned offered
     *  first — a real subset on the tasks side, where plenty carry no assignee. */
    get resourceOptions() {
        return [{ id: FILTER_UNASSIGNED, name: "Unassigned" }].concat(
            this.state.resources || []
        );
    }

    /** Open the record list a card's number was taken from.
     *
     *  The domains are built server-side alongside the counts and already carry
     *  this project, so the list a card opens is literally the recordset its
     *  number came from — including the person filter when one is set.
     */
    _openAction(action) {
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

    openTaskKpi(key) {
        this._openAction(this.tasks.actions && this.tasks.actions[key]);
    }

    openHoursKpi(key) {
        this._openAction(this.hours.hours_actions && this.hours.hours_actions[key]);
    }
}

// A view widget rather than a client action: it has to sit inside the project
// form's notebook and read the record the form is on, which is exactly what
// this registry hands a component (`record` and `readonly` props).
registry.category("view_widgets").add("ft_project_analysis", {
    component: ProjectAnalysis,
});
