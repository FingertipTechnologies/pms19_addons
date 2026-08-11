/** @odoo-module **/

import { Component } from "@odoo/owl";

/** Reusable KPI card for the Sales dashboard. */
export class KpiCard extends Component {
    static template = "ft_sales_dashboard.KpiCard";
    static props = {
        title: { type: String },
        value: { optional: true },
        icon: { type: String, optional: true },
        color: { type: String, optional: true },
        prefix: { type: String, optional: true },
        suffix: { type: String, optional: true },
        tooltip: { type: String, optional: true },
        onClick: { type: Function, optional: true },
    };

    get displayValue() {
        const v = this.props.value;
        if (v === null || v === undefined) {
            return "N/A";
        }
        if (typeof v === "number") {
            return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
        }
        return v;
    }

    get clickable() {
        return !!this.props.onClick;
    }

    onCardClick() {
        if (this.props.onClick) {
            this.props.onClick();
        }
    }
}
