/** @odoo-module **/
import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BarList, TrendChart, fmt, fmtMinutes, shareOfTop, useLoader } from "@adoption_intelligence/js/adoption_common";

/**
 * Model analytics (the Odoo counterpart of the original "Object Analytics").
 * Every model is compared against the busiest one (created + updated + deleted);
 * click a card for a deep dive of that model.
 */
export class AdoptionModelAnalytics extends Component {
    static template = "adoption_intelligence.ModelAnalytics";
    static components = { TrendChart, BarList };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.fmt = fmt;
        this.fmtMinutes = fmtMinutes;
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_model_analytics", [], {
                date_from: p.from, date_to: p.to, user_id: p.userId ? Number(p.userId) : false,
                model_name: p.model || false,
            })
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            if (["from", "to", "userId", "model", "rev"].some((k) => next[k] !== this.props[k])) {
                return this.load(next);
            }
        });
    }

    /** Cards, busiest first. A model with no activity is listed only while it is being tracked. */
    get cards() {
        const rows = this.loader.data.rows.map((r) => ({ ...r, events: r.created + r.updated + r.deleted }));
        const top = Math.max(0, ...rows.map((r) => r.events));
        return rows
            .filter((r) => r.events > 0 || r.status === "active")
            .map((r) => ({ ...r, pct: shareOfTop(r.events, top) }))
            .sort((a, b) => b.events - a.events);
    }
    statusLabel(status) {
        return { active: "Tracking", disabled: "Disabled", missing: "Not installed", untracked: "Not configured" }[status] || status;
    }
    get sourceBars() {
        return this.loader.data.detail.sources.map((s) => ({ label: s.label, value: s.value }));
    }
    flag(on) {
        return on ? "On" : "Off";
    }
}
