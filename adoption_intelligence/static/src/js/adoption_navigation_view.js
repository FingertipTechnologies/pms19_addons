/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BarList, TrendChart, fmt, useLoader } from "@adoption_intelligence/js/adoption_common";

const TYPE_LABELS = {
    page_view: "Page", list_view: "List / kanban", record_view: "Record", report_view: "Report / analysis",
    dashboard_view: "Dashboard", search: "Search", action_click: "Attempted action", session_start: "Session start",
};

/** Navigation: where people go in Odoo (browser telemetry, not proof of reading). */
export class AdoptionNavigationView extends Component {
    static template = "adoption_intelligence.NavigationView";
    static components = { TrendChart, BarList };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.fmt = fmt;
        this.ui = useState({ eventType: "", limit: 40 });
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_navigation", [], {
                date_from: p.from, date_to: p.to, user_id: p.userId ? Number(p.userId) : false,
                model_name: p.model || false, event_type: this.ui.eventType || false,
                limit: this.ui.limit, offset: 0,
            })
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            if (["from", "to", "userId", "model", "rev"].some((k) => next[k] !== this.props[k])) {
                this.ui.limit = 40;
                return this.load(next);
            }
        });
    }
    typeLabel(type) {
        return TYPE_LABELS[type] || type;
    }
    onType(ev) {
        this.ui.eventType = ev.target.value;
        this.ui.limit = 40;
        return this.load(this.props);
    }
    more() {
        this.ui.limit += 40;
        return this.load(this.props);
    }
}
