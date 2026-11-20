/** @odoo-module **/
import { Component, useState, onWillStart, onWillUpdateProps, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import {
    BAND_CLASS, BarList, ScoreRing, TrendChart, errorMessage, fmt, fmtMinutes, useLoader,
} from "@adoption_intelligence/js/adoption_common";
import { RANGE_PRESETS, detectPreset, presetRange } from "@adoption_intelligence/js/adoption_chart_math";
import { AdoptionLeaderboard } from "@adoption_intelligence/js/adoption_leaderboard";
import { AdoptionUserAdoption } from "@adoption_intelligence/js/adoption_user_adoption";
import { AdoptionFieldAdoption } from "@adoption_intelligence/js/adoption_field_adoption";
import { AdoptionHealth } from "@adoption_intelligence/js/adoption_health";
import { AdoptionNavigationView } from "@adoption_intelligence/js/adoption_navigation_view";
import { AdoptionActivityLogView } from "@adoption_intelligence/js/adoption_activity_log";
import { AdoptionModelAnalytics } from "@adoption_intelligence/js/adoption_model_analytics";
import { AdoptionReports } from "@adoption_intelligence/js/adoption_reports";

const THEME_KEY = "adoption.theme";
const AUTO_REFRESH_MS = 60000;
const PDF_REPORT = "adoption_intelligence.report_screen";

function loadTheme() {
    try {
        const saved = window.localStorage.getItem(THEME_KEY);
        if (saved === "dark" || saved === "light") {
            return saved;
        }
    } catch {
        /* storage unavailable */
    }
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function isoDate(d) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Overview: executive KPIs, trend, object adoption, insights. */
export class AdoptionOverview extends Component {
    static template = "adoption_intelligence.Overview";
    static components = { TrendChart, BarList, ScoreRing };
    static props = ["*"];
    setup() {
        this.orm = useService("orm");
        this.band = BAND_CLASS;
        this.fmt = fmt;
        this.fmtMinutes = fmtMinutes;
        const { state, load } = useLoader((p) =>
            this.orm.call("adoption.dashboard", "get_overview", [p.from, p.to, p.userId || false, p.model || false])
        );
        this.loader = state;
        this.load = load;
        onWillStart(() => this.load(this.props));
        // Must be registered through the hook: a class method of this name is never called.
        onWillUpdateProps((next) => this.load(next));
    }
    get factors() {
        return this.loader.data.factors.map((f) => ({ label: f.label, value: f.value }));
    }
    get objects() {
        return this.loader.data.objects.map((o) => ({ label: o.label, value: o.events + o.field_edits }));
    }
    get bands() {
        const d = this.loader.data;
        return this.props.init.bands.map((b) => ({ label: b.label, value: d.bands[b.key] || 0, key: b.key }));
    }
    get donutStyle() {
        return `--pct:${this.loader.data.kpis.human_pct};`;
    }
}

export class AdoptionDashboard extends Component {
    static template = "adoption_intelligence.Dashboard";
    static components = {
        AdoptionOverview, AdoptionLeaderboard, AdoptionUserAdoption, AdoptionFieldAdoption, AdoptionHealth,
        AdoptionNavigationView, AdoptionActivityLogView, AdoptionModelAnalytics, AdoptionReports,
    };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.presets = RANGE_PRESETS;
        const params = (this.props.action && (this.props.action.params || this.props.action.context)) || {};
        this.state = useState({
            tab: params.tab || params.adoption_tab || "overview",
            init: null, error: null, theme: loadTheme(),
            from: "", to: "", preset: "last90", groupBy: "month", userId: "", model: "", rev: 0,
        });
        onWillStart(() => this.loadInit());
        onMounted(() => {
            this.refreshTimer = window.setInterval(() => {
                if (this.state.tab === "overview" && document.visibilityState === "visible") {
                    this.state.rev++;
                }
            }, AUTO_REFRESH_MS);
        });
        onWillUnmount(() => window.clearInterval(this.refreshTimer));
    }

    async loadInit() {
        try {
            const init = await this.orm.call("adoption.dashboard", "get_init", []);
            this.state.init = init;
            this.applyPreset("last90");
            if (!init.is_manager && ["overview", "leaderboard", "fields", "health", "models"].includes(this.state.tab)) {
                this.state.tab = "user";
            }
        } catch (error) {
            this.state.error = errorMessage(error);
        }
    }

    // ------------------------------------------------------------ screens
    /** Every screen. `manager: true` = hidden from ordinary users (the server enforces it too). */
    get allTabs() {
        return [
            { id: "overview", group: "main", label: _t("Overview"), icon: "fa-th-large", manager: true },
            { id: "leaderboard", group: "main", label: _t("Leaderboard"), icon: "fa-trophy", manager: true },
            { id: "user", group: "main", label: _t("User adoption"), icon: "fa-user", manager: false },
            { id: "fields", group: "main", label: _t("Field adoption"), icon: "fa-th", manager: true },
            { id: "health", group: "main", label: _t("Health & errors"), icon: "fa-heartbeat", manager: true },
            { id: "navigation", group: "analytics", label: _t("Navigation"), icon: "fa-compass", manager: false },
            { id: "activity", group: "analytics", label: _t("Activity log"), icon: "fa-list-alt", manager: false },
            { id: "models", group: "analytics", label: _t("Model analytics"), icon: "fa-cubes", manager: true },
            { id: "reports", group: "analytics", label: _t("Reports"), icon: "fa-bar-chart", manager: false },
        ];
    }
    visibleTabs(group) {
        const init = this.state.init;
        return this.allTabs.filter((t) => t.group === group && (!t.manager || (init && init.is_manager)));
    }
    get tabs() {
        return this.visibleTabs("main");
    }
    get analyticsTabs() {
        return this.visibleTabs("analytics");
    }
    get title() {
        const t = this.allTabs.find((x) => x.id === this.state.tab);
        return t ? t.label : "";
    }

    // ------------------------------------------------------------ header / filters
    get filterTabs() {
        return ["overview", "user", "fields", "navigation", "activity", "models", "reports"];
    }
    get showRange() {
        return this.filterTabs.includes(this.state.tab) || this.state.tab === "leaderboard";
    }
    get showUserFilter() {
        return !!(this.state.init && this.state.init.is_manager && this.filterTabs.includes(this.state.tab));
    }
    get showModelFilter() {
        return this.filterTabs.includes(this.state.tab);
    }
    get showGroupBy() {
        return this.state.tab === "reports";
    }
    get pdfEnabled() {
        return this.state.tab !== "health";
    }
    get scopeLabel() {
        const init = this.state.init;
        if (!init) {
            return "";
        }
        if (this.state.userId) {
            const user = init.users.find((u) => String(u.id) === this.state.userId);
            return user ? user.name : "";
        }
        return init.is_manager ? "All users (org)" : "My activity";
    }
    get subtitle() {
        const scope = this.scopeLabel;
        const texts = {
            overview: `Adoption health, activity and trends for ${scope}.`,
            leaderboard: "Employees ranked by adoption score and points for the month of the selected end date.",
            user: `How ${scope} uses Odoo: score, activity, field changes and time on records.`,
            fields: `Which fields ${scope} actually maintain, and which are neglected.`,
            health: "Is tracking working? Health checks, tracking errors and a self-test.",
            navigation: `Where ${scope} go in Odoo: screens, records, searches and sessions.`,
            activity: `Every successful create, update and delete by ${scope}, with old and new values.`,
            models: `How each Odoo model is created, updated and maintained for ${scope}.`,
            reports: "Filter by date, group by day / week / month, and compare periods. Every report downloads live data.",
        };
        return texts[this.state.tab] || "";
    }
    isUser(id) {
        return String(id) === this.state.userId;
    }

    setTab(id) {
        this.state.tab = id;
    }
    refresh() {
        this.state.rev++;
    }
    toggleTheme() {
        this.state.theme = this.state.theme === "dark" ? "light" : "dark";
        try {
            window.localStorage.setItem(THEME_KEY, this.state.theme);
        } catch {
            /* ignore */
        }
    }
    applyPreset(id) {
        const range = presetRange(id, this.state.init.today);
        if (range) {
            [this.state.from, this.state.to] = range;
            this.state.preset = id;
        }
    }
    onPreset(ev) {
        if (ev.target.value !== "custom") {
            this.applyPreset(ev.target.value);
        }
    }
    onDate(field, ev) {
        this.state[field] = ev.target.value;
        this.state.preset = detectPreset(this.state.from, this.state.to, this.state.init.today);
    }
    onGroupBy(ev) {
        this.state.groupBy = ev.target.value;
    }
    onUser(ev) {
        this.state.userId = ev.target.value;
    }
    onModel(ev) {
        this.state.model = ev.target.value;
    }
    selectModel(name) {
        this.state.model = name;
    }
    openUser(userId) {
        this.state.userId = String(userId);
        this.state.tab = "user";
    }

    /** Server-side PDF of whatever the current screen shows (same filters, same scoping). */
    downloadPdf() {
        const s = this.state;
        this.action.doAction({
            type: "ir.actions.report",
            report_type: "qweb-pdf",
            report_name: PDF_REPORT,
            report_file: PDF_REPORT,
            display_name: `Adoption ${this.title}`,
            context: {},
            data: {
                screen: s.tab, date_from: s.from, date_to: s.to, user_id: s.userId ? Number(s.userId) : false,
                model_name: s.model || false, granularity: s.groupBy, period_start: s.to,
            },
        });
    }
}

registry.category("actions").add("adoption_intelligence.dashboard", AdoptionDashboard);
