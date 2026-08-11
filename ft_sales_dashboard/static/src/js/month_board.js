/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

/**
 * Month board — six month cards side by side, each showing its total, a
 * proportional bar, and the largest opportunities behind that total.
 *
 * Replaces the bar charts these three views used to be. The bar alone showed
 * the shape but never which deals made it; a table alone showed the deals but
 * buried the shape. Here the bar heights compare months at a glance and the
 * list underneath names the deals, so one card answers both questions.
 *
 * Bars share one scale (props.data.max_amount) so month-to-month comparison is
 * honest — rescaling each card to itself would make every month look equal.
 */
export class MonthBoard extends Component {
    static template = "ft_sales_dashboard.MonthBoard";
    static props = {
        title: { type: String },
        data: { type: Object },
        note: { type: String, optional: true },
        emptyText: { type: String, optional: true },
        onMonthClick: { type: Function, optional: true },
        onLeadClick: { type: Function, optional: true },
    };

    setup() {
        // Collapsed by default: six months of deals at once is a wall of text.
        // The bars stay visible either way, so the trend never needs a click.
        this.state = useState({ expanded: false });
    }

    get months() {
        return this.props.data?.months || [];
    }

    get isEmpty() {
        return !this.months.some((m) => m.count > 0);
    }

    money(v) {
        const n = Number(v || 0);
        // Lakh/crore shorthand: full figures would not fit in a narrow card,
        // and the exact number is one click away on the record.
        if (n >= 10000000) {
            return "₹ " + (n / 10000000).toFixed(2) + " Cr";
        }
        if (n >= 100000) {
            return "₹ " + (n / 100000).toFixed(2) + " L";
        }
        return "₹ " + n.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    }

    /** Bar height as a percentage of the tallest month on the board. */
    barHeight(month) {
        const max = this.props.data?.max_amount || 0;
        if (!max || !month.amount) {
            return 2; // a visible sliver, so an empty month still reads as a bar
        }
        return Math.max(4, Math.round((month.amount / max) * 100));
    }

    get totalAmount() {
        return this.money(this.props.data?.total_amount);
    }

    get totalCount() {
        return this.props.data?.total_count || 0;
    }

    get color() {
        return this.props.data?.color || "#4F46E5";
    }

    toggle() {
        this.state.expanded = !this.state.expanded;
    }

    onMonthClick(month) {
        if (this.props.onMonthClick && month.count) {
            this.props.onMonthClick(month);
        }
    }

    onLeadClick(lead, ev) {
        // The row sits inside a clickable month, so stop the click bubbling up
        // and opening the month list instead of the record.
        ev.stopPropagation();
        if (this.props.onLeadClick) {
            this.props.onLeadClick(lead);
        }
    }
}
