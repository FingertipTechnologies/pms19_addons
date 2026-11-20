/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { fmt, toQuery, useLoader } from "@adoption_intelligence/js/adoption_common";

/** Field adoption. With no model chosen it covers ALL tracked models (the default). */
export class AdoptionFieldAdoption extends Component {
    static template = "adoption_intelligence.FieldAdoption";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.fmt = fmt;
        this.ui = useState({ meaningfulOnly: false });
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_field_adoption", [], {
                model_name: p.model || false, date_from: p.from, date_to: p.to,
                user_id: p.userId ? Number(p.userId) : false, meaningful_only: this.ui.meaningfulOnly,
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
    toggleMeaningful() {
        this.ui.meaningfulOnly = !this.ui.meaningfulOnly;
        return this.load(this.props);
    }
    statusLabel(status) {
        return { observed: "Observed, never edited", partial: "Tracking incomplete in this range", not_observed: "Not observed" }[status] || status;
    }
    exportXlsx() {
        const p = this.props;
        window.open(`/adoption/export/fields.xlsx?${toQuery({
            model_name: p.model, date_from: p.from, date_to: p.to, user_id: p.userId,
        })}`, "_self");
    }
}
