# -*- coding: utf-8 -*-
import hmac
import logging

from odoo import http, _
from odoo.exceptions import ValidationError
from odoo.http import request
from odoo.addons.ft_helpdesk_portal.controllers.portal import HelpdeskPortal
from uuid import uuid4, UUID
from psycopg2.errors import UniqueViolation

from ..models.res_config_settings import (
    INTRO_PARAM,
    THANKS_PARAM,
    DEFAULT_INTRO,
    DEFAULT_THANKS,
)

_logger = logging.getLogger(__name__)

# Form field name prefix; the question id follows it (q_12).
FIELD_PREFIX = "q_"

# Name of the query/form parameter carrying a monthly request's token.
REQUEST_PARAM = "request"
# access_token values are uuid4 strings; anything longer is never valid.
REQUEST_TOKEN_MAX_LEN = 128


class CustomerFeedbackPortal(HelpdeskPortal):
    """Portal 'Feedback' tab: renders the configured questions and stores
    the answers as one ft.feedback.response per submission."""

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _feedback_grouped_questions(self, questions):
        """Return [(section_or_False, [questions])] keeping portal order.
        Questions without a section come first under no heading."""
        groups = []
        for question in questions:
            section = question.section_id or False
            if groups and groups[-1][0] == section:
                groups[-1][1].append(question)
            else:
                groups.append((section, [question]))
        return groups

    def _feedback_page_values(self, answers=None, errors=None, feedback_request=None):
        values = self._get_support_tab_values("feedback")
        values.pop("project_ids", None)
        values.pop("ticket_domain", None)

        Question = request.env["ft.feedback.question"].sudo()
        questions = Question._get_portal_questions()
        partner = request.env.user.partner_id
        Param = request.env["ir.config_parameter"].sudo()

        values.update({
            "page_name": "feedback",
            "active_tab": "feedback",
            "partner": partner,
            "questions": questions,
            "submission_token": str(uuid4()),
            "question_groups": self._feedback_grouped_questions(questions),
            "rating_labels": Question._get_rating_labels(),
            "rating_levels": sorted(Question._get_rating_labels().keys()),
            "score_levels": list(range(0, 11)),
            "score_band_by_level": {
                level: band
                for low, high, band in Question._get_score_bands()
                for level in range(low, high + 1)
            },
            "intro_text": Param.get_param(INTRO_PARAM, DEFAULT_INTRO),
            "answers": answers or {},
            "errors": errors or {},
            "field_prefix": FIELD_PREFIX,
            # Monthly feedback request (ft.feedback.request, sudo) or None.
            "feedback_request": feedback_request,
            "request_param": REQUEST_PARAM,
        })
        return values

    # ------------------------------------------------------------------
    # monthly feedback request helpers
    # ------------------------------------------------------------------

    def _feedback_find_request(self, token):
        """Return the ft.feedback.request (sudo) whose access token equals
        ``token`` exactly, or an empty recordset."""
        FeedbackRequest = request.env["ft.feedback.request"].sudo()
        if (
            not isinstance(token, str)
            or not token
            or len(token) > REQUEST_TOKEN_MAX_LEN
        ):
            return FeedbackRequest
        feedback_request = FeedbackRequest.with_context(active_test=False).search(
            [("access_token", "=", token)], limit=1,
        )
        if not feedback_request or not hmac.compare_digest(
            (feedback_request.access_token or "").encode(),
            token.encode(),
        ):
            return FeedbackRequest
        return feedback_request

    def _feedback_request_unavailable(self, status):
        """Generic page used both for unknown tokens (404) and for requests
        of another customer (403), so the page never reveals whether a
        token belongs to someone else."""
        values = self._feedback_page_values()
        return request.render(
            "ft_customer_feedback.portal_feedback_request_unavailable",
            values,
            status=status,
        )

    def _feedback_resolve_request(self, token):
        """Validate a request token for the logged-in user.

        Returns ``(feedback_request, error_response)``; exactly one of the
        two is set."""
        feedback_request = self._feedback_find_request(token)
        if not feedback_request:
            return None, self._feedback_request_unavailable(404)
        partner = request.env.user.partner_id
        if (
            partner.commercial_partner_id
            != feedback_request.partner_id.commercial_partner_id
        ):
            return None, self._feedback_request_unavailable(403)
        return feedback_request, None

    def _feedback_request_existing_response(self, feedback_request, partner):
        """The response this contact already gave for a monthly request."""
        return request.env["ft.feedback.response"].sudo().with_context(
            active_test=False,
        ).search([
            ("request_id", "=", feedback_request.id),
            ("partner_id", "=", partner.id),
        ], order="id desc", limit=1)

    def _feedback_already_submitted(self, feedback_request, response=None):
        """Render the 'already submitted' page for a monthly request."""
        values = self._feedback_page_values(feedback_request=feedback_request)
        response_url = "/my/feedbacks"
        if (
            response
            and response.active
            and response.state == "submitted"
            and response in self._feedback_own_responses()
        ):
            response_url = "/my/feedbacks/%s" % response.id
        values.update({
            "response": response or request.env["ft.feedback.response"].sudo(),
            "response_url": response_url,
        })
        return request.render(
            "ft_customer_feedback.portal_feedback_already_submitted", values,
        )

    def _feedback_link_recipient(self, feedback_request, partner, response):
        """Store the submitted response on the matching recipient row.
        Never blocks the submission itself."""
        Recipient = request.env["ft.feedback.request.recipient"].sudo()
        recipient = Recipient.search([
            ("request_id", "=", feedback_request.id),
            ("partner_id", "=", partner.id),
        ], limit=1)
        if not recipient or recipient.response_id:
            return
        try:
            with request.env.cr.savepoint():
                recipient.write({"response_id": response.id})
        except Exception:  # pylint: disable=broad-except
            _logger.exception(
                "Could not link feedback %s to request recipient %s",
                response.name, recipient.id,
            )

    def _feedback_parse_answers(self, questions, post):
        """Turn the posted form into {question_id: value} plus an error dict.
        Numbers are validated against the question type's range."""
        answers = {}
        errors = {}
        for question in questions:
            raw = (post.get("%s%s" % (FIELD_PREFIX, question.id)) or "").strip()
            if not raw:
                if question.required:
                    errors[question.id] = _("This question is required.")
                continue
            if question.question_type == "text":
                answers[question.id] = raw
                if len(raw) > 2000:
                    errors[question.id] = _(
                        "Please keep your answer within 2,000 characters."
                    )
                continue
            try:
                number = int(raw)
            except ValueError:
                errors[question.id] = _("Invalid answer.")
                continue
            low, high = (1, 5) if question.question_type == "rating" else (0, 10)
            if not low <= number <= high:
                errors[question.id] = _("Invalid answer.")
                continue
            answers[question.id] = number
        return answers, errors

    # ------------------------------------------------------------------
    # routes
    # ------------------------------------------------------------------

    @http.route("/my/feedback", type="http", auth="user", website=True)
    def portal_feedback_form(self, **kw):
        feedback_request = None
        if kw.get(REQUEST_PARAM):
            feedback_request, error_response = self._feedback_resolve_request(
                kw.get(REQUEST_PARAM)
            )
            if error_response:
                return error_response
            existing = self._feedback_request_existing_response(
                feedback_request, request.env.user.partner_id,
            )
            if existing:
                return self._feedback_already_submitted(feedback_request, existing)
        values = self._feedback_page_values(feedback_request=feedback_request)
        return request.render(
            "ft_customer_feedback.portal_feedback_form", values
        )

    @http.route("/my/feedback/submit", type="http", auth="user", website=True,
                methods=["POST"], csrf=True)
    def portal_feedback_submit(self, **post):
        token = post.get("submission_token", "")

        # Monthly request: only the token is trusted, everything else
        # (project, customer) is read from the request record itself.
        feedback_request = None
        if post.get(REQUEST_PARAM):
            feedback_request, error_response = self._feedback_resolve_request(
                post.get(REQUEST_PARAM)
            )
            if error_response:
                return error_response

        try:
            token = str(UUID(token))
        except (ValueError, TypeError, AttributeError):
            values = self._feedback_page_values(feedback_request=feedback_request)
            values["error_message"] = _(
                "Please submit your feedback using this form."
            )
            return request.render(
                "ft_customer_feedback.portal_feedback_form", values
            )

        Response = request.env["ft.feedback.response"].sudo()
        existing = Response.with_context(active_test=False).search([
            ("user_id", "=", request.env.user.id),
            ("submission_token", "=", token),
        ], limit=1)

        if existing:
            return request.redirect(
                "/my/feedback/thanks/%s" % existing.id
            )

        if feedback_request:
            already = self._feedback_request_existing_response(
                feedback_request, request.env.user.partner_id,
            )
            if already:
                return self._feedback_already_submitted(feedback_request, already)

        questions = request.env["ft.feedback.question"].sudo()._get_portal_questions()
        answers, errors = self._feedback_parse_answers(questions, post)

        if errors or not questions:
            values = self._feedback_page_values(
                answers=answers, errors=errors, feedback_request=feedback_request,
            )
            values["submission_token"] = token
            if not questions:
                values["error_message"] = _("No feedback questions are configured yet.")
            else:
                values["error_message"] = _("Please answer the highlighted questions.")
            return request.render("ft_customer_feedback.portal_feedback_form", values)

        user = request.env.user
        lines = []
        for question in questions:
            answered = question.id in answers
            line = {
                "question_id": question.id,
                "sequence": question.sequence,
                "is_answered": answered,
            }
            if question.question_type == "text":
                line["text_value"] = answers.get(question.id) if answered else False
            else:
                line["rating_value"] = answers.get(question.id) if answered else 0
            lines.append((0, 0, line))

        response_vals = {
            "state": "submitted",
            "partner_id": user.partner_id.id,
            "user_id": user.id,
            "company_id": user.company_id.id or request.env.company.id,
            "line_ids": lines,
            "submission_token": token,
        }
        if feedback_request:
            response_vals.update({
                "request_id": feedback_request.id,
                "project_id": feedback_request.project_id.id,
            })

        try:
            with request.env.cr.savepoint():
                response = Response.create(response_vals)
        except UniqueViolation as error:
            if (
                error.diag.constraint_name
                == "ft_feedback_response_submission_token_unique"
            ):
                # A simultaneous request already saved this submission.
                return request.redirect("/my/feedbacks")
            if not feedback_request:
                raise
            # One response per contact per monthly request (unique index).
            return self._feedback_already_submitted(
                feedback_request,
                self._feedback_request_existing_response(
                    feedback_request, user.partner_id,
                ),
            )
        except ValidationError:
            if not feedback_request:
                raise
            already = self._feedback_request_existing_response(
                feedback_request, user.partner_id,
            )
            if not already:
                raise
            return self._feedback_already_submitted(feedback_request, already)

        if feedback_request:
            self._feedback_link_recipient(feedback_request, user.partner_id, response)

        _logger.info(
            "Customer feedback %s submitted by %s",
            response.name,
            user.login,
        )
        return request.redirect(
            "/my/feedback/thanks/%s" % response.id
        )

    def _feedback_own_responses(self):
        """Submitted responses of the logged-in customer's company."""
        partner = request.env.user.partner_id
        return request.env["ft.feedback.response"].sudo().search([
            ("commercial_partner_id", "=", partner.commercial_partner_id.id),
            ("state", "=", "submitted"),
        ])

    @http.route("/my/feedbacks", type="http", auth="user", website=True)
    def portal_feedback_list(self, **kw):
        """'Feedbacks' tab: every feedback already given by this customer."""
        values = self._get_support_tab_values("feedbacks")
        values.pop("project_ids", None)
        values.pop("ticket_domain", None)
        values.update({
            "page_name": "feedbacks",
            "active_tab": "feedbacks",
            "responses": self._feedback_own_responses(),
        })
        return request.render("ft_customer_feedback.portal_feedback_list", values)

    @http.route("/my/feedbacks/<int:response_id>", type="http", auth="user", website=True)
    def portal_feedback_detail(self, response_id, **kw):
        response = self._feedback_own_responses().filtered(lambda r: r.id == response_id)
        if not response:
            return request.redirect("/my/feedbacks")
        values = self._get_support_tab_values("feedbacks")
        values.pop("project_ids", None)
        values.pop("ticket_domain", None)
        values.update({
            "page_name": "feedbacks",
            "active_tab": "feedbacks",
            "response": response,
            "rating_labels": request.env["ft.feedback.question"].sudo()._get_rating_labels(),
        })
        return request.render("ft_customer_feedback.portal_feedback_detail", values)

    @http.route("/my/feedback/thanks/<int:response_id>", type="http",
                auth="user", website=True)
    def portal_feedback_thanks(self, response_id, **kw):
        partner = request.env.user.partner_id
        response = request.env["ft.feedback.response"].sudo().browse(response_id).exists()
        if not response or response.partner_id != partner:
            return request.redirect("/my/feedback")
        values = self._feedback_page_values()
        values.update({
            "response": response,
            "thanks_text": request.env["ir.config_parameter"].sudo().get_param(
                THANKS_PARAM, DEFAULT_THANKS),
        })
        return request.render("ft_customer_feedback.portal_feedback_thanks", values)
