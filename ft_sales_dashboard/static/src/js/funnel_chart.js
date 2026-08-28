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

// Stage colours.
//
// Depth down the funnel is already carried by POSITION — the bands are stacked
// in stage order and every one prints its own name, count and amount inside
// itself — so hue is free to carry stage IDENTITY instead. That is what the
// previous single-hue light-to-navy ramp spent it on, and it left the middle of
// the pipeline as five shades of the same blue.
//
// TWO OF THE EIGHT HUES ARE NOT HERE. Won owns green and Lost owns red, so a
// green or red band anywhere else would be read as an outcome. Green is gone
// outright: palette green (#008300) against status green (#0ca30c) measures
// ΔE 9.7 to a normal-vision reader — below the 15 floor, i.e. the same colour.
// Palette red is kept because seven open stages need seven hues, but it is
// pinned to the FIRST slot, as far up the funnel as it goes: it sits ΔE 4.7
// from the Lost red, and the only defence available is distance. That pair is
// the accepted cost of a distinct hue per stage; it is why the run cannot be
// extended and why red must never be moved down.
//
// Hues are assigned in this FIXED ORDER and never cycled: stage 1 is always
// red, stage 2 always aqua, whatever the pipeline is called in this database.
// Colour therefore follows the stage, not its rank, so filtering the dashboard
// down to fewer stages never repaints the survivors.
//
// The order is not cosmetic — it is the colour-blindness safety mechanism. It
// came out of enumerating all 5040 orderings and keeping only the 52 where
// EVERY pipeline length (3..7 stages) clears the adjacent-pair gates on a white
// card WITH THE WON BAND APPENDED, since Won is what the last open stage
// actually sits against. That last condition is what forces aqua to the top:
// aqua is ΔE 10.0 from the Won green, so it may not end the run. This is the
// survivor with the widest normal-vision margin: worst adjacent ΔE 27.6
// (floor 15), worst adjacent colour-blind ΔE 6.9 — inside the 6–8 band, which
// is legal only alongside a second channel, and the second channel is the
// label printed in every band plus the white stroke between them.
//
// Reordering these by taste silently breaks all of that. Re-run the enumeration
// if they ever move.
const STAGE_HUES = [
    "#e34948", // red    — pinned first, furthest from the Lost band
    "#1baf7a", // aqua   — pinned high, too close to the Won green to end the run
    "#eb6834", // orange
    "#2a78d6", // blue
    "#eda100", // yellow
    "#4a3aa7", // violet
    "#e87ba4", // magenta
];

// Past the seventh open stage there is no honest colour left to give: the two
// reserved hues are spoken for, and inventing more by cycling would put two
// stages in the SAME colour, which is worse than none. Those bands take one
// neutral instead — visibly "unslotted", and still fully labelled.
const OVERFLOW_COLOR = "#64748b";

// Won and Lost are outcomes, not deeper stages of the pipeline, so they take
// reserved status colours and never a categorical slot. This is the one thing
// in the chart that can be read without reading a word of it.
//
// The two are ΔE 4.1 apart under deutan simulation, and no green/red pair does
// better — that is what red/green blindness means. The mitigation is the one
// status colours always carry: both bands are labelled, so the colour is
// confirmation and never the only evidence.
const WON_COLOR = "#0ca30c";
const LOST_COLOR = "#d03b3b";

// The mouth is not a stage — it is the sum of them — so it stays neutral rather
// than borrowing the first stage's hue and implying it is one.
//
// Neutral is not the same as invisible, which is what the first attempt at this
// was: #e2e8f0 sat at 1.2:1 against the white card, so the disc had no edge and
// the total appeared to float above the funnel. This is the lightest neutral
// that still clears 3:1 against the card — dark enough to be a solid object,
// light enough that it does not compete with the saturated bands below it.
const LID_COLOR = "#8494ab";
// How much the top FACE of the disc lifts off its body. This is a shallow
// highlight, not a wash: at the +0.5 it started with, the face climbed back to
// within 1.1:1 of the card and undid the colour above.
const LID_FACE_LIFT = 0.22;

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

// Near-black rather than the dashboard's slate ink. The bands are saturated
// now, so the dark-text side of the palette has less headroom than it did
// against the old pale ramp: this is what keeps the money figure over 3:1 on
// aqua and yellow.
const DARK_TEXT = "#0b1220";
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
 * This matters more with hues than it did with the old single-hue ramp: the
 * palette spans yellow at 2.2:1 against white and violet at 8.5:1, so no one
 * text colour works across it. A brightness threshold does not work either —
 * the mid-lightness hues sit close enough to the crossover that whichever side
 * of it they land on, the guess can be the worse of the two options. Comparing
 * the actual contrast ratios picks the better one on every band by
 * construction, which is also what lets the palette carry hues that are too
 * light to pass 3:1 on their own.
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
 *                 kinds: ('open'|'won'|'lost')[], total_count: number,
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
        // Absent on a payload from an older server, in which case every band
        // is treated as an open stage and only Lost keeps its own colour — the
        // funnel still draws, it just stops calling out the Won band.
        const kinds = data.kinds || [];
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
            fill: shade(LID_COLOR, LID_FACE_LIFT),
            body: this._band(MAX_R, MAX_R, lidY, totalBottom),
            bodyFill: LID_COLOR,
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
        // Counts only the OPEN stages, so the hue a stage gets does not shift
        // when a Won or Lost band appears above it — those two are painted from
        // the reserved status colours and take no slot.
        let slot = 0;
        for (let i = 0; i < n; i++) {
            const yt = y;
            const rt = radiusAt(i);
            const rb = i === n - 1 ? tailR : rt * BAND_TAPER;
            const h = SEG_H + overhang;
            const kind = kinds[i] || (stageIds[i] === "lost" ? "lost" : "open");
            let base;
            if (kind === "lost") {
                base = LOST_COLOR;
            } else if (kind === "won") {
                base = WON_COLOR;
            } else {
                base = STAGE_HUES[slot] || OVERFLOW_COLOR;
                slot++;
            }
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
                // A shallow light edge. The old ramp could afford +0.20 because
                // its bands were pale and carried dark text either way; on a
                // saturated hue that edge is where white text goes thin, so the
                // highlight is cut to the least that still reads as volume.
                light: shade(base, 0.1),
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
