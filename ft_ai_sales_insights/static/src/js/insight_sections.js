/** @odoo-module **/

import { Component } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

/**
 * A single KPI chip. props.kpi = { label, value, trend, status, action? }.
 *
 * `action` is attached server-side (see services/drilldown.py) only for metrics
 * with a real domain behind them, so a tile is clickable exactly when it can
 * open the records it counts.
 */
export class InsightKpi extends Component {
    static template = "ft_ai_sales_insights.InsightKpi";
    static props = { kpi: { type: Object } };

    setup() {
        this.action = useService("action");
    }

    get trendIcon() {
        return {
            up: "fa-arrow-up",
            down: "fa-arrow-down",
            flat: "fa-minus",
        }[this.props.kpi.trend] || "fa-minus";
    }
    get statusClass() {
        const base = `aisi_status--${this.props.kpi.status || "good"}`;
        return this.clickable ? `${base} aisi_kpi--clickable` : base;
    }
    get clickable() {
        return Boolean(this.props.kpi.action?.res_model);
    }
    openRecords() {
        const a = this.props.kpi.action;
        if (!a?.res_model) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: a.name || this.props.kpi.label || "Records",
            res_model: a.res_model,
            views: [[false, "list"], [false, "form"]],
            domain: a.domain || [],
            context: a.context || {},
            target: "current",
        });
    }
}

/**
 * A tonal insight section. props.section = { title, icon, tone, body, items }.
 */
export class InsightSection extends Component {
    static template = "ft_ai_sales_insights.InsightSection";
    static props = { section: { type: Object } };

    get toneClass() {
        return `aisi_section--${this.props.section.tone || "info"}`;
    }
    get items() {
        return this.props.section.items || [];
    }
}
