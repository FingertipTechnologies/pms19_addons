/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { barLayout, changeInfo, shareOfTop } from "@adoption_intelligence/js/adoption_chart_math";

export { changeInfo, shareOfTop };

export const BAND_CLASS = {
    power_user: "ad-band-power",
    healthy: "ad-band-healthy",
    needs_improvement: "ad-band-needs",
    at_risk: "ad-band-risk",
    inactive: "ad-band-inactive",
};

export function errorMessage(error) {
    return (
        (error && error.data && error.data.message) ||
        (error && error.message) ||
        String(error || "Unknown error")
    );
}

export function fmt(value) {
    const n = Number(value || 0);
    return Number.isInteger(n) ? n.toLocaleString() : n.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

export function fmtMinutes(minutes) {
    const m = Math.round(Number(minutes || 0));
    if (m < 60) {
        return `${m}m`;
    }
    return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function toQuery(params) {
    return Object.entries(params)
        .filter(([, v]) => v !== null && v !== undefined && v !== "")
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join("&");
}

/**
 * Loads data through an async fetcher with loading / error state and
 * last-request-wins semantics (a slow response can never overwrite a newer one).
 */
export function useLoader(fetcher) {
    const state = useState({ loading: true, error: null, data: null });
    let token = 0;
    const load = async (...args) => {
        const mine = ++token;
        state.loading = true;
        state.error = null;
        try {
            const data = await fetcher(...args);
            if (mine === token) {
                state.data = data;
            }
        } catch (error) {
            if (mine === token) {
                state.error = errorMessage(error);
                state.data = null;
            }
        } finally {
            if (mine === token) {
                state.loading = false;
            }
        }
    };
    return { state, load };
}

// ------------------------------------------------------------------ charts (plain SVG/CSS, no library)
export class TrendChart extends Component {
    static template = "adoption_intelligence.TrendChart";
    static props = { points: Array, a: String, b: { type: String, optional: true }, aLabel: String, bLabel: { type: String, optional: true } };
    W = 640;
    H = 170;
    PAD = 22;

    scale(key) {
        const values = this.props.points.map((p) => Number(p[key] || 0));
        const max = Math.max(1, ...values);
        const n = Math.max(1, values.length - 1);
        return values.map((v, i) => [
            this.PAD + (i * (this.W - 2 * this.PAD)) / n,
            this.H - this.PAD - (v / max) * (this.H - 2 * this.PAD),
        ]);
    }
    line(key) {
        return this.scale(key).map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    }
    get aLine() {
        return this.line(this.props.a);
    }
    get bLine() {
        return this.props.b ? this.line(this.props.b) : "";
    }
    get aArea() {
        const pts = this.scale(this.props.a);
        if (!pts.length) {
            return "";
        }
        const base = this.H - this.PAD;
        return `${pts[0][0]},${base} ${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} ${pts[pts.length - 1][0]},${base}`;
    }
    get first() {
        return this.props.points.length ? this.props.points[0].date : "";
    }
    get last() {
        return this.props.points.length ? this.props.points[this.props.points.length - 1].date : "";
    }
    get hasData() {
        return this.props.points.some((p) => p[this.props.a] || (this.props.b && p[this.props.b]));
    }
    get dots() {
        return this.scale(this.props.a).map(([x, y], i) => ({ x, y, p: this.props.points[i] }));
    }
}

export class BarList extends Component {
    static template = "adoption_intelligence.BarList";
    static props = { items: Array, color: { type: String, optional: true }, suffix: { type: String, optional: true } };
    get rows() {
        const max = Math.max(1, ...this.props.items.map((i) => Number(i.value || 0)));
        return this.props.items.map((i) => ({ ...i, pct: Math.round((100 * Number(i.value || 0)) / max) }));
    }
    fmt(v) {
        return fmt(v);
    }
}

export class ScoreRing extends Component {
    static template = "adoption_intelligence.ScoreRing";
    static props = { value: [Number, Boolean], label: { type: String, optional: true }, size: { type: Number, optional: true } };
    get pct() {
        return this.props.value === false || this.props.value === null ? 0 : Math.max(0, Math.min(100, this.props.value));
    }
    get style() {
        const s = this.props.size || 132;
        return `--pct:${this.pct}; width:${s}px; height:${s}px;`;
    }
    get text() {
        return this.props.value === false || this.props.value === null ? "–" : Math.round(this.props.value);
    }
}

/** Vertical bar chart with gridlines, y-axis ticks and a value above every bar. */
export class BarChart extends Component {
    static template = "adoption_intelligence.BarChart";
    static props = { items: Array, emptyText: { type: String, optional: true } };
    W = 1000;
    H = 320;

    get layout() {
        return barLayout(this.props.items, { width: this.W, height: this.H });
    }
    get hasData() {
        return this.props.items.some((i) => Number(i.value || 0) > 0);
    }
    get gridlines() {
        const { scale, plot } = this.layout;
        const plotH = plot.bottom - plot.top;
        return scale.ticks.map((t) => ({
            value: t,
            y: plot.bottom - (scale.max ? (t / scale.max) * plotH : 0),
        }));
    }
    get compact() {
        return this.props.items.length > 24;
    }
}
