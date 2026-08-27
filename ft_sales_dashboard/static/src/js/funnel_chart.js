/** @odoo-module **/

import { Component } from "@odoo/owl";

// ---------------------------------------------------------------------------
// Geometry, in SVG user units.
//
// The whole chart is laid out once at this size and then scaled by the browser
// (width:100% against a max-width), so every constant below is a real
// proportion rather than a pixel guess that falls apart at another zoom level
// or container width.
const VIEW_W = 660;
const CX = 330; // centre line of the funnel — the middle of the viewBox
const MAX_R = 292; // half-width of the mouth — the Total disc
const STAGE_R = 272; // widest a stage band may draw, kept under the mouth
// Narrowest band. This floor is set by the TEXT, not by the shape: each band
// now carries its amount inside it, so the thinnest band still has to be wide
// enough to print a money figure. See the floor note in radiusAt().
const MIN_R = 92;
const PERSPECTIVE = 0.13; // ellipse ry as a fraction of rx — the 3D tilt
const TOTAL_H = 34; // body height of the Total disc
// Body height of a stage band. Two lines of text ride on the visible face
// (stage name over amount), so this is the line block plus breathing room.
const SEG_H = 44;
const LINE_GAP = 13.5; // baseline-to-baseline, stage name to amount
const PAD_B = 10;
// Each band tapers only slightly, from its own radius to this fraction of it,
// rather than running down to the NEXT band's radius.
//
// That difference decides whether the chart can be read at all. Tapering into
// the next band makes every edge a blend of two values, so a small stage
// followed by a large one draws as a funnel that pinches and then flares, and
// no single width belongs to any one stage. Holding each band at its own width
// means the widest band is unambiguously the biggest number — the step between
// two bands becomes the signal instead of a smear.
const BAND_TAPER = 0.93;
const TAIL_RATIO = 0.62; // how far the last band pulls in, so the funnel closes
const CHAR_W = 6.4; // approx advance width at the stage-name font size
const AMT_CHAR_W = 6.0; // ditto at the slightly smaller amount font size

// Depth ramp: light at the mouth, navy at the tip. A single hue carries "how
// far down the funnel" so that width is left free to carry value — two
// variables on one shape need two separate channels or neither can be read.
const RAMP_TOP = "#DCE9F7";
const RAMP_BOT = "#16365C";
// Lost keeps its own colour rather than taking a place on the ramp: it is not a
// deeper stage of the pipeline, it is the deals that left it.
const LOST_COLOR = "#B03A2E";

// Unique per instance, because SVG gradient ids are document-global and two
// funnels on one page would otherwise both paint with the first one's ramp.
let SEQ = 0;

function hex2rgb(hex) {
    const h = hex.replace("#", "");
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function rgb2hex(rgb) {
    return (
        "#" +
        rgb
            .map((v) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, "0"))
            .join("")
    );
}

function mix(a, b, t) {
    const ra = hex2rgb(a);
    const rb = hex2rgb(b);
    return rgb2hex(ra.map((v, i) => v + (rb[i] - v) * t));
}

/** Lighter for amt > 0, darker for amt < 0. Used for the volume gradient. */
function shade(hex, amt) {
    return mix(hex, amt > 0 ? "#ffffff" : "#000000", Math.abs(amt));
}

const DARK_TEXT = "#1E293B";
const LIGHT_TEXT = "#FFFFFF";

/** WCAG relative luminance. */
function luminance(hex) {
    const [r, g, b] = hex2rgb(hex).map((v) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
    const la = luminance(a);
    const lb = luminance(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/**
 * The more legible of ink or paper ON this band, decided by measuring both.
 *
 * The ramp runs from near-white to navy, so no single text colour works down
 * the whole funnel. A brightness threshold does not work either: the bands in
 * the middle of the ramp sit close enough to the crossover that whichever side
 * of it they land on, the guess can be the worse of the two options — mid-slate
 * takes white at 3.3:1 when dark would have given 4.3:1. Comparing the actual
 * contrast ratios picks the better one at every step by construction.
 */
function textOn(bg) {
    return contrast(bg, DARK_TEXT) >= contrast(bg, LIGHT_TEXT) ? DARK_TEXT : LIGHT_TEXT;
}

/**
 * Dependency-free 3D funnel. Chart.js has no funnel type, and the previous CSS
 * clip-path version could only cut straight edges — a cone drawn from flat
 * trapezoids, with no way to show the elliptical rim where one band meets the
 * next. This draws real frustums in SVG instead: each band is bounded above and
 * below by half-ellipses, so the stack reads as a solid object seen slightly
 * from above, and the rims stay visible where one band steps to the next.
 *
 * Band width is proportional to that band's own value, so the outline is the
 * data: the widest band is the biggest number, and a stage holding twice the
 * revenue of another is twice as wide. The shape is therefore not always a tidy
 * narrowing cone, and should not be — a stage that holds more than the one
 * before it is exactly what a sales manager needs to see.
 *
 * Props:
 *  - title    : string
 *  - data     : { labels: string[], counts: number[], stage_ids: (int|'lost')[],
 *                 total_count: number,
 *                 datasets: [{ data: number[] }] }
 *  - fullWidth: boolean (optional)
 *  - onStageClick: function (optional)
 */
export class FunnelChart extends Component {
    static template = "ft_sales_dashboard.FunnelChart";
    static props = {
        title: { type: String },
        data: { type: Object },
        fullWidth: { type: Boolean, optional: true },
        onStageClick: { type: Function, optional: true },
    };

    setup() {
        this.uid = ++SEQ;
    }

    onStageClick(stage) {
        if (this.props.onStageClick) {
            this.props.onStageClick(stage);
        }
    }

    // Total across every band, shown on the mouth of the funnel and in the
    // header. The bands come from the same population as the Opportunities
    // card, so this is the figure a manager reconciles that card against, and
    // it has to be visible to be checked.
    get totalCount() {
        return this.props.data?.total_count || 0;
    }

    // The funnel carries Expected Revenue, so the raw number would render as
    // e.g. "16350000". Indian grouping, no decimals: lakh-scale pipeline
    // figures do not need paise, and the column is narrow.
    _money(v) {
        return "₹ " + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
    }

    _ry(r) {
        return r * PERSPECTIVE;
    }

    /**
     * One band: flat top edge, straight sides, and a bottom edge that is the
     * FRONT half of an ellipse (it bulges downward, past ``yb``).
     *
     * The top is deliberately flat rather than a second arc. Curving both edges
     * only tiles when consecutive bands are the same width: as soon as a wide
     * band follows a narrow one, the narrow band's shallow bottom arc and the
     * wide band's deep top arc bound a lens-shaped area that belongs to
     * neither, and a white gap opens between them.
     *
     * With a flat top, each band simply overhangs the one below by its own arc
     * depth, and the bands are PAINTED BOTTOM-UP (see ``painted``) so that
     * overhang lands on top. Every visible horizontal boundary is then the
     * elliptical rim of the band above it — the 3D read is preserved, and no
     * combination of widths can produce a gap.
     */
    _band(rt, rb, yt, yb) {
        const n = (v) => Math.round(v * 100) / 100;
        return [
            `M ${n(CX - rt)} ${n(yt)}`,
            `L ${n(CX + rt)} ${n(yt)}`,
            `L ${n(CX + rb)} ${n(yb)}`,
            `A ${n(rb)} ${n(this._ry(rb))} 0 0 1 ${n(CX - rb)} ${n(yb)}`,
            "Z",
        ].join(" ");
    }

    /** Trim a label to what fits inside a band of half-width r. */
    _fit(text, r) {
        const max = Math.max(Math.floor((2 * r - 24) / CHAR_W), 4);
        return text.length > max ? text.slice(0, max - 1) + "…" : text;
    }

    /**
     * Does the share-of-pipeline suffix fit next to the amount on this band?
     *
     * The percentage is what gets dropped when a band is too narrow — never a
     * digit of the amount. A clipped stage name still reads as that stage, but
     * a clipped money figure reads as a DIFFERENT NUMBER, and this is a chart
     * managers reconcile against a CRM export. So the amount is never passed
     * through _fit(): it prints whole or the band gives up the percentage to
     * make room for it.
     *
     * In practice this almost never fires, because width is proportional to
     * amount: a narrow band holds a small number, which is a short string.
     * It exists for the band sitting on the MIN_R floor.
     */
    _pctFits(money, percent, r) {
        return `${money} ${percent}`.length <= Math.floor((2 * r - 20) / AMT_CHAR_W);
    }

    get view() {
        const data = this.props.data || {};
        const labels = data.labels || [];
        const stageIds = data.stage_ids || [];
        const counts = data.counts || [];
        const ds = (data.datasets && data.datasets[0]) || {};
        const raw = ds.data || [];
        const n = labels.length;
        if (!n) {
            return { segments: [], lid: null, height: 0, width: VIEW_W, cx: CX };
        }

        // Negative expected revenue is not meaningful as a width and would map
        // below the floor, so it is clamped at 0 and draws at MIN_R.
        const amounts = labels.map((_, i) => Math.max(Number(raw[i]) || 0, 0));
        const maxAmount = Math.max(...amounts);
        const totalAmount = amounts.reduce((a, b) => a + b, 0);

        // Half-width of band i, PROPORTIONAL TO ITS VALUE.
        //
        // MIN_R is the floor that keeps the shape usable. A stage worth 2% of
        // the leader would otherwise render as a sliver a few pixels across,
        // with its label and amount clipped away to nothing and nothing left
        // to click.
        // Values map onto MIN_R..STAGE_R rather than 0..STAGE_R; the ordering
        // and the relative differences survive, and only the very bottom of the
        // range is compressed.
        //
        // The even taper is the all-zero fallback only — an empty period, where
        // proportional widths would put every band on the floor and the funnel
        // would read as a stack of identical slivers.
        const radiusAt = (i) => {
            const j = Math.min(i, n - 1);
            if (maxAmount <= 0) {
                return n <= 1 ? STAGE_R : STAGE_R - (STAGE_R - MIN_R) * (j / n);
            }
            return MIN_R + (STAGE_R - MIN_R) * (amounts[j] / maxAmount);
        };
        // Bottom edge of the last band, pulled in so the funnel closes off
        // instead of ending on a flat disc.
        const tailR = Math.max(radiusAt(n - 1) * TAIL_RATIO, 30);

        // --- the mouth: one disc carrying the total -----------------------
        const lidRy = this._ry(MAX_R);
        const lidY = lidRy;
        const totalBottom = lidY + TOTAL_H;
        const lid = {
            cy: lidY,
            rx: MAX_R,
            ry: lidRy,
            // Painted last of all, so its full ellipse reads as the open top
            // surface of the disc rather than being clipped by the body.
            fill: shade(RAMP_TOP, 0.45),
            body: this._band(MAX_R, MAX_R, lidY, totalBottom),
            bodyFill: RAMP_TOP,
            // Centred on the elliptical top face, which is where the reference
            // design puts it — the disc reads as a lid you are looking down on.
            textY: lidY + 5,
            text: `Total = ${this._money(totalAmount)}  (${this.totalCount})`,
        };

        // --- the stage bands ----------------------------------------------
        //
        // Bands are NOT a fixed SEG_H apart. Each one is overhung by the arc of
        // the shape above it — deeply, since arc depth scales with width — so a
        // constant pitch leaves the top band a sliver while the ones below get
        // their full height. With a single stage under the wide Total disc, the
        // band all but disappeared. Each band therefore takes back exactly the
        // depth that the shape above covers, which makes every VISIBLE face
        // SEG_H tall regardless of how the widths fall.
        const segments = [];
        let y = totalBottom;
        let overhang = lidRy; // the Total disc covers the first band by this much
        for (let i = 0; i < n; i++) {
            const yt = y;
            const rt = radiusAt(i);
            const rb = i === n - 1 ? tailR : rt * BAND_TAPER;
            const h = SEG_H + overhang;
            const isLost = stageIds[i] === "lost";
            const base = isLost ? LOST_COLOR : mix(RAMP_TOP, RAMP_BOT, n <= 1 ? 0.55 : i / (n - 1));
            const share = totalAmount > 0 ? (amounts[i] / totalAmount) * 100 : 0;
            const label = `${labels[i]} (${counts[i] || 0})`;
            const money = this._money(amounts[i]);
            const pct = `(${share.toFixed(share >= 10 ? 0 : 1)}%)`;
            // Centre of the VISIBLE face — from the deepest point of the rim
            // above (yt + overhang) to the deepest point of this band's own
            // rim. Both text lines are centred on it as one block.
            const faceCenter = yt + overhang + (SEG_H + this._ry(rb)) / 2;
            // Baseline of the first of two lines. The block runs from roughly
            // one cap-height above this baseline to one descender below the
            // second, so backing off by (LINE_GAP - 6) / 2 puts the INK either
            // side of faceCenter rather than the baselines.
            const labelY = faceCenter - (LINE_GAP - 6) / 2;
            segments.push({
                path: this._band(rt, rb, yt, yt + h),
                gradId: `ftFunnel${this.uid}_${i}`,
                // The finished url(#id) reference, built here rather than
                // interpolated in the template. t-attf accepts BOTH {{ }} and
                // #{ } as interpolation syntax, so "url(#{{ s.gradId }})" is
                // read as a #{ } expression wrapping "{ s.gradId }" and compiles
                // to invalid JS. Nothing in the template can escape that; the
                // only safe fix is to keep the '#' out of the template.
                fillRef: `url(#ftFunnel${this.uid}_${i})`,
                light: shade(base, 0.2),
                base,
                dark: shade(base, -0.18),
                label: this._fit(label, rt),
                // One colour for both lines, chosen by measuring contrast
                // against THIS band. The amount sits on the ramp now, so a
                // fixed grey would vanish into the navy at the bottom of the
                // funnel; the hierarchy between the two lines is carried by
                // size and opacity in the stylesheet instead.
                textColor: textOn(base),
                labelY,
                amountY: labelY + LINE_GAP,
                amount: money,
                // Blank rather than clipped when the band cannot hold it —
                // see _pctFits.
                percent: this._pctFits(money, pct, rt) ? pct : "",
                // The band clips its label, so the untruncated text lives here.
                hint: `${labels[i]} — ${this._money(amounts[i])} · ${counts[i] || 0} opportunities · ${share.toFixed(1)}% of pipeline`,
                stageId: stageIds[i] !== undefined ? stageIds[i] : false,
                count: counts[i] || 0,
            });
            y += h;
            overhang = this._ry(rb);
        }

        return {
            lid,
            segments,
            // Paint order: bottom band first, so every band's arc overhangs the
            // one below it rather than being covered by it. Labels are drawn in
            // a separate pass afterwards, or a wide band would paint over the
            // text of the narrow band above it.
            painted: [...segments].reverse(),
            width: VIEW_W,
            // y already carries every band's real height; the last rim still
            // hangs below it.
            height: y + overhang + PAD_B,
            cx: CX,
        };
    }
}
