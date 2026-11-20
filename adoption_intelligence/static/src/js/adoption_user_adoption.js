/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BAND_CLASS, BarList, ScoreRing, TrendChart, fmt, fmtMinutes, useLoader } from "@adoption_intelligence/js/adoption_common";

export class AdoptionUserAdoption extends Component {
    static template = "adoption_intelligence.UserAdoption";
    static components = { TrendChart, BarList, ScoreRing };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.band = BAND_CLASS;
        this.fmt = fmt;
        this.fmtMinutes = fmtMinutes;
        this.ui = useState({ limit: 40, operation: "" });
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_user_explorer", [
                p.userId ? Number(p.userId) : false, p.from, p.to, p.model || false,
                this.ui.operation || false, this.ui.limit, 0,
            ])
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            const p = this.props;
            if (["from", "to", "userId", "model", "rev"].some((k) => next[k] !== p[k])) {
                this.ui.limit = 40;
                return this.load(next);
            }
        });
    }
    more() {
        this.ui.limit += 40;
        return this.load(this.props);
    }
    onOperation(ev) {
        this.ui.operation = ev.target.value;
        return this.load(this.props);
    }
    get componentRows() {
        const s = this.loader.data.score;
        if (!s) {
            return [];
        }
        const w = this.loader.data.weights;
        return [
            ["presence", "Presence"], ["data_activity", "Data activity"], ["process_compliance", "Process compliance"],
            ["feature_adoption", "Feature adoption"], ["engagement", "Engagement"], ["data_quality", "Data quality"],
        ].map(([key, label]) => ({ label, value: s.components[key], max: w[key], pct: Math.round((100 * s.components[key]) / w[key]) }));
    }
    get modelBars() {
        return this.loader.data.by_model.slice(0, 8).map((m) => ({ label: m.label, value: m.created + m.updated + m.deleted }));
    }
    openRecord(row) {
        if (row.model_name && row.record_id && row.operation !== "delete") {
            this.action.doAction({ type: "ir.actions.act_window", res_model: row.model_name, res_id: row.record_id, views: [[false, "form"]] });
        }
    }
}
