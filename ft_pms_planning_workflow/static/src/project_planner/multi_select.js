/** @odoo-module **/

import { Component, onWillUpdateProps, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { CheckboxItem } from "@web/core/dropdown/checkbox_item";
import { useDropdownState } from "@web/core/dropdown/dropdown_hooks";

/** Case- and accent-insensitive form of a label, for the search box. */
function normalize(text) {
    return String(text || "")
        .normalize("NFD")
        .replace(/[̀-ͯ]/g, "")
        .toLowerCase();
}

/**
 * Searchable filter dropdown used by both planners (Project / PM / Resource).
 * Options are {id, name, initials?}; selected ids that are no longer offered
 * (cascading options) are kept and still sent to the server.
 *
 * The parent owns the selected ids and gets the new list through `onChange`;
 * a reactive local copy (`state.selected`) is updated immediately on each
 * pick so the menu (rendered in a popover) ticks/unticks instantly, and is
 * re-synced from props whenever the parent re-renders. An empty selection means "no filter" (All).
 * `multiple: false` turns it into a single select: picking an option replaces
 * the selection and closes the menu.
 *
 * The search text only narrows what is listed; it never filters the data —
 * the parent always receives record ids. Arrow keys move through the matches
 * while the caret stays in the search box (virtual focus), Enter picks the
 * highlighted match (or the only / first one), Escape closes.
 */
export class PlannerMultiSelect extends Component {
    static template = "ft_pms_planning_workflow.PlannerMultiSelect";
    static components = { Dropdown, DropdownItem, CheckboxItem };
    static props = {
        label: String,
        options: { type: Array, optional: true },
        selected: Array,
        onChange: Function,
        multiple: { type: Boolean, optional: true },
        allLabel: { type: String, optional: true },
    };
    static defaultProps = { options: [], multiple: true };

    setup() {
        this.dropdown = useDropdownState();
        this.searchRef = useRef("search");
        this.menuRef = useRef("menu");
        this.state = useState({ query: "", selected: [...this.props.selected] });
        onWillUpdateProps((nextProps) => {
            this.state.selected = [...nextProps.selected];
        });
        this.navigationOptions = { virtualFocus: true };
    }

    get selectedSet() {
        return new Set(this.state.selected);
    }

    /**
     * Options matching the search text. Selected options are listed first so
     * the current choice stays visible (and removable) whatever is typed.
     */
    get visibleOptions() {
        const query = normalize(this.state.query).trim();
        const selected = this.selectedSet;
        const matches = this.props.options.filter(
            (option) =>
                !query ||
                normalize(option.name).includes(query) ||
                normalize(option.initials).includes(query)
        );
        if (query) {
            return matches;
        }
        return [
            ...matches.filter((option) => selected.has(option.id)),
            ...matches.filter((option) => !selected.has(option.id)),
        ];
    }

    get summary() {
        const selected = this.state.selected;
        if (!selected.length) {
            return this.props.allLabel || _t("All");
        }
        if (selected.length === 1) {
            const option = this.props.options.find((o) => o.id === selected[0]);
            if (option) {
                return option.name;
            }
        }
        return _t("%s selected", selected.length);
    }

    onOpened() {
        this.state.query = "";
        // The menu is rendered in a popover; focus once it is in the DOM.
        requestAnimationFrame(() => this.searchRef.el?.focus());
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            ev.stopPropagation();
            this.dropdown.close();
        } else if (ev.key === "Enter") {
            // The dropdown navigation handles Enter when a match is
            // highlighted; otherwise pick the first match.
            const highlighted = this.menuRef.el?.querySelector(".o-navigable.focus");
            if (!highlighted) {
                ev.preventDefault();
                const first = this.visibleOptions[0];
                if (first) {
                    this.pick(first.id);
                }
            }
        }
    }

    pick(id) {
        if (!this.props.multiple) {
            const next = this.state.selected[0] === id ? [] : [id];
            this.state.selected = next;
            this.props.onChange([...next]);
            this.dropdown.close();
            return;
        }
        const next = new Set(this.state.selected);
        if (next.has(id)) {
            next.delete(id);
        } else {
            next.add(id);
        }
        this.state.selected = [...next];
        this.props.onChange([...next]);
    }

    clear() {
        this.state.selected = [];
        this.props.onChange([]);
        if (!this.props.multiple) {
            this.dropdown.close();
        }
    }
}
