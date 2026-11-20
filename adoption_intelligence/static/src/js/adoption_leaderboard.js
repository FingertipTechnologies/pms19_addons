/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { BAND_CLASS, ScoreRing, errorMessage, fmt, fmtMinutes, toQuery, useLoader } from "@adoption_intelligence/js/adoption_common";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** Leaderboard for the month that contains the header's "To" date (scores are monthly). */
export class AdoptionLeaderboard extends Component {
    static template = "adoption_intelligence.Leaderboard";
    static components = { ScoreRing };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.band = BAND_CLASS;
        this.fmt = fmt;
        this.fmtMinutes = fmtMinutes;
        this.ui = useState({ search: "", sub: "score", busy: false, expanded: null });
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_leaderboard", [], {
                period_start: this.monthStart(p), period_type: "month", search: this.ui.search || false,
            })
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        onWillUpdateProps((next) => {
            if (next.rev !== this.props.rev || next.to !== this.props.to) {
                return this.load(next);
            }
        });
    }
    monthStart(p = this.props) {
        return `${(p.to || p.init.today).slice(0, 7)}-01`;
    }
    get monthLabel() {
        const [y, m] = this.monthStart().split("-").map(Number);
        return `${MONTHS[m - 1]} ${y}`;
    }
    onSearch(ev) {
        this.ui.search = ev.target.value;
        return this.load(this.props);
    }
    toggle(row) {
        this.ui.expanded = this.ui.expanded === row.user_id ? null : row.user_id;
    }
    get components() {
        const w = this.loader.data.weights;
        return [
            ["presence", "Presence"], ["data_activity", "Data activity"], ["process_compliance", "Process compliance"],
            ["feature_adoption", "Feature adoption"], ["engagement", "Engagement"], ["data_quality", "Data quality"],
        ].map(([key, label]) => ({ key, label, max: w[key] }));
    }
    pct(row, key, max) {
        return Math.round((100 * row.components[key]) / max);
    }
    async recalculate() {
        this.ui.busy = true;
        try {
            const n = await this.orm.call("adoption.user.score", "recalculate", [this.monthStart(), "month"]);
            this.notification.add(`Scores recalculated for ${n} user(s).`, { type: "success" });
            await this.load(this.props);
        } catch (error) {
            this.notification.add(errorMessage(error), { type: "danger" });
        } finally {
            this.ui.busy = false;
        }
    }
    exportXlsx() {
        window.open(`/adoption/export/leaderboard.xlsx?${toQuery({ period_start: this.monthStart(), period_type: "month" })}`, "_self");
    }
}
