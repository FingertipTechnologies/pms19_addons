/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { errorMessage, fmt, toQuery, useLoader } from "@adoption_intelligence/js/adoption_common";

const PAGE_SIZE = 50;

/** Activity log: every successful create / update / delete, with old and new values. */
export class AdoptionActivityLogView extends Component {
    static template = "adoption_intelligence.ActivityLogView";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.fmt = fmt;
        this.ui = useState({ operation: "", source: "", origin: "", search: "", offset: 0, open: null, changes: {} });
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_activity_log", [], this.params(p))
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            if (["from", "to", "userId", "model", "rev"].some((k) => next[k] !== this.props[k])) {
                this.ui.offset = 0;
                this.ui.open = null;
                return this.load(next);
            }
        });
    }
    params(p = this.props) {
        return {
            date_from: p.from, date_to: p.to, user_id: p.userId ? Number(p.userId) : false,
            model_name: p.model || false, operation: this.ui.operation || false, source: this.ui.source || false,
            origin: this.ui.origin || false, search: this.ui.search || false,
            limit: PAGE_SIZE, offset: this.ui.offset,
        };
    }
    reload() {
        this.ui.open = null;
        return this.load(this.props);
    }
    onFilter(field, ev) {
        this.ui[field] = ev.target.value;
        this.ui.offset = 0;
        return this.reload();
    }
    get hasPrev() {
        return this.ui.offset > 0;
    }
    get hasNext() {
        const d = this.loader.data;
        return !!d && d.offset + d.rows.length < d.total;
    }
    get rangeText() {
        const d = this.loader.data;
        if (!d || !d.total) {
            return "0";
        }
        return `${d.offset + 1}–${d.offset + d.rows.length} of ${fmt(d.total)}`;
    }
    next() {
        this.ui.offset += PAGE_SIZE;
        return this.reload();
    }
    prev() {
        this.ui.offset = Math.max(0, this.ui.offset - PAGE_SIZE);
        return this.reload();
    }
    async toggle(row) {
        if (this.ui.open === row.id) {
            this.ui.open = null;
            return;
        }
        this.ui.open = row.id;
        if (row.changes && !this.ui.changes[row.id]) {
            this.ui.changes[row.id] = { loading: true, rows: [], error: null };
            try {
                const rows = await this.orm.call("adoption.dashboard", "get_activity_changes", [], { activity_id: row.id });
                this.ui.changes[row.id] = { loading: false, rows, error: null };
            } catch (error) {
                this.ui.changes[row.id] = { loading: false, rows: [], error: errorMessage(error) };
            }
        }
    }
    openRecord(row) {
        if (row.model_name && row.record_id && row.operation !== "delete") {
            this.action.doAction({ type: "ir.actions.act_window", res_model: row.model_name, res_id: row.record_id, views: [[false, "form"]] });
        }
    }
    exportXlsx() {
        const p = this.params();
        delete p.limit;
        delete p.offset;
        window.open(`/adoption/export/activity.xlsx?${toQuery(p)}`, "_self");
    }
}
