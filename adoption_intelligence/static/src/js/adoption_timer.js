/** @odoo-module **/
/**
 * Active-time accounting for one visit.  No Odoo or DOM imports so it can be
 * unit tested in Node (tests/js/test_timer.mjs).
 *
 * Time is credited only when ALL of these hold at a tick:
 *   1. the tab is visible,
 *   2. the window has focus,
 *   3. there was user input within the idle threshold.
 *
 * A gap between ticks longer than `maxGapMs` (laptop suspended, tab throttled,
 * debugger paused) credits NOTHING: we never invent time we did not observe.
 *
 *   elapsed = wall clock since the visit began (visible or not)
 *   active  = credited time (an ESTIMATE of attention, not proof of it)
 *   idle    = elapsed - active
 *
 * Only the *occurrence* of input is recorded, never its content: key presses
 * and pointer positions are not read or stored.
 */
export class ActiveTimer {
    constructor({
        idleMs = 120000,
        maxGapMs = 5000,
        now = () => Date.now(),
        isVisible = () => true,
        hasFocus = () => true,
    } = {}) {
        this.idleMs = idleMs;
        this.maxGapMs = maxGapMs;
        this.now = now;
        this.isVisible = isVisible;
        this.hasFocus = hasFocus;
        this.reset(this.now());
    }

    reset(nowMs = this.now()) {
        this.startedAt = nowMs;
        this.lastTick = nowMs;
        this.lastInput = nowMs;
        this.activeMs = 0;
    }

    setIdleMs(ms) {
        this.idleMs = ms;
    }

    /** Called from input listeners. Records that input happened, nothing else. */
    markInput(nowMs = this.now()) {
        this.lastInput = nowMs;
    }

    /** Called about once per second. Returns true when time was credited. */
    tick(nowMs = this.now()) {
        const delta = nowMs - this.lastTick;
        this.lastTick = nowMs;
        if (delta <= 0 || delta > this.maxGapMs) {
            return false;
        }
        if (!this.isVisible() || !this.hasFocus()) {
            return false;
        }
        if (nowMs - this.lastInput > this.idleMs) {
            return false;
        }
        this.activeMs += delta;
        return true;
    }

    get activeSeconds() {
        return Math.floor(this.activeMs / 1000);
    }

    elapsedSeconds(nowMs = this.now()) {
        return Math.max(0, Math.floor((nowMs - this.startedAt) / 1000));
    }

    snapshot(nowMs = this.now()) {
        const elapsed = this.elapsedSeconds(nowMs);
        const active = Math.min(this.activeSeconds, elapsed);
        return { active, elapsed, idle: elapsed - active };
    }
}
