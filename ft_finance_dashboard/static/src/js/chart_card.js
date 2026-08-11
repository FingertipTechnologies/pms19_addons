/** @odoo-module **/

import { Component, useRef, onMounted, onWillUnmount, onWillUpdateProps, onPatched } from "@odoo/owl";

/** Reusable Chart.js card for the Finance dashboard (Chart.js loaded by parent). */
export class ChartCard extends Component {
    static template = "ft_finance_dashboard.ChartCard";
    static props = {
        title: { type: String },
        type: { type: String },
        data: { type: Object },
        options: { type: Object, optional: true },
        note: { type: String, optional: true },
        fullWidth: { type: Boolean, optional: true },
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this._needsRender = false;

        onMounted(() => this._renderChart());
        onWillUpdateProps(() => {
            this._destroy();
            this._needsRender = true;
        });
        onPatched(() => {
            if (this._needsRender) {
                this._needsRender = false;
                this._renderChart();
            }
        });
        onWillUnmount(() => this._destroy());
    }

    _destroy() {
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
    }

    _baseOptions() {
        const isCircular = ["pie", "doughnut"].includes(this.props.type);
        const options = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: isCircular ? "right" : "top",
                    labels: { usePointStyle: true, boxWidth: 8, font: { size: 12 } },
                },
            },
        };
        if (this.props.type === "bar" || this.props.type === "line") {
            options.scales = {
                x: { grid: { display: false } },
                y: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
            };
        }
        return Object.assign(options, this.props.options || {});
    }

    _renderChart() {
        const canvas = this.canvasRef.el;
        if (!canvas || typeof Chart === "undefined") {
            return;
        }
        this.chart = new Chart(canvas.getContext("2d"), {
            type: this.props.type,
            data: this.props.data,
            options: this._baseOptions(),
        });
    }
}
