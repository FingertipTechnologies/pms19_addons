/** @odoo-module **/

import { onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { projectTaskKanbanView } from "@project/views/project_task_kanban/project_task_kanban_view";

// The column for the week today falls in, and the class the stylesheet
// colours it with.
const CURRENT_COLUMN_CLASS = "o_ft_current_week_column";

// How much of the previous week is left showing to the left of the current
// one. The point of the board is that the weeks run as a calendar, so the
// current week is put AT the left edge rather than in the middle — but flush
// against it there is nothing to say the board scrolls that way at all, and a
// sliver of last week says it without costing any of this week's width.
const PEEK_PX = 56;

/** The nearest ancestor that actually scrolls sideways, or null. */
function horizontalScrollParent(el) {
    for (let node = el.parentElement; node; node = node.parentElement) {
        const { overflowX } = getComputedStyle(node);
        if (
            (overflowX === "auto" || overflowX === "scroll") &&
            node.scrollWidth > node.clientWidth
        ) {
            return node;
        }
    }
    return null;
}

/**
 * The full-screen Week Board, opened on the week being worked.
 *
 * The columns are weeks and they run oldest first (qa_testapp.sprint._order),
 * which is what makes the board read as a calendar: left is behind us, right
 * is still to come. It also meant the board opened on the project's OLDEST
 * week — on anything with history behind it, months of finished work, with
 * this week off the right-hand edge and nothing to tell it from its
 * neighbours once it was scrolled to.
 *
 * So the current week is outlined, badged and brought to the left of the
 * screen when the board opens. The weeks before it are then one scroll to the
 * left and the weeks after it one scroll to the right, which is the whole
 * shape of the board in a single gesture.
 *
 * Built on the project's own kanban view class rather than on the plain one,
 * so everything project_task_kanban does for a task board — its records, its
 * headers, its controller, the rotting mixin — still happens here. Only the
 * renderer is extended.
 */
export class WeekKanbanRenderer extends projectTaskKanbanView.Renderer {
    setup() {
        super.setup();
        // The week already scrolled to. Held so the board is brought back to
        // this week ONCE: dragging a card, loading more records into a column
        // and folding a column all patch this component, and hauling the
        // reader back to today on each of those would make the board unusable.
        // Cleared when the column leaves the screen — a search or a filter can
        // take it off — so that getting it back reveals it again.
        this.revealedWeekId = null;

        // The columns do not exist when setup runs, so the scroll happens on
        // the patch that draws them — and on mount, which is where it fires
        // when the board arrives with its groups already loaded.
        onMounted(() => this.revealCurrentWeek());
        onPatched(() => this.revealCurrentWeek());
    }

    /**
     * The week today falls in, as the action put it in the context.
     *
     * Passed down from project.action_view_week_board rather than looked up
     * here: the server was already holding a cursor when it built the action,
     * and a week is only "current" by its Monday and Sunday, which is
     * arithmetic this side has no business repeating.
     *
     * False unless the board is actually grouped by week. Regrouping by stage
     * leaves `group.value` a project.task.type id, and one of those is sooner
     * or later going to be the same number as a week's.
     */
    get currentWeekId() {
        const list = this.props.list;
        if (list.groupByField?.name !== "sprint_id") {
            return false;
        }
        return list.context?.ft_current_week_id || false;
    }

    getGroupClasses(group, isGroupProcessing) {
        const classes = super.getGroupClasses(...arguments);
        const weekId = this.currentWeekId;
        if (!weekId || group.value !== weekId) {
            return classes;
        }
        return classes ? `${classes} ${CURRENT_COLUMN_CLASS}` : CURRENT_COLUMN_CLASS;
    }

    revealCurrentWeek() {
        const weekId = this.currentWeekId;
        const column =
            weekId && this.rootRef.el?.querySelector(`.${CURRENT_COLUMN_CLASS}`);
        if (!column) {
            this.revealedWeekId = null;
            return;
        }
        if (this.revealedWeekId === weekId) {
            return;
        }
        this.revealedWeekId = weekId;
        this.scrollColumnToLeft(column);
    }

    /**
     * Bring a column to the left of whatever is scrolling it.
     *
     * `scrollLeft` on the scrolling ancestor rather than `scrollIntoView`:
     * that one scrolls every scrollable ancestor in both axes to satisfy the
     * request, and this board is nested in a column that scrolls vertically
     * inside a view that scrolls both ways — asking it for a horizontal move
     * also jumped the page down to the first card. Setting one axis moves one
     * axis. The browser clamps the value, so the first and last weeks simply
     * come to rest at the ends of the board.
     */
    scrollColumnToLeft(column) {
        const scroller = horizontalScrollParent(column);
        if (!scroller) {
            return;
        }
        const offset =
            column.getBoundingClientRect().left - scroller.getBoundingClientRect().left;
        scroller.scrollLeft += offset - PEEK_PX;
    }
}

registry.category("views").add("ft_week_kanban", {
    ...projectTaskKanbanView,
    Renderer: WeekKanbanRenderer,
});
