/** @odoo-module **/

import { onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

// The row the list opens on, and the class the stylesheet colours it with.
const CURRENT_ROW_CLASS = "o_ft_current_week_row";

/**
 * The Weeks list, opened on the week today falls in.
 *
 * Weeks run oldest first (qa_testapp.sprint._order), which is the order that
 * makes the list read as a calendar: scrolling up is the weeks already worked,
 * scrolling down the weeks still to plan. It also means the list opened on the
 * OLDEST week on file — a screenful of weeks that are over, with the one being
 * worked somewhere below the fold and no way to tell it from its neighbours
 * once it was reached.
 *
 * Both halves of that are fixed here rather than in the arch. A list
 * decoration is evaluated against the record's own values and has no notion of
 * today (which is why `is_current_week` is computed on the server), and
 * nothing in a view can scroll anything.
 */
export class WeekListRenderer extends ListRenderer {
    setup() {
        super.setup();
        // The week already scrolled to. Held so the list is brought back to
        // today ONCE: sorting, filtering, editing a cell or simply hovering a
        // row all patch this component, and dragging the reader back to the
        // current week on each of those would make the list unusable. It is
        // cleared when the row leaves the page, so paging back to the week
        // reveals it again.
        this.revealedWeekId = null;

        // The rows do not exist when setup runs, so the scroll happens on the
        // patch that draws them — and on mount, which is where it fires when
        // the list arrives with its records already loaded.
        onMounted(() => this.revealCurrentWeek());
        onPatched(() => this.revealCurrentWeek());
    }

    /**
     * Colour the row for the week today falls in.
     *
     * `is_current_week` has to be in the arch for it to be in `record.data` —
     * it is there as a column_invisible field, so it is read but never drawn.
     */
    getRowClass(record) {
        const classNames = super.getRowClass(record);
        if (!record.data.is_current_week) {
            return classNames;
        }
        return classNames ? `${classNames} ${CURRENT_ROW_CLASS}` : CURRENT_ROW_CLASS;
    }

    /**
     * Scroll the current week into the middle of the list.
     *
     * `block: "center"` rather than "nearest", so the weeks either side of it
     * are a scroll away in both directions: the ones above are behind us, the
     * ones below are still to come.
     */
    revealCurrentWeek() {
        const row = this.tableRef.el?.querySelector(`tr.${CURRENT_ROW_CLASS}`);
        if (!row) {
            // Not on this page — a filter, a search or the pager has taken it
            // off. Forgotten, so that coming back to it scrolls again.
            this.revealedWeekId = null;
            return;
        }
        // `data-id` is the record's client-side id, which is stable for as
        // long as the row is on screen and is all this needs: the question is
        // only whether THIS row has been scrolled to already.
        const rowId = row.dataset.id;
        if (rowId === this.revealedWeekId) {
            return;
        }
        this.revealedWeekId = rowId;
        row.scrollIntoView({ block: "center", inline: "nearest" });
    }
}

registry.category("views").add("ft_week_list", {
    ...listView,
    Renderer: WeekListRenderer,
});
