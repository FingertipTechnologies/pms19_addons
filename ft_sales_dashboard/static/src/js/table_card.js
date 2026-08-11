/** @odoo-module **/

import { Component } from "@odoo/owl";

/**
 * Reusable table card for the Sales dashboard.
 *
 * Used for the executive-wise reports, which are lists rather than charts:
 * a bar chart of eight salespeople hides the exact figures a manager is
 * actually reading off the screen.
 *
 * `columns` describes each column once:
 *   { key, label, type: "text" | "number" | "money" | "percent", align }
 * so a new report is a props change rather than a new component.
 */
export class TableCard extends Component {
    static template = "ft_sales_dashboard.TableCard";
    static props = {
        title: { type: String },
        columns: { type: Array },
        rows: { type: Array },
        note: { type: String, optional: true },
        fullWidth: { type: Boolean, optional: true },
        emptyText: { type: String, optional: true },
        // Optional totals row, rendered in a sticky <tfoot> using the same
        // column definitions as the body — so a column can never be formatted
        // one way in the rows and another way in its own total.
        total: { type: [Object, { value: null }], optional: true },
        onRowClick: { type: Function, optional: true },
    };

    format(row, col) {
        const v = row[col.key];
        if (v === null || v === undefined) {
            return "—";
        }
        switch (col.type) {
            case "money":
                // Grouping only: the raw figures are already rounded server
                // side, and decimals on lakh-scale pipeline numbers are noise.
                return "₹ " + Number(v).toLocaleString("en-IN", {
                    maximumFractionDigits: 0,
                });
            case "percent":
                return Number(v).toFixed(1) + " %";
            case "number":
                return Number(v).toLocaleString();
            default:
                return v;
        }
    }

    cellClass(col) {
        return col.align === "right" || ["number", "money", "percent"].includes(col.type)
            ? "btsd_td--num"
            : "";
    }

    get clickable() {
        return !!this.props.onRowClick;
    }

    onRowClick(row) {
        if (this.props.onRowClick) {
            this.props.onRowClick(row);
        }
    }
}
