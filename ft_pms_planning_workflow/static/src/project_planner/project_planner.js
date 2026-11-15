/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { PlannerMultiSelect } from "./multi_select";

export const PROJECT_PLANNER_TAG = "ft_pms_project_planner";
export const TASK_PLANNER_TAG = "ft_pms_task_planner";
// Same values as the `path` fields of the ir.actions.client records in
// views/planner_menus.xml, so URLs built from a tag-only doAction match the
// records and are resolved client-side on reload.
export const PROJECT_PLANNER_PATH = "pms-project-planner";
export const TASK_PLANNER_PATH = "pms-task-planner";

/**
 * Makes sure the controller of a planner always carries a breadcrumb title.
 * The action service only knows the name when the action dict has one; when
 * the action is rebuilt from the URL (reload, browser back, virtual
 * breadcrumb controllers) it falls back to the component's static
 * displayName, and this covers any remaining case.
 */
export function ensureDisplayName(env, fallback) {
    const config = env?.config;
    if (config?.setDisplayName && !config.getDisplayName?.()) {
        config.setDisplayName(fallback.toString());
    }
}
export const DEFAULT_RANGE_KEY = "next_60";
export const CUSTOM_RANGE_KEY = "custom";
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

/** Every range_key the backend accepts, grouped for the Days selector. */
export const RANGE_GROUPS = [
    {
        label: _t("Next"),
        options: [
            { key: "next_5", label: _t("Next 5 days") },
            { key: "next_10", label: _t("Next 10 days") },
            { key: "next_15", label: _t("Next 15 days") },
            { key: "next_30", label: _t("Next 30 days") },
            { key: "next_60", label: _t("Next 60 days") },
        ],
    },
    {
        label: _t("Last"),
        options: [
            { key: "last_5", label: _t("Last 5 days") },
            { key: "last_10", label: _t("Last 10 days") },
            { key: "last_15", label: _t("Last 15 days") },
            { key: "last_30", label: _t("Last 30 days") },
            { key: "last_60", label: _t("Last 60 days") },
        ],
    },
    {
        label: _t("This"),
        options: [
            { key: "this_week", label: _t("This week") },
            { key: "this_month", label: _t("This month") },
            { key: "this_quarter", label: _t("This quarter") },
        ],
    },
    {
        label: _t("Range (± N days around today)"),
        options: [
            { key: "range_15", label: _t("± 15 days") },
            { key: "range_30", label: _t("± 30 days") },
            { key: "range_60", label: _t("± 60 days") },
        ],
    },
    {
        label: _t("Custom"),
        options: [{ key: CUSTOM_RANGE_KEY, label: _t("Custom dates…") }],
    },
];
// Layouts of the grid ("cumulative" was the former name of "project").
const MODES = new Set(["project", "employee", "project_employee", "employee_project"]);
const RANGE_KEYS = new Set(RANGE_GROUPS.flatMap((g) => g.options.map((o) => o.key)));

function isoDate(value) {
    return typeof value === "string" && ISO_DATE_RE.test(value) ? value : false;
}

/** Two-letter initials of a name, used when the server sends none. */
export function nameInitials(name) {
    const words = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!words.length) {
        return "?";
    }
    const letters = words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[words.length - 1][0];
    return letters.toUpperCase();
}

/** Server options ({id, name, initials}) with initials always filled. */
export function normalizeOptions(list) {
    return (list || []).map((o) => ({ ...o, initials: o.initials || nameInitials(o.name) }));
}

/** Fallback legend, used only if the server does not send one. */
export const DEFAULT_LEGEND = [
    { color: "grey", label: _t("< 4 h") },
    { color: "yellow", label: _t("4 h – < 6 h") },
    { color: "green", label: _t("6 h – 8 h") },
    { color: "red", label: _t("> 8 h") },
];

const AVG_STATE_LABELS = {
    no_end_date: _t("No end date"),
    exhausted: _t("Estimate used up"),
    no_estimate: _t("No estimate"),
};

const CELL_COLORS = new Set(["grey", "yellow", "green", "red", "none"]);
const COLOR_LABELS = {
    grey: _t("grey (below 4 h)"),
    yellow: _t("yellow (4 h to under 6 h)"),
    green: _t("green (6 h to 8 h)"),
    red: _t("red (above 8 h)"),
};

/** A list of positive integer ids out of anything (params may come back as strings). */
export function toIdList(value) {
    if (value === undefined || value === null || value === false) {
        return [];
    }
    const list = Array.isArray(value) ? value : [value];
    return list.map((v) => parseInt(v, 10)).filter((v) => Number.isInteger(v) && v > 0);
}

/** Planner params of an action: params first, context as fallback. */
export function readActionParams(action, keys) {
    const params = action?.params || {};
    const context = action?.context || {};
    const result = {};
    for (const key of keys) {
        if (params[key] !== undefined) {
            result[key] = params[key];
        } else if (context[key] !== undefined) {
            result[key] = context[key];
        }
    }
    return result;
}

/**
 * Writes the filters back on the action object the action service holds for
 * this controller, so that coming back to it through the breadcrumbs mounts
 * the planner again with the same filters.
 */
export function persistActionParams(action, values) {
    if (!action) {
        return;
    }
    action.params = { ...(action.params || {}), ...values };
    action.context = { ...(action.context || {}), ...values };
}

function formatHours(value) {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return "";
    }
    const totalMinutes = Math.round(Math.abs(value) * 60);
    const hours = Math.floor(totalMinutes / 60);
    const minutes = totalMinutes % 60;
    return `${value < 0 ? "-" : ""}${hours}:${String(minutes).padStart(2, "0")}`;
}

/**
 * Project Status: one row per project (or per employee, or both nested, see
 * `modes`), one compact segment per day coloured by the PLANNED effort (task
 * estimates spread over their week) per allocated resource that day.
 * Clicking a segment opens the Task Planner on that project / resource and
 * date.
 */
export class ProjectPlanner extends Component {
    static template = "ft_pms_planning_workflow.ProjectPlanner";
    static components = { Layout, PlannerMultiSelect };
    static props = { ...standardActionServiceProps };
    static path = PROJECT_PLANNER_PATH;
    static displayName = _t("Project Status");

    setup() {
        ensureDisplayName(this.env, ProjectPlanner.displayName);
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.scrollRef = useRef("scroll");
        this.rangeGroups = RANGE_GROUPS;
        this.loadSeq = 0;
        this.scrollToTodayPending = true;

        const initial = readActionParams(this.props.action, [
            "range_key",
            "date_from",
            "date_to",
            "project_ids",
            "pm_ids",
            "resource_ids",
            "status_filter",
            "mode",
        ]);
        let rangeKey = RANGE_KEYS.has(initial.range_key) ? initial.range_key : DEFAULT_RANGE_KEY;
        const dateFrom = isoDate(initial.date_from);
        const dateTo = isoDate(initial.date_to);
        if (rangeKey === CUSTOM_RANGE_KEY && !(dateFrom && dateTo)) {
            rangeKey = DEFAULT_RANGE_KEY;
        }
        this.state = useState({
            filters: {
                range_key: rangeKey,
                date_from: dateFrom,
                date_to: dateTo,
                project_ids: toIdList(initial.project_ids),
                pm_ids: toIdList(initial.pm_ids),
                resource_ids: toIdList(initial.resource_ids),
                mode: MODES.has(initial.mode) ? initial.mode : "project",
                status_filter: initial.status_filter === "completed" ? "completed" : "all",
            },
            // Custom date inputs: edited locally, applied when both are valid.
            customFrom: dateFrom || "",
            customTo: dateTo || "",
            customError: "",
            data: null,
            loading: true,
        });

        onWillStart(() => this.load());
        onMounted(() => this.scrollToToday());
        onPatched(() => this.scrollToToday());
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    get filtersPayload() {
        const f = this.state.filters;
        const isCustom = f.range_key === CUSTOM_RANGE_KEY;
        return {
            range_key: f.range_key,
            date_from: isCustom ? f.date_from : false,
            date_to: isCustom ? f.date_to : false,
            project_ids: [...f.project_ids],
            pm_ids: [...f.pm_ids],
            status_filter: f.status_filter,
            resource_ids: [...f.resource_ids],
            mode: f.mode,
        };
    }

    async load() {
        const seq = ++this.loadSeq;
        const filters = this.filtersPayload;
        persistActionParams(this.props.action, filters);
        this.state.loading = true;
        try {
            const data = await this.orm.call("ft.pms.planner", "get_project_planner_data", [
                filters,
            ]);
            if (seq !== this.loadSeq) {
                return; // a newer request is in flight
            }
            this.lastLoadedKey = filters.range_key;
            this.state.data = this.prepare(data);
            this.scrollToTodayPending = true;
        } finally {
            if (seq === this.loadSeq) {
                this.state.loading = false;
            }
        }
    }

    /**
     * Precomputes everything the template needs once per load (classes,
     * header groups), so rendering a large grid is plain iteration.
     */
    prepare(data) {
        const days = data.days || [];
        const dayClasses = days.map((day, index) => {
            let cls = "";
            if (day.is_today) {
                cls += " o_pms_today";
            }
            if (day.is_weekend) {
                cls += " o_pms_weekend";
            }
            if (index > 0 && days[index - 1].week_label !== day.week_label) {
                cls += " o_pms_week_start";
            }
            return cls;
        });
        const dayLabel = (index, date) => {
            const day = days[index];
            if (!day) {
                return date || "";
            }
            const year = (day.date || "").slice(0, 4);
            return `${day.weekday} ${day.day} ${day.month} ${year}${day.is_today ? " " + _t("(today)") : ""}`;
        };
        /**
         * Planned-effort cells. `employeeName` set => employee row: value is
         * that person's hours on this project, colour/total are across ALL
         * their projects (collision); otherwise the project (cumulative) row:
         * value = average per allocated resource.
         */
        const decorate = (cells, employeeName = false, isTotal = false) =>
            (cells || []).map((cell, index) => {
                const color = CELL_COLORS.has(cell.color) ? cell.color : "none";
                const date = cell.date || days[index]?.date;
                const hasValue = cell.value !== null && cell.value !== undefined;
                const lines = [dayLabel(index, date)];
                if (!hasValue) {
                    lines.push(_t("No planned work"));
                } else if (employeeName) {
                    lines.push(
                        isTotal
                            ? _t("%(name)s: %(hours)s h planned on the shown projects", {
                                  name: employeeName,
                                  hours: formatHours(cell.value),
                              })
                            : _t("%(name)s: %(hours)s h planned on this project", {
                                  name: employeeName,
                                  hours: formatHours(cell.value),
                              })
                    );
                    if (cell.total !== undefined && cell.total !== null) {
                        lines.push(_t("Total across all projects: %s h", formatHours(cell.total)));
                    }
                    const others = cell.other_projects || [];
                    if (others.length) {
                        lines.push(isTotal ? _t("Projects:") : _t("Other projects:"));
                        for (const other of others) {
                            lines.push(`  • ${other.name}: ${formatHours(other.hours)} h`);
                        }
                    }
                } else {
                    lines.push(_t("Planned: %s h per resource", formatHours(cell.value)));
                    if (cell.total !== undefined && cell.total !== null) {
                        lines.push(_t("Total planned: %s h", formatHours(cell.total)));
                    }
                    if (cell.resources !== undefined && cell.resources !== null) {
                        lines.push(_t("Resources: %s", cell.resources));
                    }
                }
                if (hasValue) {
                    // What the colour was taken from: the person's total across
                    // all projects on employee rows, the per-resource average
                    // on project rows.
                    const basis =
                        employeeName && cell.total !== undefined && cell.total !== null
                            ? cell.total
                            : cell.value;
                    lines.push(
                        _t("Colour: %(colour)s, from %(hours)s h", {
                            colour: COLOR_LABELS[color] || color,
                            hours: formatHours(basis),
                        })
                    );
                }
                if (cell.collision) {
                    lines.push(_t("⚠ Allocated on more than one project this day"));
                }
                return {
                    date,
                    collision: Boolean(cell.collision),
                    tooltip: lines.join("\n"),
                    cls: `o_pms_seg o_pms_c_${color}${cell.collision ? " o_pms_collision" : ""}${
                        dayClasses[index] || ""
                    }`,
                };
            });

        // Header groups: one per ISO week (week_label), one per month.
        const weekGroups = [];
        const monthGroups = [];
        days.forEach((day, index) => {
            const lastWeek = weekGroups[weekGroups.length - 1];
            if (lastWeek && lastWeek.key === day.week_label) {
                lastWeek.span++;
            } else {
                weekGroups.push({ key: day.week_label, label: day.week_label || "", span: 1, index });
            }
            const monthKey = `${day.month}-${(day.date || "").slice(0, 7)}`;
            const lastMonth = monthGroups[monthGroups.length - 1];
            if (lastMonth && lastMonth.key === monthKey) {
                lastMonth.span++;
            } else {
                monthGroups.push({
                    key: monthKey,
                    label: `${day.month} ${(day.date || "").slice(0, 4)}`,
                    span: 1,
                    index,
                });
            }
        });

        // "Actual / Estimated" hours of a row over the selected period.
        const hoursOf = (item) => ({
            hoursLabel: `${item.actual_hhmm || "0:00"} / ${item.estimated_hhmm || "0:00"}`,
            hoursTitle: _t("Actual %(actual)s h (timesheets) / Estimated %(estimated)s h (planned) in the selected period", {
                actual: item.actual_hhmm || "0:00",
                estimated: item.estimated_hhmm || "0:00",
            }),
            over: (item.actual || 0) > (item.estimated || 0),
        });

        const projects = (data.projects || []).map((project) => {
            let avgLabel = "";
            let avgClass = "text-muted";
            if (project.avg_state === "ok" && project.avg_daily_effort !== null) {
                avgLabel = _t("%s h/day planned", formatHours(project.avg_daily_effort));
            } else if (project.avg_state && project.avg_state !== "overdue") {
                avgLabel = AVG_STATE_LABELS[project.avg_state] || "";
            }
            return {
                id: project.id,
                name: project.name,
                avgLabel,
                avgClass,
                ...hoursOf(project),
                cells: decorate(project.cells),
                employees: (project.employees || []).map((emp) => ({
                    id: emp.id,
                    userId: emp.user_id || emp.id || false,
                    name: emp.name,
                    initials: emp.initials || nameInitials(emp.name),
                    ...hoursOf(emp),
                    cells: decorate(emp.cells, emp.name),
                })),
            };
        });

        // Flat list of grid rows for the chosen layout. level 0 = main row,
        // level 1 = compact row underneath; cells === null => heading only.
        const mode = MODES.has(data.mode) ? data.mode : "project";
        const rows = [];
        const projectRow = (p, level, cells, userId = false, key = "") => ({
            key: `p${p.id}${key}`, kind: "project", level, name: p.name,
            projectId: p.id, userId, cells,
            hoursLabel: p.hoursLabel, hoursTitle: p.hoursTitle, over: p.over,
        });
        const employeeRow = (e, level, cells, projectId = false, key = "") => ({
            key: `e${e.id}${key}`, kind: "employee", level, name: e.name,
            initials: e.initials, projectId, userId: e.userId, cells,
            hoursLabel: e.hoursLabel, hoursTitle: e.hoursTitle, over: e.over,
        });
        const emptyRow = (key, text) => ({ key, kind: "empty", level: 1, name: text, cells: null });
        if (mode === "project") {
            projects.forEach((p) => rows.push(projectRow(p, 0, p.cells)));
        } else if (mode === "project_employee") {
            for (const p of projects) {
                rows.push(projectRow(p, 0, null));
                p.employees.forEach((e) => rows.push(employeeRow(e, 1, e.cells, p.id, `-p${p.id}`)));
                if (!p.employees.length) {
                    rows.push(emptyRow(`x${p.id}`, _t("No resources allocated in range")));
                }
            }
        } else {
            for (const emp of data.employees || []) {
                const e = {
                    id: emp.id,
                    userId: emp.user_id || emp.id || false,
                    name: emp.name,
                    initials: emp.initials || nameInitials(emp.name),
                    ...hoursOf(emp),
                };
                if (mode === "employee") {
                    rows.push(employeeRow(e, 0, decorate(emp.cells, emp.name, true)));
                    continue;
                }
                rows.push(employeeRow(e, 0, null));
                for (const p of emp.projects || []) {
                    rows.push(projectRow(
                        { id: p.id, name: p.name, ...hoursOf(p) }, 1,
                        decorate(p.cells, emp.name), e.userId, `-e${e.id}`));
                }
                if (!(emp.projects || []).length) {
                    rows.push(emptyRow(`x${e.id}`, _t("No projects planned in range")));
                }
            }
        }

        return {
            dateFrom: data.date_from,
            dateTo: data.date_to,
            today: data.today,
            days: days.map((day, index) => ({ ...day, cls: dayClasses[index] })),
            weekGroups,
            monthGroups,
            projects,
            rows,
            mode,
            firstColumn: mode.startsWith("employee") ? _t("Employee") : _t("Project"),
            options: {
                projects: normalizeOptions(data.options?.projects),
                pms: normalizeOptions(data.options?.pms),
                resources: normalizeOptions(data.options?.resources),
            },
            legend: data.legend && data.legend.length ? data.legend : DEFAULT_LEGEND,
        };
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------

    get options() {
        return this.state.data?.options || { projects: [], pms: [], resources: [] };
    }

    get modes() {
        return [
            { key: "project", label: _t("Project wise"),
              title: _t("One row per project, with its actual / estimated hours") },
            { key: "employee", label: _t("Employee wise"),
              title: _t("One row per employee, with their actual / estimated hours") },
            { key: "project_employee", label: _t("Project and Employee"),
              title: _t("Each project, then its employees with their actual / estimated hours") },
            { key: "employee_project", label: _t("Employee and Project"),
              title: _t("Each employee, then their projects with the actual / estimated hours") },
        ];
    }

    setFilter(name, value) {
        if (JSON.stringify(this.state.filters[name]) === JSON.stringify(value)) {
            return;
        }
        this.state.filters[name] = value;
        this.load();
    }

    /** View (layout) dropdown. */
    onModeChange(ev) {
        const key = ev.target.value;
        if (MODES.has(key)) {
            this.setFilter("mode", key);
        }
    }

    get isCustomRange() {
        return this.state.filters.range_key === CUSTOM_RANGE_KEY;
    }

    onRangeChange(ev) {
        const key = ev.target.value;
        if (key !== CUSTOM_RANGE_KEY) {
            this.state.customError = "";
            this.setFilter("range_key", key);
            return;
        }
        // Custom: prefill with the range currently shown, then apply.
        if (!this.state.customFrom || !this.state.customTo) {
            this.state.customFrom = this.state.data?.dateFrom || "";
            this.state.customTo = this.state.data?.dateTo || "";
        }
        this.state.filters.range_key = CUSTOM_RANGE_KEY;
        this.applyCustomRange();
    }

    onCustomDateChange(which, ev) {
        this.state[which] = ev.target.value || "";
        this.applyCustomRange();
    }

    /** Reloads with the custom dates once both are set and in order. */
    applyCustomRange() {
        const from = isoDate(this.state.customFrom);
        const to = isoDate(this.state.customTo);
        if (!from || !to) {
            this.state.customError = _t("Choose both dates.");
            return;
        }
        if (from > to) {
            this.state.customError = _t("The start date must be on or before the end date.");
            return;
        }
        this.state.customError = "";
        const f = this.state.filters;
        if (f.date_from === from && f.date_to === to && this.lastLoadedKey === CUSTOM_RANGE_KEY) {
            return; // already showing exactly this range
        }
        f.date_from = from;
        f.date_to = to;
        f.range_key = CUSTOM_RANGE_KEY;
        this.load();
    }

    // ------------------------------------------------------------------
    // Navigation
    // ------------------------------------------------------------------

    /**
     * One delegated listener for every segment of the grid. A segment carries
     * a project id (project rows), a user id (employee total rows, which span
     * every project of that person) or both (employee rows under a project,
     * project rows under an employee).
     */
    onGridClick(ev) {
        const seg = ev.target.closest(".o_pms_seg");
        if (!seg) {
            return;
        }
        const projectId = parseInt(seg.dataset.projectId, 10) || false;
        const userId = parseInt(seg.dataset.userId, 10) || false;
        if (!projectId && !userId) {
            return;
        }
        this.openTaskPlanner(projectId, seg.dataset.date || false, userId);
    }

    /**
     * Project bar -> Task Planner on that project; project + resource bar
     * (a resource under a project, or a project under a resource) -> that
     * project narrowed to that resource; resource total bar (Employee wise,
     * no project) -> all projects narrowed to that resource (project_id
     * false, the Task Planner then lists the person's tasks of every
     * project). The clicked day is passed as the focus date so the board
     * opens on its week. The Project Status filters themselves are not
     * forwarded (they stay on this action for the breadcrumb).
     */
    openTaskPlanner(projectId, focusDate, userId = false) {
        const f = this.filtersPayload;
        const params = {
            project_id: projectId || false,
            pm_ids: [],
            resource_ids: userId ? [userId] : [],
            focus_date: focusDate || false,
            range_key: f.range_key,
            status_filter: f.status_filter,
            mode: f.mode,
        };
        this.actionService.doAction({
            type: "ir.actions.client",
            tag: TASK_PLANNER_TAG,
            name: _t("Task Planner"),
            params,
            context: { ...params },
        });
    }

    /** Brings today's column next to the sticky columns once per load. */
    scrollToToday() {
        if (!this.scrollToTodayPending || !this.scrollRef.el) {
            return;
        }
        this.scrollToTodayPending = false;
        const scrollEl = this.scrollRef.el;
        const todayHead = scrollEl.querySelector("th.o_pms_day.o_pms_today");
        const sticky = scrollEl.querySelector("th.o_pms_col_project");
        if (!todayHead || !sticky) {
            scrollEl.scrollLeft = 0;
            return;
        }
        const stickyRight = sticky.offsetLeft + sticky.offsetWidth;
        const target = todayHead.offsetLeft - stickyRight - 3 * todayHead.offsetWidth;
        scrollEl.scrollLeft = Math.max(0, target);
    }
}

registry.category("actions").add(PROJECT_PLANNER_TAG, ProjectPlanner);
