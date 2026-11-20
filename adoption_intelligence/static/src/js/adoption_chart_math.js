/** @odoo-module **/
/**
 * Pure helpers for the dashboard charts and comparison tables.
 * No Odoo / DOM imports, so they are unit tested in Node (tests/js/test_chart_math.mjs).
 */

const NICE = [1, 2, 2.5, 5, 10];

/** Axis for a bar chart: {max, step, ticks:[0, step, ..., max]} with "nice" round numbers. */
export function niceScale(maxValue, tickCount = 4) {
    const top = Number(maxValue);
    if (!isFinite(top) || top <= 0) {
        return { max: tickCount, step: 1, ticks: Array.from({ length: tickCount + 1 }, (_, i) => i) };
    }
    const raw = top / tickCount;
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const normalised = raw / magnitude;
    const step = (NICE.find((n) => n >= normalised - 1e-9) || 10) * magnitude;
    const ticks = [];
    for (let v = 0; v < top + step - 1e-9; v += step) {
        ticks.push(Math.round(v * 1e6) / 1e6);
    }
    return { max: ticks[ticks.length - 1], step, ticks };
}

/** Whole-number % change from `previous` to `current`; null when it is undefined (previous is 0). */
export function pctChange(current, previous) {
    const cur = Number(current || 0);
    const prev = Number(previous || 0);
    if (prev === 0) {
        return cur === 0 ? 0 : null;
    }
    return Math.round(((cur - prev) / Math.abs(prev)) * 100);
}

/**
 * What to show in a "change vs previous" cell.
 * @returns {{text:string, tone:'up'|'down'|'flat'|'none'}}
 */
export function changeInfo(current, previous, hasPrevious) {
    if (!hasPrevious) {
        return { text: "—", tone: "none" };
    }
    const change = pctChange(current, previous);
    if (change === null) {
        return { text: "new", tone: "up" };
    }
    if (change === 0) {
        return { text: "0%", tone: "flat" };
    }
    return { text: `${change > 0 ? "+" : ""}${change}%`, tone: change > 0 ? "up" : "down" };
}

/** Share of the top value as a whole-number percentage (top itself = 100). */
export function shareOfTop(value, top) {
    const t = Number(top || 0);
    if (t <= 0) {
        return 0;
    }
    return Math.max(0, Math.min(100, Math.round((Number(value || 0) / t) * 100)));
}

/** Show at most `maxLabels` x-axis labels: every n-th one. */
export function labelStep(count, maxLabels = 12) {
    return Math.max(1, Math.ceil(count / Math.max(1, maxLabels)));
}

/**
 * Geometry for a vertical bar chart inside a (width x height) viewBox.
 * @returns {{scale, bars:[{x,y,w,h,value,label,showLabel}], plot:{left,right,top,bottom}}}
 */
export function barLayout(items, { width = 1000, height = 320, left = 56, right = 20, top = 34, bottom = 40 } = {}) {
    const values = items.map((i) => Number(i.value || 0));
    const scale = niceScale(Math.max(0, ...values));
    const plotW = width - left - right;
    const plotH = height - top - bottom;
    const slot = items.length ? plotW / items.length : plotW;
    const barW = Math.min(90, slot * 0.6);
    const step = labelStep(items.length);
    const bars = items.map((item, i) => {
        const h = scale.max ? (Number(item.value || 0) / scale.max) * plotH : 0;
        return {
            x: left + i * slot + (slot - barW) / 2, y: top + plotH - h, w: barW, h,
            value: Number(item.value || 0), label: item.label, showLabel: i % step === 0,
        };
    });
    return { scale, bars, plot: { left, right: width - right, top, bottom: height - bottom } };
}

// ---------------------------------------------------------------- date presets (the FILTER select)
export const RANGE_PRESETS = [
    { id: "last7", label: "Last 7 days", days: 7 },
    { id: "last30", label: "Last 30 days", days: 30 },
    { id: "last90", label: "Last 3 months", days: 90 },
    { id: "last180", label: "Last 6 months", days: 180 },
    { id: "month", label: "This month" },
    { id: "year", label: "This year" },
];

function parseIso(iso) {
    const [y, m, d] = String(iso).split("-").map(Number);
    return Date.UTC(y, m - 1, d);
}

function toIso(ms) {
    return new Date(ms).toISOString().slice(0, 10);
}

/** [from, to] (ISO dates) for a preset, counting back from `todayIso`. */
export function presetRange(presetId, todayIso) {
    const today = parseIso(todayIso);
    const preset = RANGE_PRESETS.find((p) => p.id === presetId);
    if (!preset) {
        return null;
    }
    if (preset.days) {
        return [toIso(today - (preset.days - 1) * 86400000), toIso(today)];
    }
    const now = new Date(today);
    if (presetId === "month") {
        return [toIso(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)), toIso(today)];
    }
    return [toIso(Date.UTC(now.getUTCFullYear(), 0, 1)), toIso(today)];
}

/** Which preset (if any) the current dates correspond to; "custom" otherwise. */
export function detectPreset(fromIso, toIso_, todayIso) {
    for (const preset of RANGE_PRESETS) {
        const range = presetRange(preset.id, todayIso);
        if (range && range[0] === fromIso && range[1] === toIso_) {
            return preset.id;
        }
    }
    return "custom";
}
