/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate, formatDate } from "@web/core/l10n/dates";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSortable } from "@web/core/utils/sortable_owl";
import { Layout } from "@web/search/layout";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { PlannerMultiSelect } from "@ft_pms_planning_workflow/project_planner/multi_select";
import {
    TASK_PLANNER_PATH,
    TASK_PLANNER_TAG,
    ensureDisplayName,
    persistActionParams,
    readActionParams,
    toIdList,
} from "@ft_pms_planning_workflow/project_planner/project_planner";

const DEFAULT_WEEK_COUNT = 6;
const STATUS_FILTERS = ["open", "completed", "all"];
export const DEFAULT_STATUS_FILTER = "open";

const CATEGORY_LABELS = {
    overdue: _t("Overdue"),
    not_started: _t("Not started"),
    working: _t("Working"),
    completed: _t("Completed"),
};

export const TOTALS_TOOLTIP = _t(
    "Totals over ALL tasks allocated to this week that match the Project / PM / Resource " +
        "filters (whatever the Status selector hides).\n" +
        "Estimated = sum of the tasks' estimated hours.\n" +
        "Open = estimated hours of tasks not yet completed.\n" +
        "Completed = estimated hours of tasks in a completed stage.\n" +
        "Estimated / Open / Completed are all based on the ESTIMATE, not on time logged."
);

export const ACTUAL_TOOLTIP = _t(
    "Actual (timesheets) = hours actually logged in timesheets on these tasks " +
        "(all dates). It is not part of the estimate-based totals above and can be " +
        "higher or lower than the estimate."
);

export const STATUS_OPTIONS = [
    { key: "open", label: _t("Open"), title: _t("Overdue, not started and in-progress tasks") },
    { key: "completed", label: _t("Completed"), title: _t("Only tasks in a completed stage") },
    { key: "all", label: _t("All"), title: _t("Open and completed tasks") },
];

/**
 * Task Planner: one Kanban column per week (allocation = task.sprint_id),
 * starting at the current (or focus) week. A task moves between weeks by drag
 * and drop or the card's week picker; the move is applied at once (no dialog),
 * the deadline moves to the new week's Sunday, the original deadline is kept
 * on the task and the move is recorded in Week Moves.
 */
export class TaskPlanner extends Component {
    static template = "ft_pms_planning_workflow.TaskPlanner";
    static components = { Layout, PlannerMultiSelect, Dropdown, DropdownItem };
    static props = { ...standardActionServiceProps };
    static path = TASK_PLANNER_PATH;
    static displayName = _t("Task Planner");

    setup() {
        ensureDisplayName(this.env, TaskPlanner.displayName);
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.boardRef = useRef("board");
        this.totalsTooltip = TOTALS_TOOLTIP;
        this.actualTooltip = ACTUAL_TOOLTIP;
        this.statusOptions = STATUS_OPTIONS;
        this.categoryLabels = CATEGORY_LABELS;
        this.loadSeq = 0;
        this.dragging = false;
        this.revealPending = true;

        const initial = readActionParams(this.props.action, [
            "project_id",
            "pm_ids",
            "resource_ids",
            "status_filter",
            "focus_date",
            "week_offset",
            "week_count",
            // Carried through untouched so the Project Planner breadcrumb
            // context stays complete.
            "range_key",
            "mode",
        ]);
        const projectId = toIdList(initial.project_id)[0] || false;
        this.passThrough = { range_key: initial.range_key, mode: initial.mode };
        this.state = useState({
            filters: {
                project_id: projectId,
                pm_ids: toIdList(initial.pm_ids),
                resource_ids: toIdList(initial.resource_ids),
                status_filter: STATUS_FILTERS.includes(initial.status_filter)
                    ? initial.status_filter
                    : DEFAULT_STATUS_FILTER,
                focus_date:
                    typeof initial.focus_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(initial.focus_date)
                        ? initial.focus_date
                        : false,
                week_offset: parseInt(initial.week_offset, 10) || 0,
                week_count: parseInt(initial.week_count, 10) || DEFAULT_WEEK_COUNT,
            },
            data: null,
            loading: true,
        });

        onWillStart(() => this.load());
        onMounted(() => this.revealFocusWeek());
        onPatched(() => this.revealFocusWeek());

        useSortable({
            ref: this.boardRef,
            elements: ".o_pms_tp_card",
            groups: ".o_pms_tp_column",
            connectGroups: true,
            cursor: "move",
            placeholderClasses: ["o_pms_tp_card_placeholder"],
            onDragStart: () => {
                this.dragging = true;
            },
            onDragEnd: () => {
                // Cleared after the click that ends the drag has fired.
                setTimeout(() => {
                    this.dragging = false;
                });
            },
            onDrop: (params) => this.onCardDropped(params),
        });
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------

    get filtersPayload() {
        const f = this.state.filters;
        return {
            project_id: f.project_id || false,
            pm_ids: [...f.pm_ids],
            resource_ids: [...f.resource_ids],
            status_filter: f.status_filter,
            focus_date: f.focus_date || false,
            week_offset: f.week_offset,
            week_count: f.week_count,
        };
    }

    async load() {
        const seq = ++this.loadSeq;
        const filters = this.filtersPayload;
        persistActionParams(this.props.action, { ...this.passThrough, ...filters });
        this.state.loading = true;
        try {
            const data = await this.orm.call("ft.pms.planner", "get_task_planner_data", [filters]);
            if (seq !== this.loadSeq) {
                return;
            }
            this.state.data = this.prepare(data);
        } finally {
            if (seq === this.loadSeq) {
                this.state.loading = false;
            }
        }
    }

    /** Splits each week's (already sorted) tasks into category sections. */
    prepare(data) {
        const weeks = (data.weeks || []).map((week) => {
            const sections = [];
            for (const task of week.tasks || []) {
                let section = sections[sections.length - 1];
                if (!section || section.category !== task.category) {
                    section = {
                        category: task.category,
                        label: CATEGORY_LABELS[task.category] || task.category || "",
                        tasks: [],
                    };
                    sections.push(section);
                }
                section.tasks.push(task);
            }
            const totals = week.totals || {};
            return {
                ...week,
                tasks: week.tasks || [],
                sections,
                totals: {
                    estimated_hhmm: totals.estimated_hhmm || "0:00",
                    open_hhmm: totals.open_hhmm || "0:00",
                    completed_hhmm: totals.completed_hhmm || "0:00",
                    actual_hhmm: totals.actual_hhmm || "0:00",
                },
            };
        });
        const taskWeek = new Map();
        for (const week of weeks) {
            for (const task of week.tasks) {
                taskWeek.set(task.id, week);
            }
        }
        this.revealPending = true;
        return {
            project: data.project || false,
            weeks,
            taskWeek,
            options: {
                projects: data.options?.projects || [],
                pms: data.options?.pms || [],
                resources: data.options?.resources || [],
            },
        };
    }

    // ------------------------------------------------------------------
    // Filters & navigation
    // ------------------------------------------------------------------

    get options() {
        return this.state.data?.options || { projects: [], pms: [], resources: [] };
    }

    get projectOptions() {
        const options = [...this.options.projects];
        const current = this.state.data?.project;
        if (current && !options.some((p) => p.id === current.id)) {
            options.unshift(current);
        }
        return options;
    }

    setFilter(name, value) {
        if (JSON.stringify(this.state.filters[name]) === JSON.stringify(value)) {
            return;
        }
        this.state.filters[name] = value;
        this.load();
    }

    setStatusFilter(key) {
        this.setFilter("status_filter", key);
    }

    shiftWeeks(delta) {
        this.setFilter("week_offset", this.state.filters.week_offset + delta);
    }

    resetWeeks() {
        this.setFilter("week_offset", 0);
    }

    clearFocus() {
        this.state.filters.week_offset = 0;
        this.setFilter("focus_date", false);
    }

    columnClass(week) {
        return {
            o_pms_tp_current: week.is_current,
            o_pms_tp_focus: week.contains_focus,
        };
    }

    /** Scrolls the focus (or current) week into view once per load. */
    revealFocusWeek() {
        if (!this.revealPending || !this.boardRef.el || !this.state.data) {
            return;
        }
        this.revealPending = false;
        const column =
            this.boardRef.el.querySelector(".o_pms_tp_column.o_pms_tp_focus") ||
            this.boardRef.el.querySelector(".o_pms_tp_column.o_pms_tp_current");
        if (column) {
            // The board is position: relative, so offsetLeft is board-relative.
            const board = this.boardRef.el;
            const left = column.offsetLeft;
            const right = left + column.offsetWidth;
            if (left < board.scrollLeft || right > board.scrollLeft + board.clientWidth) {
                board.scrollLeft = Math.max(0, left - 16);
            }
        }
    }

    // ------------------------------------------------------------------
    // Moving tasks
    // ------------------------------------------------------------------

    findWeek(weekId) {
        return this.state.data?.weeks.find((w) => w.id === weekId) || false;
    }

    onCardDropped({ element, parent }) {
        // The sortable hook never moves the card in the DOM: the board is
        // re-rendered from the server once the move is saved.
        if (!parent || !this.state.data) {
            return;
        }
        const taskId = parseInt(element.dataset.taskId, 10);
        const targetId = parseInt(parent.dataset.weekId, 10);
        const fromWeek = this.state.data.taskWeek.get(taskId);
        if (!taskId || !targetId || !fromWeek || fromWeek.id === targetId) {
            return;
        }
        const task = fromWeek.tasks.find((t) => t.id === taskId);
        if (task) {
            this.moveTask(task, targetId);
        }
    }

    /** Visible weeks a task can be moved to (all but its current one). */
    moveTargets(task) {
        const fromWeek = this.state.data?.taskWeek.get(task.id);
        return (this.state.data?.weeks || []).filter((w) => !fromWeek || w.id !== fromWeek.id);
    }

    async moveTask(task, weekId) {
        const week = this.findWeek(weekId);
        await this.orm.call("ft.pms.planner", "move_task_week", [task.id, weekId, false]);
        await this.load();
        let deadline = _t("the week's Sunday");
        if (week && week.end) {
            try {
                deadline = formatDate(deserializeDate(week.end));
            } catch {
                deadline = week.end;
            }
        }
        this.notification.add(
            _t("Moved to %(week)s — deadline now %(deadline)s; recorded in Week Moves", {
                week: week ? week.name || week.label : _t("the new week"),
                deadline,
            }),
            { type: "success" }
        );
    }

    // ------------------------------------------------------------------
    // Opening records
    // ------------------------------------------------------------------

    openTask(taskId) {
        if (this.dragging) {
            return;
        }
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: taskId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(TASK_PLANNER_TAG, TaskPlanner);
