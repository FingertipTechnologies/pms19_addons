/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BarChart, changeInfo, fmt, fmtMinutes, toQuery, useLoader } from "@adoption_intelligence/js/adoption_common";

const PAGE_SIZE = 50;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TITLES = { day: "Day-over-Day", week: "Week-over-Week", month: "Month-over-Month" };

/** Reports: period comparison (chart + table), the full summary and the field-change report. */
export class AdoptionReports extends Component {
    static template = "adoption_intelligence.Reports";
    static components = { BarChart };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.fmt = fmt;
        this.fmtMinutes = fmtMinutes;
        this.ui = useState({ meaningfulOnly: false, includeAutomated: false, kind: "", offset: 0 });

        const base = (p) => ({
            date_from: p.from, date_to: p.to, user_id: p.userId ? Number(p.userId) : false, model_name: p.model || false,
        });
        const summary = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_summary_report", [], { ...base(p), granularity: p.granularity || "month" })
        );
        const changes = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_field_change_report", [], {
                ...base(p), meaningful_only: this.ui.meaningfulOnly, include_automated: this.ui.includeAutomated,
                kind: this.ui.kind || false, limit: PAGE_SIZE, offset: this.ui.offset,
            })
        );
        this.summary = summary.state;
        this.changes = changes.state;
        this.loadSummary = summary.load;
        this.loadChanges = changes.load;
        onWillStart(() => Promise.all([this.loadSummary(this.props), this.loadChanges(this.props)]));
        onWillUpdateProps((next) => {
            const keys = ["from", "to", "userId", "model", "rev", "granularity"];
            if (keys.some((k) => next[k] !== this.props[k])) {
                this.ui.offset = 0;
                return Promise.all([this.loadSummary(next), this.loadChanges(next)]);
            }
        });
    }

    // ------------------------------------------------------------ period comparison
    get granularity() {
        return this.summary.data ? this.summary.data.granularity : this.props.granularity || "month";
    }
    get chartTitle() {
        return `${TITLES[this.granularity]} Comparison — Field Edits`;
    }
    periodLabel(row) {
        const [y, m, d] = row.bucket.split("-").map(Number);
        if (this.granularity === "month") {
            return `${MONTHS[m - 1]} ${y}`;
        }
        if (this.granularity === "week") {
            return `${MONTHS[m - 1]} ${d}`;
        }
        return `${MONTHS[m - 1]} ${d}`;
    }
    /** Periods with no activity at all are left out, like the original report. */
    get activeRows() {
        return this.summary.data.rows.filter(
            (r) => r.events + r.field_edits + r.viewed + r.pages + r.reports + r.dashboards + r.active_minutes + r.logins > 0
        );
    }
    get chartItems() {
        return this.activeRows.map((r) => ({ label: this.periodLabel(r), value: r.field_edits }));
    }
    /** Newest first; each row compared with the previous period. */
    get comparisonRows() {
        const rows = this.activeRows;
        return rows
            .map((r, i) => ({
                key: r.bucket, period: this.periodLabel(r), field_edits: r.field_edits,
                touched: r.created + r.updated, active_users: r.active_users,
                change: changeInfo(r.field_edits, i ? rows[i - 1].field_edits : 0, i > 0),
            }))
            .reverse();
    }

    // ------------------------------------------------------------ field-change report
    toggle(flag) {
        this.ui[flag] = !this.ui[flag];
        this.ui.offset = 0;
        return this.loadChanges(this.props);
    }
    onKind(ev) {
        this.ui.kind = ev.target.value;
        this.ui.offset = 0;
        return this.loadChanges(this.props);
    }
    get hasPrev() {
        return this.ui.offset > 0;
    }
    get hasNext() {
        const d = this.changes.data;
        return !!d && d.offset + d.rows.length < d.total;
    }
    get rangeText() {
        const d = this.changes.data;
        return d && d.total ? `${d.offset + 1}–${d.offset + d.rows.length} of ${fmt(d.total)}` : "0";
    }
    next() {
        this.ui.offset += PAGE_SIZE;
        return this.loadChanges(this.props);
    }
    prev() {
        this.ui.offset = Math.max(0, this.ui.offset - PAGE_SIZE);
        return this.loadChanges(this.props);
    }

    // ------------------------------------------------------------ exports
    query(extra = {}) {
        const p = this.props;
        return toQuery({ date_from: p.from, date_to: p.to, user_id: p.userId, model_name: p.model, ...extra });
    }
    exportSummary() {
        window.open(`/adoption/export/summary.xlsx?${this.query({ granularity: this.granularity })}`, "_self");
    }
    exportChanges() {
        window.open(`/adoption/export/field_changes.xlsx?${this.query({
            meaningful_only: this.ui.meaningfulOnly ? 1 : "", include_automated: this.ui.includeAutomated ? 1 : "",
            kind: this.ui.kind,
        })}`, "_self");
    }
}
