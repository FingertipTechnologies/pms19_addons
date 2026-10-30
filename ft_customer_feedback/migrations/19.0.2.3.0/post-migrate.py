# -*- coding: utf-8 -*-
"""Switch the monthly feedback request cron from daily to the 1st of every
month. The cron record is ``noupdate``, so the XML data does not change it on
an existing database."""
from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import SUPERUSER_ID, api

CRON_XMLID = "ft_customer_feedback.cron_monthly_feedback_requests"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if not cron:
        return
    # 1st of next month, 03:30 UTC (09:00 Asia/Kolkata); same as the XML.
    nextcall = (datetime.utcnow() + relativedelta(day=1, months=1)).replace(
        hour=3, minute=30, second=0, microsecond=0
    )
    cron.sudo().write({
        "interval_number": 1,
        "interval_type": "months",
        "nextcall": nextcall,
        "active": True,
    })
