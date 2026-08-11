/** @odoo-module **/

import { Component } from "@odoo/owl";

// Fallback palette (mirrors the Python PALETTE) when the data carries no colors.
const PALETTE = [
    "#7C3AED", "#EC4899", "#06B6D4", "#3B82F6", "#10B981",
    "#F59E0B", "#EF4444", "#8B5CF6", "#14B8A6", "#F97316",
];

// Funnel band widths (% of the funnel area). Bands taper evenly from TOP at the
// mouth to TIP at the last stage, so the shape stays a clean cone no matter how
// the raw counts cluster (many stages tie or bunch at the low end otherwise).
const TOP_WIDTH = 100;
const TIP_WIDTH = 30;

/**
 * Dependency-free inverted-funnel chart. Chart.js has no funnel type, so each
 * stage is a horizontal trapezoid (clip-path) whose top edge matches the stage
 * width and whose bottom edge matches the *next* stage's width — so the bands
 * connect into a downward-narrowing cone, closed by a small tip triangle.
 *
 * Props:
 *  - title    : string
 *  - data     : { labels: string[], datasets: [{ data: number[], backgroundColor?: string[] }] }
 *  - fullWidth: boolean (optional)
 */
export class FunnelChart extends Component {
    static template = "ft_sales_dashboard.FunnelChart";
    static props = {
        title: { type: String },
        data: { type: Object },
        fullWidth: { type: Boolean, optional: true },
        onStageClick: { type: Function, optional: true },
    };

    onStageClick(stage) {
        if (this.props.onStageClick) {
            this.props.onStageClick(stage);
        }
    }

    // Total across every band, shown in the header. The bands are taken from
    // the same population as the Opportunities Generated card — live records by
    // stage plus one Lost band — so this is the figure a manager reconciles the
    // card against, and it has to be visible to be checked.
    get totalCount() {
        return this.props.data?.total_count || 0;
    }

    // Centered trapezoid clip-path from a top width to a bottom width (in %).
    _trapezoid(topW, botW) {
        const tl = (100 - topW) / 2, tr = (100 + topW) / 2;
        const bl = (100 - botW) / 2, br = (100 + botW) / 2;
        return `polygon(${tl}% 0, ${tr}% 0, ${br}% 100%, ${bl}% 100%)`;
    }

    // The funnel now carries Expected Revenue, not a count, so the raw number
    // would render as e.g. "16350000". Indian grouping, no decimals: lakh-scale
    // pipeline figures do not need paise, and the band is narrow.
    _money(v) {
        return "₹ " + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
    }

    get view() {
        const data = this.props.data || {};
        const labels = data.labels || [];
        const stageIds = data.stage_ids || [];
        const counts = data.counts || [];
        const ds = (data.datasets && data.datasets[0]) || {};
        const values = ds.data || [];
        const colors = ds.backgroundColor || [];

        const items = labels.map((label, i) => ({
            label,
            // Revenue is what the band measures; the opportunity count rides
            // along so a stage worth a lot on one deal is not read as volume.
            value: this._money(values[i]),
            count: counts[i] || 0,
            color: colors[i] || PALETTE[i % PALETTE.length],
            stageId: stageIds[i] !== undefined ? stageIds[i] : false,
        }));
        // Order comes from the server in CRM stage-sequence order
        // (Cold -> Discussion -> ... -> Won -> Lost); keep it as-is rather than
        // re-sorting by count, so the funnel follows the pipeline flow. The band
        // taper is rank-based (see widthAt), so the cone stays clean regardless.

        const n = items.length;
        // Even rank-based taper from TOP_WIDTH (mouth) to TIP_WIDTH (last stage).
        // widthAt(0) = TOP_WIDTH, widthAt(n) = TIP_WIDTH.
        const widthAt = (i) =>
            n <= 1 ? TOP_WIDTH : TOP_WIDTH - (TOP_WIDTH - TIP_WIDTH) * (i / n);

        const stages = items.map((s, i) => {
            const topW = widthAt(i);
            // Bottom edge meets the next stage's top width, so bands connect.
            const botW = widthAt(i + 1);
            return {
                ...s,
                num: String(i + 1).padStart(2, "0"),
                clip: this._trapezoid(topW, botW),
            };
        });

        // Closing tip: from the last band's bottom width down to a centre point.
        let tip = null;
        if (n) {
            const w = widthAt(n);
            tip = {
                color: stages[n - 1].color,
                clip: `polygon(${(100 - w) / 2}% 0, ${(100 + w) / 2}% 0, 50% 100%)`,
            };
        }
        return { stages, tip };
    }
}
