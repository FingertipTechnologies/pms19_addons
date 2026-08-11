/** @odoo-module **/

import { Component, useRef, onMounted, onWillUnmount, onWillUpdateProps, onPatched } from "@odoo/owl";

// Width (px) reserved for the pinned Y axis in horizontal-scroll mode.
const AXIS_W = 54;

/**
 * Reusable Chart.js card. Chart.js is expected to be already loaded
 * (the parent dashboard loads it in onWillStart).
 *
 * Props:
 *  - title   : string
 *  - type    : "doughnut" | "pie" | "bar" | "line"
 *  - data    : { labels, datasets }  (Chart.js data object)
 *  - options : object (optional Chart.js options override)
 *  - note    : string (optional caption shown under the title)
 *  - onSegmentClick: function(index) (optional drill-down)
 *  - fullWidth: boolean (optional, styling hint)
 *  - scrollMinWidth: number (optional) — enables "fixed Y / scrollable X"
 *    mode: the plot area gets this min-width and scrolls horizontally while
 *    the Y axis is redrawn as a pinned overlay on the left.
 */
export class ChartCard extends Component {
    static template = "ft_project_dashboard.ChartCard";
    static props = {
        title: { type: String },
        type: { type: String },
        data: { type: Object },
        options: { type: Object, optional: true },
        note: { type: String, optional: true },
        onSegmentClick: { type: Function, optional: true },
        fullWidth: { type: Boolean, optional: true },
        scrollMinWidth: { type: Number, optional: true },
        slots: { type: Object, optional: true },
    };

    setup() {
        this.canvasRef = useRef("canvas");
        this.axisRef = useRef("axis");
        this.chart = null;
        this._needsRender = false;

        onMounted(() => this._renderChart());
        onWillUpdateProps((nextProps) => {
            // Only rebuild when something the chart actually draws has changed.
            // The dashboard re-renders on every keystroke in any search box, but
            // hands us the SAME data object when our own data is unaffected — so
            // a reference check avoids a needless teardown/redraw (the flicker).
            const changed =
                nextProps.data !== this.props.data ||
                nextProps.type !== this.props.type ||
                nextProps.scrollMinWidth !== this.props.scrollMinWidth;
            if (!changed) {
                return;
            }
            // Tear down the old chart; redraw after the DOM is patched.
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
                tooltip: { enabled: true },
            },
        };
        if (this.props.type === "bar" || this.props.type === "line") {
            options.scales = {
                x: { grid: { display: false } },
                y: { beginAtZero: true, grid: { color: "rgba(0,0,0,0.05)" } },
            };
        }
        if (this.props.onSegmentClick) {
            options.onClick = (evt, elements) => {
                if (elements && elements.length) {
                    this.props.onSegmentClick(elements[0].index);
                }
            };
        }
        return Object.assign(options, this.props.options || {});
    }

    _renderChart() {
        const canvas = this.canvasRef.el;
        if (!canvas || typeof Chart === "undefined") {
            return;
        }
        const options = this._baseOptions();
        const plugins = [];
        if (this.props.scrollMinWidth) {
            // The wide plot area scrolls, so the canvas legend would slide off —
            // an HTML legend in the header replaces it.
            options.plugins = options.plugins || {};
            options.plugins.legend = Object.assign({}, options.plugins.legend, { display: false });
            // Hide the native Y axis (labels + line) but keep its gridlines, and
            // force its width to 0 so the plot area aligns with the pinned axis
            // overlay. layout.padding.left keeps the first bars off the overlay.
            options.scales = options.scales || {};
            options.scales.y = Object.assign({}, options.scales.y, {
                ticks: { display: false },
                border: { display: false },
                afterFit: (scale) => { scale.width = 0; },
            });
            options.layout = Object.assign({}, options.layout, {
                padding: Object.assign({ left: AXIS_W }, (options.layout || {}).padding),
            });
            // Redraw the pinned axis every frame so it stays synced through
            // animation and resize.
            plugins.push({ id: "ftpdFixedAxis", afterDraw: () => this._drawFixedAxis() });
        }
        this.chart = new Chart(canvas.getContext("2d"), {
            type: this.props.type,
            data: this.props.data,
            options,
            plugins,
        });
    }

    // Draw a fixed Y axis on the overlay canvas, reading the live chart scale so
    // ticks line up exactly with the (scrolling) gridlines.
    _drawFixedAxis() {
        const axis = this.axisRef.el;
        if (!axis || !this.chart) {
            return;
        }
        const yScale = this.chart.scales.y;
        if (!yScale) {
            return;
        }
        const dpr = window.devicePixelRatio || 1;
        const wCss = axis.clientWidth || AXIS_W;
        const hCss = axis.clientHeight || this.chart.height;
        if (axis.width !== Math.round(wCss * dpr) || axis.height !== Math.round(hCss * dpr)) {
            axis.width = Math.round(wCss * dpr);
            axis.height = Math.round(hCss * dpr);
        }
        const ctx = axis.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, wCss, hCss);
        ctx.fillStyle = "#64748b";
        ctx.strokeStyle = "rgba(0,0,0,0.12)";
        ctx.lineWidth = 1;
        ctx.font = "11px sans-serif";
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        // Axis line down the right edge of the overlay.
        ctx.beginPath();
        ctx.moveTo(wCss - 0.5, yScale.top);
        ctx.lineTo(wCss - 0.5, yScale.bottom);
        ctx.stroke();
        (yScale.ticks || []).forEach((t) => {
            const y = yScale.getPixelForValue(t.value);
            const label = t.label != null ? String(t.label) : String(t.value);
            ctx.fillText(label, wCss - 8, y);
            ctx.beginPath();
            ctx.moveTo(wCss - 5, y);
            ctx.lineTo(wCss, y);
            ctx.stroke();
        });
    }
}
