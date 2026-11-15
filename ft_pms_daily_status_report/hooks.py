def post_init_hook(env):
    """Align the daily cron's next run with the main company's send hour
    (company time zone) right after install."""
    company = env.ref('base.main_company', raise_if_not_found=False) or env.company
    company._ft_daily_report_reschedule_cron()
