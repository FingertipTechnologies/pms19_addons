/** @odoo-module **/

import { Component, useState, useRef, useExternalListener } from "@odoo/owl";

// Matches beyond this are not rendered. 285 projects is enough for a plain
// <select> to be unusable but also enough that painting every one of them on
// each keystroke is wasted work — nobody scrolls past fifty, they type instead.
// The count of what is hidden is shown, so a narrow search never looks complete
// when it is not.
const MAX_VISIBLE = 50;

/**
 * A type-to-search replacement for a long <select>.
 *
 * A native select only jumps to the first letter, so picking one project out of
 * 285 meant hammering "F" and hoping. This filters as you type, on a substring
 * rather than a prefix, so "leaves" finds "Fingertip Leaves".
 *
 * Props:
 *  - options     : [{id, name}]
 *  - value       : the selected id ("" for none)
 *  - allLabel    : label for the clear-the-filter entry, e.g. "All Projects"
 *  - placeholder : input placeholder
 *  - onSelect    : function(idOrEmptyString)
 *  - title       : optional tooltip for the control
 *  - label       : optional caption shown inside the box, e.g. "RESOURCE". Worth
 *                  setting wherever more than one picker sits side by side: once
 *                  a value is chosen the boxes look alike, and the caption is
 *                  what says which is which.
 */
export class SearchSelect extends Component {
    static template = "ft_project_dashboard.SearchSelect";
    static props = {
        options: { type: Array },
        value: { optional: true },
        allLabel: { type: String, optional: true },
        placeholder: { type: String, optional: true },
        onSelect: { type: Function },
        title: { type: String, optional: true },
        label: { type: String, optional: true },
    };

    setup() {
        this.state = useState({ open: false, query: "", active: 0 });
        this.root = useRef("root");
        this.input = useRef("input");
        // Pointerdown rather than click: a click on another control would
        // otherwise fire before this closed, and the list would swallow it.
        useExternalListener(window, "pointerdown", this.onOutside.bind(this));
    }

    // ----------------------------------------------------------------
    // Derived state
    // ----------------------------------------------------------------
    /** The label to show when the field is not being edited. */
    get selectedLabel() {
        const hit = this.props.options.find(
            (o) => String(o.id) === String(this.props.value)
        );
        return hit ? hit.name : "";
    }

    /** Options matching the current query, capped. */
    get matches() {
        const q = this.state.query.trim().toLowerCase();
        const all = this.props.options;
        const hits = q
            ? all.filter((o) => (o.name || "").toLowerCase().includes(q))
            : all;
        return hits.slice(0, MAX_VISIBLE);
    }

    get hiddenCount() {
        const q = this.state.query.trim().toLowerCase();
        const total = q
            ? this.props.options.filter((o) =>
                  (o.name || "").toLowerCase().includes(q)
              ).length
            : this.props.options.length;
        return Math.max(total - MAX_VISIBLE, 0);
    }

    /** The "All Projects" row is offered only when it is not filtered away. */
    get showAllRow() {
        const q = this.state.query.trim().toLowerCase();
        return !q || (this.props.allLabel || "").toLowerCase().includes(q);
    }

    /** Rows in render order, so keyboard and mouse agree on the indices. */
    get rows() {
        const rows = this.showAllRow
            ? [{ id: "", name: this.props.allLabel || "All" }]
            : [];
        return rows.concat(this.matches);
    }

    isActive(index) {
        return index === this.state.active;
    }

    isChosen(row) {
        return String(row.id) === String(this.props.value || "");
    }

    // ----------------------------------------------------------------
    // Interaction
    // ----------------------------------------------------------------
    open() {
        this.state.open = true;
        this.state.query = "";
        this.state.active = 0;
    }

    close() {
        this.state.open = false;
        this.state.query = "";
    }

    onFocus() {
        this.open();
    }

    onInput(ev) {
        this.state.query = ev.target.value;
        this.state.open = true;
        // The previous highlight belongs to the old list.
        this.state.active = 0;
    }

    onOutside(ev) {
        if (this.state.open && this.root.el && !this.root.el.contains(ev.target)) {
            this.close();
        }
    }

    pick(row) {
        this.close();
        if (this.input.el) {
            this.input.el.blur();
        }
        this.props.onSelect(row.id === "" ? "" : row.id);
    }

    onKeydown(ev) {
        const rows = this.rows;
        switch (ev.key) {
            case "ArrowDown":
                ev.preventDefault();
                if (!this.state.open) {
                    return this.open();
                }
                this.state.active = Math.min(this.state.active + 1, rows.length - 1);
                break;
            case "ArrowUp":
                ev.preventDefault();
                this.state.active = Math.max(this.state.active - 1, 0);
                break;
            case "Enter":
                // Only swallow Enter when there is something to commit.
                if (this.state.open && rows[this.state.active]) {
                    ev.preventDefault();
                    this.pick(rows[this.state.active]);
                }
                break;
            case "Escape":
                if (this.state.open) {
                    // Stop the dialog/action above from also reacting to it.
                    ev.stopPropagation();
                    this.close();
                    if (this.input.el) {
                        this.input.el.blur();
                    }
                }
                break;
        }
    }
}
