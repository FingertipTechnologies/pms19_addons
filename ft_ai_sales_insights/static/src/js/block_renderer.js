/** @odoo-module **/

import { Component, useRef, onMounted, onWillUnmount } from "@odoo/owl";
import { InsightKpi, InsightSection } from "./insight_sections";

// Shared palette for chart series (matches the dashboard family of colours).
const PALETTE = [
    "#4F46E5", "#06B6D4", "#10B981", "#F59E0B", "#EF4444",
    "#8B5CF6", "#EC4899", "#14B8A6", "#F97316", "#3B82F6",
];

/**
 * A single chart block. The numbers come pre-resolved from the server in
 * block._chart = { labels: [...], data: [...] }; this component only draws them.
 * Chart.js is expected to be loaded already (the parent dashboard loadJS-es it).
 */
export class AiChart extends Component {
    static template = "ft_ai_sales_insights.AiChart";
    static props = { block: { type: Object } };

    setup() {
        this.canvasRef = useRef("canvas");
        this._chart = null;
        onMounted(() => this._draw());
        onWillUnmount(() => this._destroy());
    }

    get chartType() {
        return {
            bar_chart: "bar",
            line_chart: "line",
            pie_chart: "pie",
        }[this.props.block.type] || "bar";
    }

    _draw() {
        const Chart = window.Chart;
        const el = this.canvasRef.el;
        const chart = this.props.block._chart;
        if (!Chart || !el || !chart) {
            return;
        }
        const type = this.chartType;
        const isCircular = type === "pie";
        this._chart = new Chart(el, {
            type,
            data: {
                labels: chart.labels,
                datasets: [{
                    label: this.props.block.title || "",
                    data: chart.data,
                    backgroundColor: isCircular
                        ? chart.data.map((_, i) => PALETTE[i % PALETTE.length])
                        : PALETTE[0],
                    borderColor: type === "line" ? PALETTE[0] : undefined,
                    fill: type === "line" ? false : undefined,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: isCircular } },
                scales: isCircular ? {} : { y: { beginAtZero: true } },
            },
        });
    }

    _destroy() {
        if (this._chart) {
            this._chart.destroy();
            this._chart = null;
        }
    }
}

/**
 * Dispatches one layout block to the right presentation. Unknown types render
 * nothing (the server already drops them, so this is just belt-and-braces).
 *
 * props.block shapes (filled by services/layout_resolver.py):
 *  - kpi_tiles : { title?, _items: [{label, value, key?}] }
 *  - table     : { title?, columns: [{key,label}], _rows: [ {..} ] }
 *  - *_chart   : { title?, _chart: {labels, data} }
 *  - section /
 *    callout   : { title, tone, body, items }
 */
export class BlockRenderer extends Component {
    static template = "ft_ai_sales_insights.BlockRenderer";
    static components = { InsightKpi, InsightSection, AiChart };
    static props = { block: { type: Object } };

    get isChart() {
        return ["bar_chart", "line_chart", "pie_chart"].includes(this.props.block.type);
    }

    // Present a cell value; objects/arrays would render as "[object Object]", so
    // guard against a column pointed at a non-scalar field.
    cell(row, key) {
        const v = row[key];
        return v == null || typeof v === "object" ? "" : v;
    }
}
