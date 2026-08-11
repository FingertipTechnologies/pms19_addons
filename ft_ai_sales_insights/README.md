# FT AI Sales Insights

AI-powered Sales & CRM analytics for Odoo 18. Sales managers filter CRM/Sales
data, the module aggregates it server-side, sends a compact summary to a
configurable AI provider, and renders executive-level insights in an OWL
dashboard.

---

## 1. Architecture

```
                        ┌─────────────────────────────────────────┐
   Browser (OWL)        │  AiSalesInsights (client action)         │
                        │   ├─ InsightKpi / InsightSection          │
                        │   └─ filters + result rendering           │
                        └───────────────┬──────────────────────────┘
                                        │ ORM RPC (get_filter_options / analyze)
                        ┌───────────────▼──────────────────────────┐
   Orchestrator (ORM)   │  ft.ai.sales.insights (TransientModel)    │
                        │   analyze():                              │
                        │     1 resolve config + purpose            │
                        │     2 compute date range                  │
                        │     3 collect data (as current user)      │
                        │     4 build prompt                        │
                        │     5 call AI                             │
                        │     6 log + return                        │
                        └───┬──────────┬───────────┬────────────┬──┘
                            │          │           │            │
             ┌──────────────▼──┐  ┌────▼──────┐ ┌──▼─────────┐ ┌▼───────────────┐
   Services  │ SalesData        │ │ Prompt    │ │ AIService  │ │ ft.ai.insights │
   (plain    │ Collector        │ │ Builder   │ │  (façade)  │ │ .log (audit)   │
   Python)   │ (read_group agg) │ └───────────┘ └─────┬──────┘ └────────────────┘
             └──────────────────┘                     │
                                         ┌─────────────▼──────────────┐
   Providers │  registry: PROVIDERS = { openai, claude, gemini,       │
             │             azure, ollama }  — all subclass AIProvider  │
             └─────────────────────────────────────────────────────────┘

   Config    ft.ai.insights.config (singleton) — provider/model/tuning/master prompt
             API key → ir.config_parameter (system-only)
   Purposes  ft.ai.insights.purpose (records) — editable per-purpose prompts
```

**Layering rule:** callers depend only on `AIService`. Providers depend only on
`base.AIProvider`. Prompt text lives in DB records, never in code.

---

## 2. Folder structure

```
ft_ai_sales_insights/
├── __manifest__.py
├── README.md
├── data/
│   ├── ai_config_data.xml          # default config + master prompt
│   └── ai_purpose_data.xml         # 23 default purposes (editable)
├── models/
│   ├── ai_config.py                # ft.ai.insights.config (singleton, secure key)
│   ├── ai_purpose.py               # ft.ai.insights.purpose (data-driven)
│   ├── ai_log.py                   # ft.ai.insights.log (audit + chatter)
│   └── sales_insights.py           # ft.ai.sales.insights (orchestrator/RPC)
├── services/                       # plain, unit-testable Python (no ORM base)
│   ├── ai_service.py               # AIService façade + PROVIDERS registry
│   ├── prompt_builder.py           # PromptBuilder + response contract
│   ├── data_collector.py           # SalesDataCollector (aggregation)
│   └── providers/
│       ├── base.py                 # AIProvider, AIResult, AIProviderError
│       ├── openai_provider.py      # OpenAI + AzureOpenAI
│       ├── claude_provider.py      # Anthropic
│       ├── gemini_provider.py      # Google Gemini
│       └── ollama_provider.py      # self-hosted
├── security/
│   ├── ai_insights_security.xml    # groups + record rules
│   └── ir.model.access.csv
├── static/src/{js,xml,scss}/       # OWL dashboard
└── views/                          # config / purpose / log / client action + menus
```

---

## 3. Sequence — one analysis

```
User        OWL            Orchestrator        Collector   PromptBuilder  AIService   Provider   Log
 │  Analyse  │                  │                   │            │            │          │        │
 │──────────▶│  analyze(filters)│                   │            │            │          │        │
 │           │─────────────────▶│                   │            │            │          │        │
 │           │                  │ _get_singleton()  │            │            │          │        │
 │           │                  │ _compute_date_range                        │          │        │
 │           │                  │ collect() ───────▶│ read_group │            │          │        │
 │           │                  │◀── payload ───────│ (as user)  │            │          │        │
 │           │                  │ build(payload) ───────────────▶│            │          │        │
 │           │                  │◀── messages ───────────────────│            │          │        │
 │           │                  │ generate(messages) ─────────────────────────▶│ POST ──▶│        │
 │           │                  │◀────────────────────────────── AIResult ─────│◀────────│        │
 │           │                  │ create(log) ───────────────────────────────────────────────────▶│
 │           │◀── result ───────│                   │            │            │          │        │
 │◀ render ──│                  │                   │            │            │          │        │
```

---

## 4. Data model relationships

```
res.users ─┐
           ├─< ft.ai.insights.log >── ft.ai.insights.purpose
crm.team   │        (audit)                    │
           │                                    │ default_purpose_id
res.partner│                     ft.ai.insights.config ─┘  (singleton)
crm.stage ─┘   (filter sources, read-only)

ft.ai.sales.insights  → TransientModel, no storage (pure orchestration)
API key               → ir.config_parameter 'ft_ai_sales_insights.api_key.<provider>'
```

---

## 5. Security

| Group | Can |
|---|---|
| **AI Insights / User** (implies Salesperson) | run analyses, read own logs |
| **AI Insights / Manager** | edit config & purposes, see all logs |

* **Record-rule isolation** — non-managers only read their own `ft.ai.insights.log` rows.
* **Data access** — `SalesDataCollector` runs as the current user, so CRM/Sales
  record rules are enforced; users can only analyse data they may see.
* **Secrets** — API keys live in `ir.config_parameter` (system-only), never in a
  business table; the config form field is a proxy that writes to the parameter.
* **Audit without PII** — logs store metadata + aggregated response; the raw
  aggregated payload is stored only when **Debug Mode** is on.

---

## 6. Step-by-step setup

1. Install the module (`-i ft_ai_sales_insights`).
2. Go to **AI Insights → Configuration → Settings**.
3. Pick a **Provider** (OpenAI/Claude/Gemini/Azure/Ollama), set **Model** and
   **API Key** (Azure/Ollama also need **API Base URL**).
4. Click **Test Connection**.
5. (Optional) tune Temperature / Max Tokens / Master Prompt, and edit
   **Purposes** prompts under Configuration → Purposes.
6. Open **AI Insights → Sales Insights**, choose filters + a purpose, **Analyse**.

### Provider quick reference

| Provider | Model example | Base URL | Key |
|---|---|---|---|
| OpenAI | `gpt-4o-mini` | default | required |
| Claude | `claude-sonnet-5` | default | required |
| Gemini | `gemini-1.5-flash` | default | required |
| Azure OpenAI | your deployment | `https://<res>.openai.azure.com/openai/deployments/<dep>` | required |
| Ollama | `llama3.1` | `http://localhost:11434` | none |

---

## 7. Adding a new provider (no business-logic change)

1. Create `services/providers/foo_provider.py` subclassing `AIProvider`,
   implement `generate()` returning an `AIResult`.
2. Add the class to `PROVIDERS` in `services/ai_service.py`.

That's it — it appears in the config Provider dropdown automatically
(`provider_selection()` reads the registry).

## Adding a new purpose

Create a record under **Configuration → Purposes** (name, code, prompt). No code.

---

## 8. Performance

* Every section uses `read_group` **aggregation** — payload size is independent
  of DB size. List sections are capped at `TOP_N = 10` (`data_collector.py`).
* One AI round-trip per analysis; `max_tokens` bounds the response.
* The orchestrator is a `TransientModel` (no persistence overhead).

---

## 9. Production deployment

* Set API keys via `ir.config_parameter` (already the case) and restrict the
  Manager group tightly.
* Turn **Debug Mode off** in production (avoids storing payloads).
* Put outbound HTTPS egress rules in place for the provider endpoint.
* Consider a per-user/day rate cap (extend `analyze` with a counted check
  against `ft.ai.insights.log`).
* Monitor `ft.ai.insights.log` for cost (token sums) and error rate.
* `requests` timeout is configurable; keep workers' `limit_time_real` above it.

---

## 10. Future enhancements (architecture already supports)

* Lead scoring / opportunity health / close-probability models — add a service
  + purpose; reuse `SalesDataCollector`.
* Scheduled weekly executive reports via `ir.cron` calling `analyze` and
  emailing / posting to Discuss (log already has chatter).
* Next-best-action, follow-up/quotation drafting — new purposes + a write-back
  service.
* Conversational assistant ("which deals need attention?") — a thin controller
  that maps a question to a purpose + filters, then calls `analyze`.
* Churn/upsell prediction — plug an ML provider behind the same `AIProvider`
  interface.
```
