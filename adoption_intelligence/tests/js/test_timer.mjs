// Run:  bash tests/js/run.sh        (plain Node, no Odoo required)
import test from "node:test";
import assert from "node:assert/strict";
import { ActiveTimer } from "../../static/src/js/adoption_timer.mjs";

function make(opts = {}) {
    const s = { t: 0, visible: true, focus: true };
    const timer = new ActiveTimer({
        idleMs: 120000, now: () => s.t,
        isVisible: () => s.visible, hasFocus: () => s.focus, ...opts,
    });
    const run = (seconds, { input = false } = {}) => {
        for (let i = 0; i < seconds; i++) {
            s.t += 1000;
            if (input) timer.markInput(s.t);
            timer.tick(s.t);
        }
    };
    return { s, timer, run };
}

test("credits time while visible, focused and interacting", () => {
    const { timer, run } = make();
    run(30, { input: true });
    assert.equal(timer.activeSeconds, 30);
    assert.deepEqual(timer.snapshot(), { active: 30, elapsed: 30, idle: 0 });
});

test("does not credit a hidden tab", () => {
    const { s, timer, run } = make();
    s.visible = false;
    run(60, { input: true });
    assert.equal(timer.activeSeconds, 0);
    assert.equal(timer.snapshot().elapsed, 60);
});

test("does not credit an unfocused window", () => {
    const { s, timer, run } = make();
    s.focus = false;
    run(60, { input: true });
    assert.equal(timer.activeSeconds, 0);
});

test("stops crediting after the idle threshold and resumes on input", () => {
    const { timer, run } = make();
    run(10, { input: true });
    run(300);
    assert.ok(timer.activeSeconds >= 10 && timer.activeSeconds <= 10 + 120, `active=${timer.activeSeconds}`);
    const before = timer.activeSeconds;
    run(20, { input: true });
    assert.equal(timer.activeSeconds, before + 20);
    assert.ok(timer.snapshot().idle >= 170);
});

test("a long gap (suspend) credits nothing", () => {
    const { s, timer } = make();
    timer.markInput(0);
    s.t = 3 * 3600 * 1000;
    timer.markInput(s.t);
    assert.equal(timer.tick(s.t), false);
    assert.equal(timer.activeSeconds, 0);
});

test("reset starts a new visit from zero", () => {
    const { s, timer, run } = make();
    run(20, { input: true });
    timer.reset(s.t);
    assert.equal(timer.activeSeconds, 0);
    assert.equal(timer.snapshot(s.t).elapsed, 0);
});

test("active never exceeds elapsed", () => {
    const { timer, run } = make();
    run(5, { input: true });
    const snap = timer.snapshot();
    assert.ok(snap.active <= snap.elapsed);
});
