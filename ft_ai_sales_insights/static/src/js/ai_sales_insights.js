/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { browser } from "@web/core/browser/browser";
import { loadJS } from "@web/core/assets";
import { InsightKpi, InsightSection } from "./insight_sections";
import { BlockRenderer } from "./block_renderer";

const MODEL = "ft.ai.sales.insights";

// The breadcrumb restores props.state, but browser Back rebuilds the action from
// the URL with no exported state. Mirror the filters into sessionStorage so both
// routes return to the same selection. The result itself is deliberately NOT
// stored — a stale analysis reappearing on a fresh open would be misleading.
const FILTER_KEY = "ft_ai_sales_insights.filters";

function readStoredFilters() {
    try {
        return JSON.parse(browser.sessionStorage.getItem(FILTER_KEY) || "null");
    } catch {
        return null;
    }
}

function writeStoredFilters(filters) {
    try {
        browser.sessionStorage.setItem(FILTER_KEY, JSON.stringify(filters));
    } catch {
        // Storage unavailable/full: filters just won't persist.
    }
}

export class AiSalesInsights extends Component {
    static template = "ft_ai_sales_insights.AiSalesInsights";
    static components = { InsightKpi, InsightSection, BlockRenderer };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        // Restored by the action manager when returning through the breadcrumb
        // (e.g. back from a KPI drill-down). Keeping the result too means the
        // round trip costs no extra tokens.
        const restored = this.props.state || { filters: readStoredFilters() };
        // Restoring from storage has no query text, so rebuild it from the
        // chosen customer; otherwise the box would look empty while filtered.
        const rf = restored?.filters;
        const customerQuery =
            restored?.customerQuery ??
            (rf?.partner_id && rf.partner_id !== "all" ? rf.partner_label : "");
        this.state = useState({
            options: null,
            loadingOptions: true,
            analyzing: false,
            error: null,
            result: restored?.result || null,
            customerQuery: customerQuery || "",
            customerResults: [],
            filters: restored?.filters
                ? { ...restored.filters }
                : {
                      date_filter: "this_month",
                      date_from: null,
                      date_to: null,
                      team_id: "all",
                      team_label: "All Teams",
                      user_id: "all",
                      user_label: "All Salespersons",
                      partner_id: "all",
                      partner_label: "All Customers",
                      stage_id: "all",
                      stage_label: "All Stages",
                      purpose_id: null,
                      purpose_label: null,
                  },
        });

        useSetupAction({
            getLocalState: () => ({
                filters: { ...this.state.filters },
                result: this.state.result,
                customerQuery: this.state.customerQuery,
            }),
        });

        onWillStart(async () => {
            // Chart.js backs the AI-chosen chart blocks. Loaded once up front so
            // a chart never mounts before the library is available.
            await loadJS("/web/static/lib/Chart/Chart.js");
            const opts = await this.orm.call(MODEL, "get_filter_options", []);
            this.state.options = opts;
            // A restored view already has its purpose; don't overwrite it.
            if (!this.state.filters.purpose_id) {
                const def = opts.default_purpose_id;
                const purposes = opts.purposes || [];
                const chosen = purposes.find((p) => p.id === def) || purposes[0] || null;
                if (chosen) {
                    this.state.filters.purpose_id = chosen.id;
                    this.state.filters.purpose_label = chosen.name;
                }
            }
            this.state.loadingOptions = false;
        });
    }

    // ---- Filter handlers ------------------------------------------------
    get f() {
        return this.state.filters;
    }
    get showCustom() {
        return this.f.date_filter === "custom";
    }

    onDateFilter(ev) {
        this.f.date_filter = ev.target.value;
    }
    onCustomDate(field, ev) {
        this.f[field] = ev.target.value || null;
    }
    _labelFor(list, id, allLabel) {
        if (id === "all") return allLabel;
        const rec = (list || []).find((r) => String(r.id) === String(id));
        return rec ? rec.name : allLabel;
    }
    onTeam(ev) {
        this.f.team_id = ev.target.value;
        this.f.team_label = this._labelFor(this.state.options.teams, ev.target.value, "All Teams");
    }
    onUser(ev) {
        this.f.user_id = ev.target.value;
        this.f.user_label = this._labelFor(this.state.options.salespersons, ev.target.value, "All Salespersons");
    }
    onStage(ev) {
        this.f.stage_id = ev.target.value;
        this.f.stage_label = this._labelFor(this.state.options.stages, ev.target.value, "All Stages");
    }
    onPurpose(ev) {
        this.f.purpose_id = Number(ev.target.value);
        this.f.purpose_label = this._labelFor(this.state.options.purposes, ev.target.value, null);
    }

    // ---- Customer autocomplete -----------------------------------------
    async onCustomerInput(ev) {
        const q = ev.target.value;
        this.state.customerQuery = q;
        if (!q) {
            this.state.customerResults = [];
            this.f.partner_id = "all";
            this.f.partner_label = "All Customers";
            return;
        }
        this.state.customerResults = await this.orm.call(MODEL, "search_customers", [q, 15]);
    }
    pickCustomer(c) {
        this.f.partner_id = c.id;
        this.f.partner_label = c.name;
        this.state.customerQuery = c.name;
        this.state.customerResults = [];
    }
    clearCustomer() {
        this.f.partner_id = "all";
        this.f.partner_label = "All Customers";
        this.state.customerQuery = "";
        this.state.customerResults = [];
    }

    // ---- Analysis -------------------------------------------------------
    get canAnalyze() {
        return !this.state.analyzing && this.f.purpose_id && this.state.options?.configured;
    }

    async analyze() {
        if (this.state.analyzing) return;
        // Persist what was actually analysed, so a drill-down and back returns
        // to the same selection.
        writeStoredFilters({ ...this.f });
        this.state.analyzing = true;
        this.state.error = null;
        try {
            const res = await this.orm.call(MODEL, "analyze", [{ ...this.f }]);
            this.state.result = res;
        } catch (e) {
            this.state.error = e?.data?.message || e?.message || "Analysis failed.";
        } finally {
            this.state.analyzing = false;
        }
    }
    async regenerate() {
        await this.analyze();
    }

    // ---- Result getters -------------------------------------------------
    get insight() {
        return this.state.result?.insight || null;
    }

    // The AI-chosen layout blocks, if any. When empty the template falls back to
    // the fixed KPI/section/card view, so older purposes render unchanged.
    get layout() {
        const blocks = this.insight?.layout;
        return Array.isArray(blocks) ? blocks : [];
    }
    get meta() {
        return this.state.result?.meta || {};
    }
    get rawText() {
        return this.state.result?.raw_text || null;
    }
    get scoreStyle() {
        const s = Math.max(0, Math.min(100, this.insight?.overall_score ?? 0));
        const hue = Math.round((s / 100) * 120); // red -> green
        return `--aisi-score:${s}%; --aisi-score-color:hsl(${hue},70%,45%);`;
    }
    get actionsByPriority() {
        const rank = { high: 0, medium: 1, low: 2 };
        return [...(this.insight?.recommended_actions || [])].sort(
            (a, b) => (rank[a.priority] ?? 3) - (rank[b.priority] ?? 3)
        );
    }

    // ---- Output actions -------------------------------------------------
    _plainText() {
        const i = this.insight;
        if (!i) return this.rawText || "";
        const lines = [];
        if (i.executive_summary) lines.push(i.executive_summary, "");
        if (i.overall_score != null) lines.push(`Overall score: ${i.overall_score} (${i.score_label || ""})`, "");
        (i.kpis || []).forEach((k) => lines.push(`- ${k.label}: ${k.value}`));
        (i.sections || []).forEach((s) => {
            lines.push("", s.title || "");
            if (s.body) lines.push(s.body);
            (s.items || []).forEach((it) => lines.push(`  • ${it}`));
        });
        (this.actionsByPriority || []).forEach((a) =>
            lines.push(`[${(a.priority || "").toUpperCase()}] ${a.action}`)
        );
        return lines.join("\n");
    }

    async copyResponse() {
        try {
            await navigator.clipboard.writeText(this._plainText());
            this.notification.add("Insight copied to clipboard.", { type: "success" });
        } catch {
            this.notification.add("Could not access clipboard.", { type: "warning" });
        }
    }

    exportCsv() {
        const i = this.insight;
        if (!i) return;
        const rows = [["Type", "Label", "Value"]];
        (i.kpis || []).forEach((k) => rows.push(["KPI", k.label, k.value]));
        (i.recommended_actions || []).forEach((a) =>
            rows.push(["Action", a.priority || "", a.action || ""])
        );
        (i.at_risk_deals || []).forEach((d) =>
            rows.push(["At-Risk", d.name || "", `${d.amount || ""} — ${d.reason || ""}`])
        );
        const csv = rows
            .map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(","))
            .join("\n");
        const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `ai-sales-insight-${this.meta.log_id || "export"}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    printPdf() {
        window.print();
    }

    async saveToChatter() {
        if (!this.meta.log_id) return;
        await this.orm.call(MODEL, "save_to_chatter", [this.meta.log_id]);
        this.notification.add("Saved to the request log's chatter.", { type: "success" });
    }
}

registry.category("actions").add("ft_ai_sales_insights", AiSalesInsights);
