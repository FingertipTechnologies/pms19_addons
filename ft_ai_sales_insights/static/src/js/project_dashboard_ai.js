/** @odoo-module **/

/**
 * Adds the "AI Summary" feature to the Project Dashboard *from this module*,
 * so no AI code lives in ft_project_dashboard. It patches the exported
 * ProjectDashboard component (extra reactive state + handlers) and the template
 * is extended in project_dashboard_ai.xml to inject the button + panel.
 */
import { onWillStart, useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ProjectDashboard } from "@ft_project_dashboard/js/project_dashboard";

patch(ProjectDashboard.prototype, {
    setup() {
        super.setup();
        // Separate reactive state so we never touch ft_project_dashboard's own.
        this.aiState = useState({
            open: false,
            loading: false,
            period: "this_month",
            periods: [],
            purposeId: null,
            purposes: [],
            configured: false,
            provider: null,
            error: null,
            result: null,
        });
        onWillStart(async () => {
            try {
                const opts = await this.orm.call(
                    "ft.project.dashboard",
                    "get_ai_options",
                    []
                );
                this.aiState.periods = opts.periods || [];
                this.aiState.purposes = opts.purposes || [];
                // Fall back to the first purpose so Generate always has one,
                // matching the server-side resolver.
                this.aiState.purposeId =
                    opts.default_purpose_id || this.aiState.purposes[0]?.id || null;
                this.aiState.configured = opts.configured;
                this.aiState.provider = opts.provider;
            } catch {
                // AI options are optional; the button just stays disabled.
            }
        });
    },

    toggleAi() {
        this.aiState.open = !this.aiState.open;
    },
    onAiPeriod(ev) {
        this.aiState.period = ev.target.value;
    },
    onAiPurpose(ev) {
        this.aiState.purposeId = parseInt(ev.target.value, 10) || null;
    },
    async runAiSummary() {
        const ai = this.aiState;
        if (ai.loading) {
            return;
        }
        ai.loading = true;
        ai.error = null;
        try {
            ai.result = await this.orm.call(
                "ft.project.dashboard",
                "get_ai_summary",
                [ai.period, ai.purposeId]
            );
        } catch (e) {
            ai.error = e?.data?.message || e?.message || "AI summary failed.";
        } finally {
            ai.loading = false;
        }
    },
    get aiSummary() {
        return this.aiState.result?.summary || null;
    },
    get aiMeta() {
        return this.aiState.result?.meta || {};
    },
    get aiRaw() {
        return this.aiState.result?.raw_text || null;
    },
});
