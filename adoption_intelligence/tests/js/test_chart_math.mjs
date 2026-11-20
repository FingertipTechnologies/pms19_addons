import test from "node:test";
import assert from "node:assert/strict";
import { niceScale, pctChange, changeInfo, shareOfTop, labelStep, barLayout } from "../../static/src/js/adoption_chart_math.mjs";

test("niceScale produces round ticks that always cover the data", () => {
    for (const max of [1, 3, 7, 18, 54, 99, 100, 101, 250, 1234, 98765]) {
        const s = niceScale(max);
        assert.equal(s.ticks[0], 0);
        assert.ok(s.max >= max, `max ${s.max} must cover ${max}`);
        assert.ok(s.ticks.length >= 3 && s.ticks.length <= 8, `ticks for ${max}: ${s.ticks}`);
        for (let i = 1; i < s.ticks.length; i++) {
            assert.ok(Math.abs(s.ticks[i] - s.ticks[i - 1] - s.step) < 1e-6);
        }
    }
});

test("niceScale for the screenshot value 54", () => {
    const s = niceScale(54);
    assert.deepEqual(s.ticks, [0, 20, 40, 60]);
});

test("niceScale handles zero / garbage without NaN or division by zero", () => {
    for (const v of [0, -5, NaN, undefined, "x"]) {
        const s = niceScale(v);
        assert.ok(s.ticks.every((t) => Number.isFinite(t)));
        assert.ok(s.max > 0);
    }
});

test("pctChange: the -93% case from the Reports screenshot (54 -> 4)", () => {
    assert.equal(pctChange(4, 54), -93);
    assert.equal(pctChange(54, 4), 1250);
    assert.equal(pctChange(10, 10), 0);
});

test("pctChange never divides by zero", () => {
    assert.equal(pctChange(5, 0), null);
    assert.equal(pctChange(0, 0), 0);
    assert.equal(pctChange(0, 8), -100);
});

test("changeInfo wording and tone", () => {
    assert.deepEqual(changeInfo(1, 1, false), { text: "—", tone: "none" });
    assert.deepEqual(changeInfo(4, 54, true), { text: "-93%", tone: "down" });
    assert.deepEqual(changeInfo(60, 50, true), { text: "+20%", tone: "up" });
    assert.deepEqual(changeInfo(5, 5, true), { text: "0%", tone: "flat" });
    assert.deepEqual(changeInfo(3, 0, true), { text: "new", tone: "up" });
});

test("shareOfTop matches the Object Analytics screenshot (top = 23 events incl. deletions)", () => {
    assert.equal(shareOfTop(23, 23), 100);   // Account  5 created + 17 updated + 1 deleted
    assert.equal(shareOfTop(5, 23), 22);     // Contact
    assert.equal(shareOfTop(4, 23), 17);     // Assessment Task
    assert.equal(shareOfTop(3, 23), 13);     // Lead
    assert.equal(shareOfTop(2, 23), 9);      // Case, Customer
    assert.equal(shareOfTop(1, 23), 4);      // Asset
    assert.equal(shareOfTop(0, 23), 0);
    assert.equal(shareOfTop(5, 0), 0);
    assert.equal(shareOfTop(50, 23), 100, "clamped");
});

test("labelStep thins crowded axes", () => {
    assert.equal(labelStep(5), 1);
    assert.equal(labelStep(12), 1);
    assert.equal(labelStep(90), 8);
    assert.equal(labelStep(0), 1);
});

test("barLayout keeps every bar inside the plot area and scales heights", () => {
    const L = barLayout([{ label: "Sep 2026", value: 54 }, { label: "Oct 2026", value: 4 }]);
    assert.equal(L.bars.length, 2);
    const plotH = L.plot.bottom - L.plot.top;
    for (const b of L.bars) {
        assert.ok(b.x >= L.plot.left && b.x + b.w <= L.plot.right);
        assert.ok(b.y >= L.plot.top - 1e-6 && b.y + b.h <= L.plot.bottom + 1e-6);
        assert.ok(b.h <= plotH + 1e-6);
    }
    assert.ok(L.bars[0].h > L.bars[1].h * 10, "54 is much taller than 4");
});

test("barLayout with no data or all zeros does not throw", () => {
    assert.equal(barLayout([]).bars.length, 0);
    const z = barLayout([{ label: "a", value: 0 }, { label: "b", value: 0 }]);
    assert.ok(z.bars.every((b) => b.h === 0));
});

import { presetRange, detectPreset, RANGE_PRESETS } from "../../static/src/js/adoption_chart_math.mjs";

test("presetRange: Last 3 months for 22 Oct 2026 is the 25 Jul – 22 Oct range in the screenshot", () => {
    assert.deepEqual(presetRange("last90", "2026-10-22"), ["2026-07-25", "2026-10-22"]);
});

test("presetRange: the other presets", () => {
    assert.deepEqual(presetRange("last7", "2026-10-22"), ["2026-10-16", "2026-10-22"]);
    assert.deepEqual(presetRange("last30", "2026-10-22"), ["2026-09-23", "2026-10-22"]);
    assert.deepEqual(presetRange("last180", "2026-10-22"), ["2026-04-26", "2026-10-22"]);
    assert.deepEqual(presetRange("month", "2026-10-22"), ["2026-10-01", "2026-10-22"]);
    assert.deepEqual(presetRange("year", "2026-10-22"), ["2026-01-01", "2026-10-22"]);
    assert.equal(presetRange("nonsense", "2026-10-22"), null);
});

test("presetRange crosses month and year boundaries correctly (no timezone drift)", () => {
    assert.deepEqual(presetRange("last7", "2027-01-03"), ["2026-12-28", "2027-01-03"]);
    assert.deepEqual(presetRange("last30", "2026-03-01"), ["2026-01-31", "2026-03-01"]);
    assert.deepEqual(presetRange("month", "2026-02-28"), ["2026-02-01", "2026-02-28"]);
});

test("detectPreset round-trips and falls back to custom", () => {
    for (const p of RANGE_PRESETS) {
        const [f, t] = presetRange(p.id, "2026-10-22");
        const found = detectPreset(f, t, "2026-10-22");
        assert.deepEqual(presetRange(found, "2026-10-22"), [f, t], p.id);
    }
    assert.equal(detectPreset("2026-10-02", "2026-10-09", "2026-10-22"), "custom");
});
