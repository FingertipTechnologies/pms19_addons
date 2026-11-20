import test from "node:test";
import assert from "node:assert/strict";
import { classifyView, resIdFromPath, newKey, viewSignature, readCurrentView } from "../../static/src/js/adoption_navigation.mjs";

test("saved form is a record view", () => {
    const v = classifyView({ viewType: "form", resModel: "crm.lead", resId: 125, actionName: "Pipeline" });
    assert.equal(v.eventType, "record_view");
    assert.equal(v.recordId, 125);
    assert.equal(v.kind, "record");
});

test("unsaved form is a page view with no record id", () => {
    for (const resId of [false, null, undefined, "new", 0]) {
        const v = classifyView({ viewType: "form", resModel: "crm.lead", resId });
        assert.equal(v.eventType, "page_view");
        assert.equal(v.kind, "form_new");
        assert.equal(v.recordId, null);
    }
});

test("list and kanban are list views; graph and pivot are reports", () => {
    assert.equal(classifyView({ viewType: "list", resModel: "sale.order" }).eventType, "list_view");
    assert.equal(classifyView({ viewType: "kanban", resModel: "sale.order" }).eventType, "list_view");
    assert.equal(classifyView({ viewType: "graph", resModel: "sale.report" }).eventType, "report_view");
    assert.equal(classifyView({ viewType: "pivot", resModel: "sale.report" }).eventType, "report_view");
});

test("client actions: dashboard / report / other", () => {
    assert.equal(classifyView({ actionType: "ir.actions.client", tag: "action_spreadsheet_dashboard" }).eventType, "dashboard_view");
    assert.equal(classifyView({ actionType: "ir.actions.client", tag: "account_report" }).eventType, "report_view");
    assert.equal(classifyView({ actionType: "ir.actions.client", tag: "something_else" }).eventType, "page_view");
});

test("the tracker never tracks itself", () => {
    assert.equal(classifyView({ viewType: "list", resModel: "adoption.activity.log" }), null);
    assert.equal(classifyView({ actionType: "ir.actions.client", tag: "adoption_intelligence.dashboard" }), null);
});

test("invalid model names are dropped, not forwarded", () => {
    const v = classifyView({ viewType: "list", resModel: "x; drop table" });
    assert.equal(v.model, null);
});

test("page name is the ACTION name, never the record title", () => {
    const v = classifyView({ viewType: "form", resModel: "res.partner", resId: 7, actionName: "Contacts" });
    assert.equal(v.name, "Contacts");
});

test("resId from path, key generation, signature", () => {
    assert.equal(resIdFromPath("/odoo/crm/42"), 42);
    assert.equal(resIdFromPath("/odoo/action-12"), null);
    assert.equal(resIdFromPath("/odoo/crm/new"), null);
    const k = newKey();
    assert.match(k, /^[A-Za-z0-9]{24}$/);
    assert.notEqual(newKey(), newKey());
    assert.equal(viewSignature(null), "");
});

test("readCurrentView prefers the router id (pager) over stale props", () => {
    const action = { currentController: { action: { name: "Pipeline", id: 3 }, props: { resModel: "crm.lead", type: "form", resId: 1 } } };
    const v = readCurrentView(action, { router: { current: { resId: 9 } } }, "/odoo/crm/9");
    assert.equal(v.recordId, 9);
    assert.equal(readCurrentView({ currentController: null }), null);
});

import { resolveBrowserSession, packQueue, unpackQueue } from "../../static/src/js/adoption_navigation.mjs";

test("browser session key is reused for the same user and replaced for another user", () => {
    let n = 0;
    const make = () => `KEY${++n}`;
    const first = resolveBrowserSession(null, 7, make);
    assert.deepEqual([first.key, first.fresh], ["KEY1", true]);
    const same = resolveBrowserSession(first.stored, 7, make);
    assert.deepEqual([same.key, same.fresh], ["KEY1", false], "same user keeps the key");
    const other = resolveBrowserSession(first.stored, 8, make);
    assert.deepEqual([other.key, other.fresh], ["KEY2", true], "a different user must not inherit it");
});

test("legacy / malformed stored keys are treated as a new browser session", () => {
    for (const stored of ["PLAINSTRINGKEY12345", "", "{not json", "null", '{"uid":7}', '{"key":"x"}', undefined]) {
        const r = resolveBrowserSession(stored, 7, () => "NEWKEY");
        assert.equal(r.fresh, true, String(stored));
        assert.equal(r.key, "NEWKEY");
    }
});

test("unsent events are only restored for the user who produced them", () => {
    const events = [{ t: "visit", key: "a" }, { t: "beat", key: "a" }];
    const raw = packQueue(7, events);
    assert.deepEqual(unpackQueue(raw, 7), events);
    assert.deepEqual(unpackQueue(raw, 8), [], "user B never receives user A's events");
    assert.deepEqual(unpackQueue("[1,2,3]", 7), [], "old unstamped format is dropped");
    assert.deepEqual(unpackQueue("garbage", 7), []);
    assert.deepEqual(unpackQueue(null, 7), []);
    assert.deepEqual(unpackQueue('{"uid":7,"events":"x"}', 7), []);
});

test("packQueue is bounded", () => {
    const many = Array.from({ length: 500 }, (_, i) => ({ i }));
    assert.equal(unpackQueue(packQueue(1, many), 1).length, 100);
    assert.equal(unpackQueue(packQueue(1, many, 10), 1)[9].i, 499, "keeps the newest");
});
