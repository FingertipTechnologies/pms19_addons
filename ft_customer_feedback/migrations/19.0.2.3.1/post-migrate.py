# -*- coding: utf-8 -*-
"""Remove the daily "Synchronise Request Status" cron introduced in
19.0.2.3.0: email statuses are now updated by the mail queue when it sends
the email. The record was ``noupdate``, so dropping it from the XML data does
not delete it on an existing database."""
from odoo import SUPERUSER_ID, api

CRON_XMLID = "ft_customer_feedback.cron_sync_feedback_request_states"


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(CRON_XMLID, raise_if_not_found=False)
    if cron:
        cron.sudo().unlink()
    env["ir.model.data"].sudo().search([
        ("module", "=", "ft_customer_feedback"),
        ("name", "=", "cron_sync_feedback_request_states"),
    ]).unlink()
