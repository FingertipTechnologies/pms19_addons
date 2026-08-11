/** @odoo-module **/

import { Component, useState, onWillUpdateProps } from "@odoo/owl";

// Row-count choices for the "Rows per page" selector.
const PAGE_SIZES = [10, 25, 50, 100];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * Reusable, dependency-free data table with:
 *  - click-to-sort on every column (asc/desc toggle),
 *  - pagination (Prev / Next / numbered pages),
 *  - a rows-per-page selector (10 / 25 / 50 / 100),
 *  - horizontal + vertical scrolling for wide/long tables,
 *  - optional row grouping (repeated leading values are blanked, e.g. a
 *    resource that spans several project rows shows its name once).
 *
 * The parent owns searching and passes already-filtered `rows`.
 *
 * Props:
 *  - title      : string
 *  - columns    : [{ key, label, numeric?, date?, group?, cls? }]
 *  - rows       : array of plain objects keyed by column.key
 *  - groupKey   : string (optional) — key whose consecutive repeats form a group
 *  - groupLabel : string (optional) — noun for the group count, e.g. "resources"
 *  - emptyText  : string (optional)
 *  - defaultSort: { key, dir } (optional) — initial sort
 *  - Named slot "tools" renders in the header (search inputs live there).
 */
export class DataTable extends Component {
    static template = "ft_project_dashboard.DataTable";
    static props = {
        title: { type: String },
        columns: { type: Array },
        rows: { type: Array },
        groupKey: { type: String, optional: true },
        groupLabel: { type: String, optional: true },
        emptyText: { type: String, optional: true },
        defaultSort: { type: Object, optional: true },
        slots: { type: Object, optional: true },
    };

    setup() {
        this.pageSizes = PAGE_SIZES;
        const ds = this.props.defaultSort || {};
        this.state = useState({
            sortKey: ds.key || (this.props.columns[0] && this.props.columns[0].key),
            sortDir: ds.dir || "asc",
            page: 0,
            pageSize: PAGE_SIZES[0],
        });
        // Reset to the first page whenever the (filtered) row set changes size,
        // so a search that shrinks the list doesn't strand the user on a page
        // that no longer exists.
        onWillUpdateProps((next) => {
            if (next.rows.length !== this.props.rows.length) {
                this.state.page = 0;
            }
        });
    }

    // ---- sorting -----------------------------------------------------
    onSort(key) {
        if (this.state.sortKey === key) {
            this.state.sortDir = this.state.sortDir === "asc" ? "desc" : "asc";
        } else {
            this.state.sortKey = key;
            this.state.sortDir = "asc";
        }
        this.state.page = 0;
    }

    _isEmpty(v) {
        return v === null || v === undefined || v === "";
    }

    get sortedRows() {
        const key = this.state.sortKey;
        const col = this.props.columns.find((c) => c.key === key) || {};
        const dir = this.state.sortDir === "asc" ? 1 : -1;
        const rows = this.props.rows.slice();
        rows.sort((a, b) => {
            const va = a[key];
            const vb = b[key];
            // Empty values always sort last, regardless of direction.
            const ea = this._isEmpty(va);
            const eb = this._isEmpty(vb);
            if (ea && eb) return 0;
            if (ea) return 1;
            if (eb) return -1;
            let cmp;
            if (col.numeric) {
                cmp = va - vb;
            } else {
                // Date columns carry ISO strings, which compare chronologically
                // as plain strings — so text comparison is correct for them too.
                cmp = String(va).localeCompare(String(vb));
            }
            return cmp * dir;
        });
        return rows;
    }

    // ---- pagination --------------------------------------------------
    get pageCount() {
        return Math.max(1, Math.ceil(this.sortedRows.length / this.state.pageSize));
    }
    get currentPage() {
        return Math.min(Math.max(this.state.page, 0), this.pageCount - 1);
    }
    get pagedRows() {
        const start = this.currentPage * this.state.pageSize;
        const rows = this.sortedRows
            .slice(start, start + this.state.pageSize)
            .map((r) => ({ ...r }));
        // Grouping flags are computed per page, so each page is self-contained
        // (a group split across pages simply re-shows its label at the top).
        const gk = this.props.groupKey;
        let prev = null;
        rows.forEach((r) => {
            r.__first = !gk || r[gk] !== prev;
            if (gk) prev = r[gk];
        });
        rows.forEach((r, i) => {
            r.__mid = !!gk && i < rows.length - 1 && rows[i + 1][gk] === r[gk];
        });
        return rows;
    }
    get pageNumbers() {
        const total = this.pageCount;
        const cur = this.currentPage;
        const win = 5;
        let start = Math.max(0, cur - 2);
        let end = Math.min(total, start + win);
        start = Math.max(0, end - win);
        const arr = [];
        for (let i = start; i < end; i++) arr.push(i);
        return arr;
    }
    get rangeStart() {
        return this.sortedRows.length ? this.currentPage * this.state.pageSize + 1 : 0;
    }
    get rangeEnd() {
        return Math.min(this.sortedRows.length, (this.currentPage + 1) * this.state.pageSize);
    }
    get groupCount() {
        if (!this.props.groupKey) return 0;
        return new Set(this.props.rows.map((r) => r[this.props.groupKey])).size;
    }

    goto(p) {
        this.state.page = p;
    }
    prev() {
        if (this.currentPage > 0) this.state.page = this.currentPage - 1;
    }
    next() {
        if (this.currentPage < this.pageCount - 1) this.state.page = this.currentPage + 1;
    }
    onPageSize(ev) {
        this.state.pageSize = parseInt(ev.target.value, 10) || PAGE_SIZES[0];
        this.state.page = 0;
    }

    // ---- cell rendering ---------------------------------------------
    headClass(col) {
        let c = "ftpd_sortable";
        if (col.numeric) c += " ftpd_num";
        if (this.state.sortKey === col.key) c += " ftpd_sort_active";
        // Marks the abbreviated headers (DE, OTD, RWR, DWD) so they carry a
        // help cursor and a dotted underline — otherwise there is nothing on
        // screen to suggest the tooltip is there to be found.
        if (col.help) c += " ftpd_th_help";
        return c;
    }
    cellClass(col) {
        let c = col.numeric ? "ftpd_num" : "";
        if (col.cls) c += (c ? " " : "") + col.cls;
        return c;
    }
    sortIcon(col) {
        if (this.state.sortKey !== col.key) return "";
        return this.state.sortDir === "asc" ? "fa-caret-up" : "fa-caret-down";
    }
    _fmtDate(iso) {
        // 'YYYY-MM-DD' -> 'DD Mon YYYY' without touching the timezone.
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
        if (!m) return iso;
        return `${m[3]} ${MONTHS[parseInt(m[2], 10) - 1]} ${m[1]}`;
    }
    cellValue(row, col) {
        if (col.group && !row.__first) return "";
        const v = row[col.key];
        if (col.date) return this._isEmpty(v) ? "" : this._fmtDate(v);
        if (this._isEmpty(v)) return col.numeric ? "—" : "";
        return v;
    }
}
