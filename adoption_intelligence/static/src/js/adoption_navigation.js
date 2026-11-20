/** @odoo-module **/
/**
 * Turns "what the Odoo web client is showing" into a tracking event.
 * Pure functions (no Odoo/DOM imports) so they can be unit tested in Node.
 *
 * What can and cannot be observed is documented in docs/LIMITATIONS.md.
 * In short: views shown by the action manager (list, kanban, form, graph,
 * pivot, client actions) are observable; PDF downloads, xlsx exports and
 * pop-up dialogs are not.
 */

export const IGNORED_MODEL_PREFIXES = ["adoption."];
export const IGNORED_TAG_PREFIXES = ["adoption_intelligence."];
const MODEL_RE = /^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$/;
const COLLECTION_VIEWS = ["list", "kanban"];
const ANALYSIS_VIEWS = ["graph", "pivot", "cohort"];

/**
 * The browser session key and the queue of unsent events live in sessionStorage, which
 * survives a logout followed by another person logging in IN THE SAME TAB.  Both are
 * therefore stamped with the id of the user they belong to, and are only reused for
 * that same user.  (The server never trusts the browser for identity anyway: it takes
 * the user from the authenticated session, so without this, user A's unsent events
 * would be stored under user B.)
 */
export function resolveBrowserSession(stored, uid, make) {
    let parsed = null;
    try {
        parsed = JSON.parse(stored);
    } catch {
        parsed = null;
    }
    if (parsed && parsed.uid === uid && typeof parsed.key === "string" && parsed.key) {
        return { key: parsed.key, fresh: false, stored: stored };
    }
    const key = (make || newKey)();
    return { key, fresh: true, stored: JSON.stringify({ uid, key }) };
}

export function packQueue(uid, events, max = 100) {
    return JSON.stringify({ uid, events: (events || []).slice(-max) });
}

/** Events saved by a previous page of the SAME user; anything else is discarded. */
export function unpackQueue(raw, uid) {
    try {
        const saved = JSON.parse(raw);
        if (saved && saved.uid === uid && Array.isArray(saved.events)) {
            return saved.events;
        }
    } catch {
        /* malformed: ignore */
    }
    return [];
}

export function newKey(length = 24) {
    const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
    const out = [];
    const cryptoObj = typeof crypto !== "undefined" ? crypto : null;
    if (cryptoObj && cryptoObj.getRandomValues) {
        const bytes = new Uint8Array(length);
        cryptoObj.getRandomValues(bytes);
        for (const b of bytes) {
            out.push(alphabet[b % alphabet.length]);
        }
    } else {
        for (let i = 0; i < length; i++) {
            out.push(alphabet[Math.floor(Math.random() * alphabet.length)]);
        }
    }
    return out.join("");
}

/** Extracts a saved record id from the URL path as a last resort. */
export function resIdFromPath(pathname) {
    const match = /\/(\d+)\/?$/.exec(pathname || "");
    return match ? parseInt(match[1], 10) : null;
}

/**
 * @param {Object} info
 *   actionType  ir.actions.* type string
 *   tag         client action tag
 *   resModel    model shown by the controller
 *   resId       record id (number) or falsy/"new" when unsaved
 *   viewType    "form" | "list" | "kanban" | "graph" | ...
 *   actionName  the ACTION's name (never the record title)
 *   actionRef   xml id or numeric id of the action
 * @returns {Object|null} null = do not track this screen
 */
export function classifyView(info) {
    if (!info) {
        return null;
    }
    const model = info.resModel && MODEL_RE.test(info.resModel) ? info.resModel : null;
    if (model && IGNORED_MODEL_PREFIXES.some((p) => model.startsWith(p))) {
        return null;
    }
    if (info.tag && IGNORED_TAG_PREFIXES.some((p) => String(info.tag).startsWith(p))) {
        return null;
    }
    const base = {
        model,
        recordId: null,
        aid: info.actionRef ? String(info.actionRef) : info.tag ? String(info.tag) : null,
        name: info.actionName ? String(info.actionName) : null,
        viewType: info.viewType || null,
    };
    const tag = String(info.tag || "").toLowerCase();
    if (info.actionType === "ir.actions.client" || (tag && !info.viewType)) {
        if (tag.includes("dashboard")) {
            return { ...base, eventType: "dashboard_view", kind: "dashboard" };
        }
        if (tag.includes("report")) {
            return { ...base, eventType: "report_view", kind: "analysis" };
        }
        return { ...base, eventType: "page_view", kind: "client" };
    }
    const view = info.viewType;
    if (view === "form") {
        const id = typeof info.resId === "number" && info.resId > 0 ? info.resId : null;
        if (id) {
            return { ...base, eventType: "record_view", kind: "record", recordId: id };
        }
        return { ...base, eventType: "page_view", kind: "form_new" };
    }
    if (COLLECTION_VIEWS.includes(view)) {
        return { ...base, eventType: "list_view", kind: "list" };
    }
    if (ANALYSIS_VIEWS.includes(view)) {
        return { ...base, eventType: "report_view", kind: "analysis" };
    }
    if (view === "dashboard") {
        return { ...base, eventType: "dashboard_view", kind: "dashboard" };
    }
    return { ...base, eventType: "page_view", kind: "other" };
}

export function viewSignature(view) {
    if (!view) {
        return "";
    }
    return [view.eventType, view.model, view.recordId, view.aid, view.viewType].join("|");
}

/**
 * Reads the screen currently shown by the action manager.
 * `routerModule` is optional (resolved defensively by the service) and only
 * used to find the id of the record shown by a form with a pager.
 */
export function readCurrentView(actionService, routerModule, pathname) {
    const controller = actionService && actionService.currentController;
    if (!controller) {
        return null;
    }
    const action = controller.action || {};
    const props = controller.props || {};
    let resId = null;
    const current = routerModule && routerModule.router && routerModule.router.current;
    if (current) {
        const v = current.resId !== undefined ? current.resId : current.id;
        resId = typeof v === "number" ? v : null;
    }
    if (resId === null) {
        resId = typeof props.resId === "number" ? props.resId : resIdFromPath(pathname);
    }
    return classifyView({
        actionType: action.type,
        tag: action.tag,
        resModel: props.resModel || action.res_model || null,
        resId,
        viewType: props.type || (controller.view && controller.view.type) || null,
        actionName: action.name,
        actionRef: action.xml_id || action.id,
    });
}
