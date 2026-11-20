/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { errorMessage, useLoader } from "@adoption_intelligence/js/adoption_common";

export class AdoptionHealth extends Component {
    static template = "adoption_intelligence.Health";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.ui = useState({ testing: false, test: null, testError: null });
        const { state, load } = useLoader(() => this.orm.call("adoption.dashboard", "get_health", []));
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load());
        onWillUpdateProps((next) => {
            if (next.rev !== this.props.rev) {
                return this.load();
            }
        });
    }
    openErrors() {
        this.action.doAction("adoption_intelligence.action_adoption_error_log");
    }
    async runSelfTest() {
        this.ui.testing = true;
        this.ui.test = null;
        this.ui.testError = null;
        try {
            this.ui.test = await this.orm.call("adoption.dashboard", "run_self_test", []);
        } catch (error) {
            this.ui.testError = errorMessage(error);
        } finally {
            this.ui.testing = false;
        }
    }
    icon(status) {
        return { ok: "fa-check-circle", warn: "fa-exclamation-triangle", fail: "fa-times-circle" }[status];
    }
}
