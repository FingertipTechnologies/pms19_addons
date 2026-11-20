/** @odoo-module **/
/**
 * Adoption Intelligence web-client tracker (replaces the Chrome extension).
 *
 * One shared service for every model: it watches which screen the Odoo action
 * manager is showing, times active use, and reports to the server in small
 * idempotent batches.  There is no per-model JavaScript.
 *
 * What it sends:  which screen/record was opened, cumulative active seconds,
 *                 and COUNTS of searches and attempted actions.
 * What it never sends: key presses, mouse positions, search terms, filter
 *                 values, field values, screenshots, or a user id (the server
 *                 takes the user from the authenticated session).
 *
 * Whether an operation SUCCEEDED is never inferred here: that comes only from
 * the server-side ORM events.  An "action_click" is merely an attempt.
 */
import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ActiveTimer } from "@adoption_intelligence/js/adoption_timer";
import {
    newKey,
    packQueue,
    readCurrentView,
    resolveBrowserSession,
    unpackQueue,
    viewSignature,
} from "@adoption_intelligence/js/adoption_navigation";

const BS_KEY = "adoption.browser_session";
const QUEUE_KEY = "adoption.queue";
const MAX_QUEUE = 200;
const MAX_SIGNALS_QUEUED = 50;
const ATTEMPT_METHODS = new Set(["web_save", "create", "write", "unlink"]);
const SEARCH_METHODS = new Set(["web_search_read", "web_read_group", "read_group", "formatted_read_group", "search_read"]);
const BEACON_URL = "/web/dataset/call_kw/adoption.tracker/track";

let ormPatched = false;
let activeTracker = null;

/** Optional internals are looked up defensively so a rename in another Odoo
 *  build degrades one feature instead of breaking the whole web client. */
function loaderModule(name) {
    try {
        return window.odoo && window.odoo.loader && window.odoo.loader.modules.get(name);
    } catch {
        return undefined;
    }
}

function patchOrmOnce() {
    if (ormPatched) {
        return;
    }
    const ORM = (loaderModule("@web/core/orm_service") || {}).ORM;
    if (!ORM) {
        console.warn("[adoption] ORM class not found: search/attempt counting disabled");
        return;
    }
    ormPatched = true;
    patch(ORM.prototype, {
        call(model, method, args = [], kwargs = {}) {
            try {
                if (activeTracker) {
                    activeTracker.observe(model, method, args, kwargs);
                }
            } catch {
                /* observing must never affect a real call */
            }
            return super.call(...arguments);
        },
    });
}

class AdoptionTracker {
    constructor(env, orm, action) {
        this.env = env;
        this.orm = orm.silent || orm;
        this.action = action;
        this.config = null;
        this.queue = [];
        this.visit = null;
        this.sig = "";
        this.beatCountdown = 0;
        this.backoffUntil = 0;
        this.domainSig = new Map();
        this.lastAttempt = new Map();
        this.lastInputMove = 0;
        this.timer = new ActiveTimer({
            isVisible: () => document.visibilityState === "visible",
            hasFocus: () => document.hasFocus(),
        });
    }

    // ---------------------------------------------------------------- lifecycle
    async init() {
        try {
            this.config = await this.orm.call("adoption.tracker", "get_client_config", []);
        } catch {
            return;                                  // not allowed / offline: stay silent
        }
        if (!this.config || !this.config.enabled) {
            return;
        }
        this.timer.setIdleMs(this.config.idle_seconds * 1000);
        this.uid = this.config.uid;
        this.browserSession = this.ensureBrowserSession();
        this.restoreQueue();
        this.bindEvents();
        activeTracker = this;
        patchOrmOnce();
        this.timerId = window.setInterval(() => this.onTick(), 1000);
    }

    /**
     * One browser session per (tab, user).  The key is stamped with the user id so that
     * somebody else logging in in the same tab never inherits the previous user's key.
     */
    ensureBrowserSession() {
        let stored = null;
        try {
            stored = window.sessionStorage.getItem(BS_KEY);
        } catch {
            stored = null;
        }
        const session = resolveBrowserSession(stored, this.uid);
        if (session.fresh) {
            try {
                window.sessionStorage.setItem(BS_KEY, session.stored);
            } catch {
                /* storage unavailable: a new session per page load */
            }
            if (this.config.navigation) {
                this.enqueue({ t: "visit", key: newKey(), bs: session.key, ev: "session_start", kind: "other", ts: Date.now() });
            }
        }
        return session.key;
    }

    bindEvents() {
        const input = () => this.timer.markInput();
        const opts = { capture: true, passive: true };
        for (const name of ["pointerdown", "keydown", "wheel", "touchstart"]) {
            window.addEventListener(name, input, opts);
        }
        // Mouse movement counts as presence, but is sampled at most once a second.
        window.addEventListener("pointermove", () => {
            const now = Date.now();
            if (now - this.lastInputMove > 1000) {
                this.lastInputMove = now;
                this.timer.markInput(now);
            }
        }, opts);
        document.addEventListener("visibilitychange", () => {
            if (document.visibilityState === "hidden") {
                this.pushBeat(false);
                this.flush({ beacon: true });      // the tab may never come back (mobile)
            } else {
                this.timer.markInput();
            }
        });
        window.addEventListener("pagehide", () => {
            this.closeVisit();
            this.persistQueue();
            this.flush({ beacon: true });
        });
    }

    // ---------------------------------------------------------------- ticking
    onTick() {
        this.timer.tick();
        let view = null;
        try {
            view = readCurrentView(
                this.action, loaderModule("@web/core/browser/router"), window.location.pathname
            );
        } catch {
            view = null;
        }
        const sig = viewSignature(view);
        if (sig !== this.sig) {
            this.sig = sig;
            this.switchVisit(view);
        }
        if (this.visit && ++this.beatCountdown >= this.config.heartbeat_seconds) {
            this.beatCountdown = 0;
            this.pushBeat(false);
        }
        if (this.queue.length >= 10 || (this.queue.length && this.beatCountdown === 0)) {
            this.flush();
        }
    }

    switchVisit(view) {
        this.closeVisit();
        this.visit = null;
        this.domainSig.clear();
        if (!view) {
            return;                                  // our own screens / nothing shown
        }
        const cfg = this.config;
        if (view.eventType === "record_view" && !cfg.record_views) {
            return;
        }
        if (view.eventType !== "record_view" && !cfg.navigation) {
            return;
        }
        this.visit = { key: newKey(), seq: 0, startedAt: Date.now(), lastActive: -1, lastElapsed: -1 };
        this.timer.reset();
        this.timer.markInput();
        this.beatCountdown = 0;
        this.enqueue({
            t: "visit", key: this.visit.key, bs: this.browserSession, ev: view.eventType,
            kind: view.kind, model: view.model || undefined, rid: view.recordId || undefined,
            aid: view.aid || undefined, name: view.name || undefined, vt: view.viewType || undefined,
            ts: Date.now(),
        });
    }

    closeVisit() {
        if (this.visit) {
            this.pushBeat(true);
        }
    }

    /** Beats carry CUMULATIVE totals, so only the latest one per visit matters. */
    pushBeat(ended) {
        const v = this.visit;
        if (!v) {
            return;
        }
        const { active, elapsed } = this.timer.snapshot();
        if (!ended && active === v.lastActive && elapsed === v.lastElapsed) {
            return;
        }
        v.lastActive = active;
        v.lastElapsed = elapsed;
        this.enqueue({ t: "beat", key: v.key, seq: ++v.seq, act: active, ela: elapsed, end: ended ? 1 : 0 });
    }

    // ---------------------------------------------------------------- signals
    observe(model, method, args, kwargs) {
        if (!this.config || !model || model.startsWith("adoption.") || !this.visit) {
            return;
        }
        const now = Date.now();
        if (this.config.actions && (ATTEMPT_METHODS.has(method) || method.startsWith("action_") || method.startsWith("button_"))) {
            const id = `${model}|${method}`;
            if (now - (this.lastAttempt.get(id) || 0) > 2000) {
                this.lastAttempt.set(id, now);
                this.enqueue({ t: "signal", key: newKey(), ev: "action_click", model, aid: method, bs: this.browserSession, ts: now });
            }
        }
        if (this.config.search && SEARCH_METHODS.has(method)) {
            const domain = (args && args[0] !== undefined && Array.isArray(args[0])) ? args[0] : (kwargs && kwargs.domain) || [];
            const sig = JSON.stringify(domain);                 // compared locally, never sent
            const previous = this.domainSig.get(model);
            this.domainSig.set(model, sig);
            if (previous !== undefined && previous !== sig) {
                this.enqueue({ t: "signal", key: newKey(), ev: "search", model, bs: this.browserSession, ts: now });
            }
        }
    }

    // ---------------------------------------------------------------- queue / transport
    enqueue(event) {
        if (event.t === "beat") {
            const i = this.queue.findIndex((e) => e.t === "beat" && e.key === event.key);
            if (i >= 0) {
                this.queue.splice(i, 1);              // superseded by this cumulative beat
            }
        }
        this.queue.push(event);
        if (this.queue.length > MAX_QUEUE) {          // bounded: shed oldest signals first
            const s = this.queue.findIndex((e) => e.t === "signal");
            this.queue.splice(s >= 0 ? s : 0, 1);
        }
        if (this.queue.filter((e) => e.t === "signal").length > MAX_SIGNALS_QUEUED) {
            this.queue.splice(this.queue.findIndex((e) => e.t === "signal"), 1);
        }
    }

    takeBatch() {
        return this.queue.splice(0, this.config.max_batch || 50);
    }

    async flush({ beacon = false } = {}) {
        if (!this.queue.length || !this.config) {
            return;
        }
        if (beacon) {
            const batch = this.takeBatch();
            const body = JSON.stringify({
                jsonrpc: "2.0", method: "call", id: Date.now(),
                params: { model: "adoption.tracker", method: "track", args: [{ events: batch }], kwargs: {} },
            });
            let sent = false;
            try {
                sent = navigator.sendBeacon(BEACON_URL, new Blob([body], { type: "application/json" }));
            } catch {
                sent = false;
            }
            if (!sent) {
                this.queue.unshift(...batch);        // keep for the next page load
                this.persistQueue();
            }
            return;
        }
        if (Date.now() < this.backoffUntil || this.flushing) {
            return;
        }
        this.flushing = true;
        const batch = this.takeBatch();
        try {
            const result = await this.orm.call("adoption.tracker", "track", [{ events: batch }]);
            this.failures = 0;
            if (result && (result.disabled || result.throttled)) {
                this.backoffUntil = Date.now() + 60000;
            }
        } catch {
            // Network / session problem: keep the batch (idempotent on the server)
            // and retry with exponential back-off up to 5 minutes.
            this.queue.unshift(...batch);
            this.failures = (this.failures || 0) + 1;
            this.backoffUntil = Date.now() + Math.min(300000, 2000 * 2 ** this.failures);
        } finally {
            this.flushing = false;
        }
    }

    persistQueue() {
        try {
            window.sessionStorage.setItem(QUEUE_KEY, packQueue(this.uid, this.queue));
        } catch {
            /* ignore */
        }
    }

    /** Only events saved by this same user are restored; another user's are dropped. */
    restoreQueue() {
        let raw = null;
        try {
            raw = window.sessionStorage.getItem(QUEUE_KEY);
            window.sessionStorage.removeItem(QUEUE_KEY);
        } catch {
            raw = null;
        }
        unpackQueue(raw, this.uid).forEach((event) => this.enqueue(event));
    }
}

export const adoptionActivityService = {
    dependencies: ["orm", "action"],
    start(env, { orm, action }) {
        // Not async on purpose: an async start() would delay the web client boot.
        const tracker = new AdoptionTracker(env, orm, action);
        tracker.init();
        return { tracker };
    },
};

registry.category("services").add("adoption_activity", adoptionActivityService);
