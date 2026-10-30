# -*- coding: utf-8 -*-
"""Monthly customer feedback requests.

One ``ft.feedback.request`` per project and calendar month, with one
``ft.feedback.request.recipient`` per customer contact. Each recipient has an
independent state per channel, so a channel that was sent is never sent again
and only failed channels are retried.

This module only sends by email. Other channels (e.g. WhatsApp in
``ft_customer_feedback_whatsapp``) plug in by extending, on the recipient:
``_ft_send_channels`` (send), ``_ft_channel_states`` (states used by the
request status), ``_ft_channel_done_states``, ``_ft_sync_channel_states`` and
``_ft_cron_sync_channel_states`` (asynchronous status synchronisation).
The email status of a recipient is updated by the mail queue itself when it
sends the email (``mail_mail.py``).
"""
import logging
import uuid
from datetime import date, datetime, timedelta

import pytz
from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import email_normalize

_logger = logging.getLogger(__name__)

DEFAULT_TZ = "Asia/Kolkata"
MANAGER_GROUPS = (
    "ft_customer_feedback.group_feedback_manager",
    "base.group_system",
)
START_MONTH_PARAM = "ft_customer_feedback.monthly_start_month"
EMAIL_TEMPLATE_XMLID = "ft_customer_feedback.mail_template_monthly_feedback_request"
RECIPIENT_MODEL = "ft.feedback.request.recipient"

EMAIL_STATES = [
    ("pending", "Pending"),
    ("queued", "Queued"),
    ("sent", "Sent"),
    ("failed", "Failed"),
    ("skipped", "Skipped"),
]
# Email channel states that count as "went out" for the request state.
EMAIL_DONE_STATES = ("queued", "sent")


# ----------------------------------------------------------------------
# Pure calendar helpers (copied from ft_amc_monthly_timesheet.periods so
# this module does not depend on it).
# ----------------------------------------------------------------------
def month_start(value):
    """First day of the month of ``value``."""
    return value.replace(day=1)


def month_end(value):
    """Last day of the month of ``value``."""
    first_next = date(value.year + (value.month == 12), value.month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def previous_month(today):
    """(first day, last day) of the calendar month before ``today``."""
    end = month_start(today) - timedelta(days=1)
    return month_start(end), end


def _new_token():
    return str(uuid.uuid4())


class FeedbackRequest(models.Model):
    _name = "ft.feedback.request"
    _description = "Monthly Customer Feedback Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_start desc, project_id, id desc"

    _project_period_unique = models.Constraint(
        "UNIQUE(project_id, period_start)",
        "A feedback request already exists for this project and month.",
    )
    _access_token_unique = models.Constraint(
        "UNIQUE(access_token)",
        "The feedback link token must be unique.",
    )

    name = fields.Char(compute="_compute_name", store=True, readonly=True)
    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        index=True,
        help="Commercial partner of the project customer when the request "
        "was created.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    period_start = fields.Date(string="Month Start", required=True, index=True)
    period_end = fields.Date(string="Month End")
    period_label = fields.Char(
        string="Feedback Month", compute="_compute_period_label", store=True
    )
    access_token = fields.Char(
        required=True,
        copy=False,
        index=True,
        readonly=True,
        # Odoo calls a field default with the model as argument.
        default=lambda self: _new_token(),
    )
    feedback_url = fields.Char(
        string="Feedback Link",
        compute="_compute_feedback_url",
        compute_sudo=True,
        help="Project-specific link sent to the feedback contacts.",
    )
    recipient_ids = fields.One2many(
        "ft.feedback.request.recipient", "request_id", string="Recipients"
    )
    response_ids = fields.One2many(
        "ft.feedback.response", "request_id", string="Responses"
    )
    response_count = fields.Integer(compute="_compute_response_count")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("sent", "Sent"),
            ("partial", "Partially Sent"),
            ("failed", "Failed"),
            ("done", "Done"),
        ],
        compute="_compute_state",
        store=True,
        default="draft",
        tracking=True,
    )
    last_run = fields.Datetime(string="Last Send Attempt", readonly=True)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends("period_start")
    def _compute_period_label(self):
        for request in self:
            request.period_label = (
                request.period_start.strftime("%B %Y")
                if request.period_start
                else False
            )

    @api.depends("period_label", "project_id.name")
    def _compute_name(self):
        for request in self:
            request.name = self.env._(
                "Feedback %(month)s – %(project)s",
                month=request.period_label or "",
                project=request.project_id.name or "",
            )

    @api.depends("access_token")
    def _compute_feedback_url(self):
        for request in self:
            if request.access_token:
                request.feedback_url = "%s/my/feedback?request=%s" % (
                    request.get_base_url().rstrip("/"),
                    request.access_token,
                )
            else:
                request.feedback_url = False

    def _compute_response_count(self):
        data = self.env["ft.feedback.response"].sudo()._read_group(
            [("request_id", "in", self.ids)], ["request_id"], ["__count"]
        )
        counts = {request.id: count for request, count in data}
        for request in self:
            request.response_count = counts.get(request.id, 0)

    # Channel modules add their state field to the dependencies by
    # overriding this method with their own @api.depends and calling super().
    @api.depends(
        "recipient_ids.email_state",
        "recipient_ids.response_id",
    )
    def _compute_state(self):
        for request in self:
            recipients = request.recipient_ids
            if not recipients:
                request.state = "draft"
                continue
            if all(recipient.response_id for recipient in recipients):
                request.state = "done"
                continue
            done_states = recipients._ft_channel_done_states()
            went_out = failed = pending = 0
            for recipient in recipients:
                for state in recipient._ft_channel_states():
                    if state == "skipped":
                        continue
                    if state in done_states:
                        went_out += 1
                    elif state == "failed":
                        failed += 1
                    else:
                        pending += 1
            if went_out and not failed and not pending:
                request.state = "sent"
            elif went_out:
                request.state = "partial"
            elif failed or not pending:
                # Every channel failed, or every channel was skipped
                # (nothing could be sent to anybody).
                request.state = "failed"
            else:
                request.state = "draft"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @api.model
    def _check_manager(self):
        if self.env.su:
            return
        user = self.env.user
        if not any(user.has_group(group) for group in MANAGER_GROUPS):
            raise AccessError(_(
                "Only Customer Feedback Managers can send feedback requests."
            ))

    @api.model
    def _company_tz(self, company):
        return company.partner_id.tz or DEFAULT_TZ

    @api.model
    def _local_today(self, company):
        return datetime.now(pytz.timezone(self._company_tz(company))).date()

    @api.model
    def _ft_start_month(self):
        """First month for which requests may be created (ICP), or None."""
        raw = self.env["ir.config_parameter"].sudo().get_param(START_MONTH_PARAM)
        if not raw:
            return None
        try:
            return month_start(fields.Date.to_date(raw.strip()))
        except (ValueError, TypeError):
            _logger.warning(
                "Invalid %s parameter %r: ignored.", START_MONTH_PARAM, raw
            )
            return None

    @api.model
    def _get_or_create(self, project, period_start):
        """The request of ``project`` for the month starting ``period_start``."""
        period_start = month_start(period_start)
        domain = [
            ("project_id", "=", project.id),
            ("period_start", "=", period_start),
        ]
        request = self.search(domain, limit=1)
        if request:
            return request
        try:
            with self.env.cr.savepoint():
                return self.create({
                    "project_id": project.id,
                    "partner_id": project.partner_id.commercial_partner_id.id,
                    "company_id": (project.company_id or self.env.company).id,
                    "period_start": period_start,
                    "period_end": month_end(period_start),
                })
        except IntegrityError:
            # Created concurrently (another cron worker / user click).
            return self.search(domain, limit=1)

    def _sync_recipients(self):
        """Create the missing recipient rows from the project's feedback
        contacts. Existing rows are never deleted (their history is kept)."""
        Recipient = self.env[RECIPIENT_MODEL].sudo()
        for request in self:
            existing = request.recipient_ids.partner_id
            to_add = request.project_id.ft_feedback_contact_ids - existing
            for partner in to_add:
                try:
                    with self.env.cr.savepoint():
                        Recipient.create({
                            "request_id": request.id,
                            "partner_id": partner.id,
                            "email": partner.email or False,
                        })
                except IntegrityError:
                    # Created concurrently: unique (request, partner).
                    _logger.info(
                        "Feedback recipient %s already exists on request %s.",
                        partner.id, request.id,
                    )
            request.invalidate_recordset(["recipient_ids"])

    def _has_pending_channels(self):
        return any(
            "pending" in recipient._ft_channel_states()
            for recipient in self.recipient_ids
        )

    def _send_pending(self, retry_failed=False):
        """Send every channel still ``pending`` (and ``failed`` ones when
        ``retry_failed``). Channels already sent / queued / skipped (or
        delivered / read for other channels) are never sent again. Never raises for a recipient error:
        failures are stored on the recipient row."""
        for request in self:
            request._sync_recipients()
            for recipient in request.recipient_ids:
                recipient._ft_send_channels(retry_failed=retry_failed)
            request.last_run = fields.Datetime.now()
        return True

    # ------------------------------------------------------------------
    # buttons
    # ------------------------------------------------------------------
    def action_send_now(self):
        self._check_manager()
        requests = self.sudo()
        requests.recipient_ids._ft_sync_channel_states()
        requests._send_pending(retry_failed=False)
        return True

    def action_retry_failed(self):
        self._check_manager()
        requests = self.sudo()
        requests.recipient_ids._ft_sync_channel_states()
        requests._send_pending(retry_failed=True)
        return True

    def action_view_responses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Feedback Responses"),
            "res_model": "ft.feedback.response",
            "view_mode": "list,form",
            "domain": [("request_id", "=", self.id)],
            "context": {"default_request_id": self.id, "create": False},
        }

    # ------------------------------------------------------------------
    # cron
    # ------------------------------------------------------------------
    @api.model
    def _ft_commit_progress(self):
        """Commit after each request when running inside the real cron, so a
        message already sent is never rolled back (and resent)."""
        if self.env.context.get("ir_cron_progress_id"):
            self.env["ir.cron"]._commit_progress(1)

    @api.model
    def _cron_monthly_feedback_requests(self):
        """1st of every month: make sure every enabled active customer
        project has its request for the previous month and send what is
        still pending.

        A missed 1st (scheduler down) is caught up by Odoo as soon as the
        scheduler is back, and a manual run on a later day sends the same
        previous month; duplicates are impossible (unique request per
        project+month, unique recipient per request+contact and per-channel
        states). Email statuses are updated by the mail queue when it sends
        the email (``mail.mail._postprocess_sent_message``); this cron only
        re-synchronises leftovers before sending."""
        Request = self.sudo()
        Recipient = self.env[RECIPIENT_MODEL].sudo()
        try:
            Recipient._ft_cron_sync_channel_states()
        except Exception:  # noqa: BLE001 - status sync must not block sending
            _logger.exception("Feedback request status synchronisation failed")

        Project = self.env["project.project"].sudo()
        default_company = self.env.ref("base.main_company", raise_if_not_found=False)
        start_month = Request._ft_start_month()
        for company in self.env["res.company"].sudo().search([]):
            period_start, _period_end = previous_month(Request._local_today(company))
            if start_month and period_start < start_month:
                continue
            company_domain = [("company_id", "=", company.id)]
            if company == default_company:
                # Projects without a company are handled by the main company.
                company_domain = [
                    "|", ("company_id", "=", company.id), ("company_id", "=", False),
                ]
            projects = Project.search([
                ("active", "=", True),
                ("ft_feedback_monthly_enabled", "=", True),
                ("partner_id", "!=", False),
            ] + company_domain, order="id")
            for project in projects:
                try:
                    if not project._ft_feedback_is_active_customer_project():
                        continue
                    with self.env.cr.savepoint():
                        request = Request.with_company(company)._get_or_create(
                            project, period_start
                        )
                        request._sync_recipients()
                    if not request._has_pending_channels():
                        continue
                    request._send_pending(retry_failed=False)
                except Exception:  # noqa: BLE001 - one project must not block the others
                    _logger.exception(
                        "Monthly feedback request failed for project %s (%s)",
                        project.id, project.name,
                    )
                Request._ft_commit_progress()


class FeedbackRequestRecipient(models.Model):
    _name = RECIPIENT_MODEL
    _description = "Monthly Customer Feedback Request Recipient"
    # mail.thread: chatter on the recipient, and lets channel modules post
    # messages (e.g. WhatsApp templates) on the recipient.
    _inherit = ["mail.thread"]
    _order = "request_id desc, id"

    _request_partner_unique = models.Constraint(
        "UNIQUE(request_id, partner_id)",
        "This contact is already a recipient of the feedback request.",
    )

    request_id = fields.Many2one(
        "ft.feedback.request",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner", string="Contact", required=True, index=True
    )
    company_id = fields.Many2one(
        related="request_id.company_id", store=True, index=True
    )
    project_id = fields.Many2one(
        related="request_id.project_id", store=True, string="Project"
    )
    period_label = fields.Char(
        related="request_id.period_label", string="Feedback Month"
    )
    feedback_url = fields.Char(
        related="request_id.feedback_url", string="Feedback Link"
    )

    # Email channel
    email = fields.Char(help="Email address used for the request.")
    email_state = fields.Selection(
        EMAIL_STATES, default="pending", required=True, copy=False
    )
    email_error = fields.Text(copy=False)
    mail_id = fields.Many2one("mail.mail", ondelete="set null", copy=False)
    email_sent_on = fields.Datetime(copy=False)

    response_id = fields.Many2one(
        "ft.feedback.response",
        string="Response",
        ondelete="set null",
        copy=False,
        help="Feedback submitted by this contact for the request.",
    )

    @api.depends("partner_id", "request_id")
    def _compute_display_name(self):
        for recipient in self:
            recipient.display_name = "%s - %s" % (
                recipient.request_id.display_name or "",
                recipient.partner_id.display_name or "",
            )

    # ------------------------------------------------------------------
    # channel extension points
    # ------------------------------------------------------------------
    def _ft_channel_states(self):
        """States of every channel of this recipient (list of strings), used
        by the request status and the "has pending channels" check. Channel
        modules append their own state, e.g. ``whatsapp_state``."""
        self.ensure_one()
        return [self.email_state]

    @api.model
    def _ft_channel_done_states(self):
        """Channel states meaning "the message went out". Channel modules add
        theirs (states are shared: pending / failed / skipped mean the same
        on every channel)."""
        return set(EMAIL_DONE_STATES)

    def _ft_sync_channel_states(self):
        """Pick up asynchronous outcomes of the channels of these recipients."""
        self._ft_sync_email_states()

    @api.model
    def _ft_cron_sync_channel_states(self):
        """Start of the monthly cron: synchronise every channel still
        waiting for an outcome."""
        self.sudo().search([("email_state", "=", "queued")])._ft_sync_email_states()

    # ------------------------------------------------------------------
    # sending
    # ------------------------------------------------------------------
    def _ft_send_channels(self, retry_failed=False):
        """Send the channels of each recipient that still need it. Errors are
        recorded on the recipient, never raised. Channel modules override it,
        call super() and send their channel with ``_ft_send_channel``."""
        for recipient in self:
            recipient._ft_send_channel(
                "email", "email_state", "email_error",
                recipient._ft_send_email, retry_failed=retry_failed,
            )

    def _ft_send_channel(self, channel, state_field, error_field, method,
                         retry_failed=False):
        """Run ``method`` (send one channel) when the channel state is
        ``pending`` (or ``failed`` with ``retry_failed``), inside a savepoint;
        an exception marks the channel failed with the error."""
        self.ensure_one()
        states = ("pending", "failed") if retry_failed else ("pending",)
        if self[state_field] not in states:
            return
        try:
            with self.env.cr.savepoint():
                method()
        except Exception as exc:  # noqa: BLE001 - recorded on the row
            _logger.exception(
                "Feedback %s request to %s (recipient %s) failed",
                channel, self.partner_id.display_name, self.id,
            )
            self.write({
                state_field: "failed",
                error_field: str(exc) or exc.__class__.__name__,
            })

    # -- email ---------------------------------------------------------
    def _ft_send_email(self):
        self.ensure_one()
        partner = self.partner_id
        # Current contact address first, else the address snapshot of the row.
        if email_normalize(partner.email or ""):
            email = partner.email
        elif email_normalize(self.email or ""):
            email = self.email
        else:
            email = False
        if not email:
            self.write({
                "email_state": "skipped",
                "email_error": _("The contact has no valid email address."),
            })
            return
        template = self.env.ref(EMAIL_TEMPLATE_XMLID, raise_if_not_found=False)
        if not template:
            raise UserError(_("The feedback request email template is missing."))
        # A previous failed attempt must not be retried from the mail queue too.
        old_mail = self.mail_id.sudo()
        if old_mail and old_mail.state == "exception":
            old_mail.cancel()
        self.write({"email": email})
        # Queued (no force_send): a rollback discards the email as well.
        mail_id = template.sudo().send_mail(
            self.id,
            force_send=False,
            email_values={
                "auto_delete": False,
                "email_to": self.email,
                "recipient_ids": [],
            },
        )
        self.write({
            "email_state": "queued",
            "email_error": False,
            "mail_id": mail_id,
            "email_sent_on": False,
        })

    def _ft_sync_email_states(self):
        """Update queued email channels from their outgoing mail.mail."""
        for recipient in self.filtered(lambda r: r.email_state == "queued"):
            mail = recipient.mail_id.sudo()
            if not mail.exists():
                # Deleted after sending: delivered.
                recipient.write({
                    "email_state": "sent",
                    "email_sent_on": recipient.email_sent_on or fields.Datetime.now(),
                })
            elif mail.state in ("sent", "received"):
                recipient.write({
                    "email_state": "sent",
                    "email_sent_on": mail.write_date,
                    "email_error": False,
                })
            elif mail.state == "exception":
                recipient.write({
                    "email_state": "failed",
                    "email_error": mail.failure_reason
                    or _("The email could not be sent."),
                })
            elif mail.state == "cancel":
                recipient.write({
                    "email_state": "failed",
                    "email_error": _("The email was cancelled before being sent."),
                })
