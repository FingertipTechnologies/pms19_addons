{
    'name': 'FT AI Sales Insights',
    # 1.1.0 adds AI Project Insights + re-aims milestones at billing.
    # The bump also triggers migrations/18.0.1.1.0, which refreshes the
    # noupdate-protected project purposes.
    'version': '19.0.1.1.0',
    'category': 'Sales/CRM',
    'summary': 'AI-powered Sales & CRM analytics — configurable prompts, pluggable AI providers (OpenAI/Claude/Gemini/Azure/Ollama).',
    'description': """
FT AI Sales Insights
====================
An AI-powered Sales Analytics component for Odoo 18.

Sales managers and executives filter CRM/Sales data, send an *aggregated*
summary to an AI provider, and receive executive-level insights and
recommendations rendered in a modern OWL dashboard.

Key design points
------------------
* **Data-driven purposes** — each analysis "purpose" is a record with its own
  editable prompt, so new analyses need no code change.
* **Pluggable AI layer** — a provider registry (OpenAI, Claude, Gemini, Azure
  OpenAI, Ollama) behind a single ``AIService`` façade; adding a provider needs
  no business-logic change.
* **Privacy & security** — data is collected as the current user (record rules
  enforced), aggregated before it leaves the server, API keys live in system
  parameters, and every request is audited.
""",
    'author': 'Fingertip',
    'website': '',
    'depends': [
        'base',
        'mail',
        'crm',
        'sale_management',
        # Project Insights reads projects, tasks, timesheets and employees.
        'project',
        'hr_timesheet',
        # Owns the shared stage-based definition of a completed/open task
        # (project.task._ft_delivery_domain / _ft_open_domain), which the
        # collector calls so its counts match the project fields and the PMS
        # dashboard. Reached transitively via ft_project_dashboard, but this
        # module uses the API directly, so the dependency is declared here.
        'bt_project_customization',
        # Extended (AI Summary button injected into its dashboard). Keeping the
        # dependency here means all AI code lives in this module.
        'ft_project_dashboard',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'data': [
        'security/ai_insights_security.xml',
        'security/ir.model.access.csv',
        'data/ai_purpose_data.xml',
        'data/ai_config_data.xml',
        'views/ai_config_views.xml',
        'views/ai_purpose_views.xml',
        'views/ai_log_views.xml',
        'views/ai_insights_action.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_ai_sales_insights/static/src/scss/ai_sales_insights.scss',
            'ft_ai_sales_insights/static/src/scss/blocks.scss',
            'ft_ai_sales_insights/static/src/js/insight_sections.js',
            'ft_ai_sales_insights/static/src/js/block_renderer.js',
            'ft_ai_sales_insights/static/src/js/ai_sales_insights.js',
            'ft_ai_sales_insights/static/src/xml/ai_sales_insights.xml',
            'ft_ai_sales_insights/static/src/xml/blocks.xml',
            # AI Project Insights — reuses the components + styling above.
            'ft_ai_sales_insights/static/src/js/ai_project_insights.js',
            'ft_ai_sales_insights/static/src/xml/ai_project_insights.xml',
            # AI Summary injected into the Project Dashboard.
            'ft_ai_sales_insights/static/src/scss/project_dashboard_ai.scss',
            'ft_ai_sales_insights/static/src/js/project_dashboard_ai.js',
            'ft_ai_sales_insights/static/src/xml/project_dashboard_ai.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
