# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .feedback_question import RATING_LABELS, QUESTION_TYPES


class FeedbackResponse(models.Model):
    """One submission of the feedback form by a customer."""

    _name = "ft.feedback.response"
    _description = "Customer Feedback Response"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    submission_token = fields.Char(
        copy=False,
        readonly=True,
        index=True,
    )

    _submission_token_unique = models.Constraint(
        "UNIQUE(user_id, submission_token)",
        "This feedback has already been submitted.",
    )
    active = fields.Boolean(default=True)

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: "New",
    )
    date = fields.Datetime(
        string="Date",
        required=True,
        default=fields.Datetime.now,
        tracking=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("submitted", "Submitted")],
        string="Feedback Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        help="Portal submissions are created directly as Submitted.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True,
        index=True,
    )
    commercial_partner_id = fields.Many2one(
        related="partner_id.commercial_partner_id",
        string="Company",
        store=True,
    )

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        tracking=True,
        index=True,
        ondelete="set null",
        help="The project this feedback relates to.",
    )
    
    user_id = fields.Many2one(
        "res.users",
        string="Submitted By",
        help="Portal user who filled in the form.",
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company
    )
    line_ids = fields.One2many(
        "ft.feedback.response.line", "response_id", string="Answers"
    )
    average_rating = fields.Float(
        string="Average Rating",
        compute="_compute_scores",
        store=True,
        digits=(3, 2),
        aggregator="avg",
        help="Average of all 1-5 smiley ratings in this response.",
    )
    average_score = fields.Float(
        string="Average Score",
        compute="_compute_scores",
        store=True,
        digits=(4, 2),
        aggregator="avg",
        help="Average of all 0-10 scores in this response.",
    )
    rating_label = fields.Char(compute="_compute_scores", store=True)
    line_count = fields.Integer(compute="_compute_line_count")

    @api.depends("line_ids.rating_value", "line_ids.question_type", "line_ids.is_answered")
    def _compute_scores(self):
        for response in self:
            ratings = [
                l.rating_value
                for l in response.line_ids
                if l.question_type == "rating" and l.rating_value
            ]
            scores = [
                l.rating_value
                for l in response.line_ids
                if l.question_type == "score" and l.is_answered
            ]
            response.average_rating = (
                sum(ratings) / len(ratings) if ratings else 0.0
            )
            response.average_score = (
                sum(scores) / len(scores) if scores else 0.0
            )
            rounded = int(round(response.average_rating)) if ratings else 0
            response.rating_label = RATING_LABELS.get(rounded, "")

    def _compute_line_count(self):
        for response in self:
            response.line_count = len(response.line_ids)

    def action_submit(self):
        # Only the state changes: the submission date is the original one,
        # even when a response is reset to draft and submitted again.
        self.write({"state": "submitted"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def write(self, vals):
        # Allow only archive/unarchive for submitted feedback.
        if (
            set(vals) - {"active"}
            and any(response.state == "submitted" for response in self)
        ):
            raise UserError(_(
                "Submitted feedback is read-only. "
                "You can archive it instead."
            ))
        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_submitted(self):
        if any(response.state == "submitted" for response in self):
            raise UserError(_(
                "Submitted feedback cannot be deleted. "
                "Please archive it instead."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(["state"])
        prepared = []
        states = []

        for incoming in vals_list:
            vals = dict(incoming)
            states.append(vals.get("state", defaults.get("state", "draft")))
            vals["state"] = "draft"

            if vals.get("name", "New") == "New":
                vals["name"] = (
                    self.env["ir.sequence"].next_by_code("ft.feedback.response")
                    or "New"
                )

            prepared.append(vals)

        responses = super().create(prepared)

        for response, state in zip(responses, states):
            if not response.project_id and response.partner_id:
                projects = self.env["project.project"].search([
                    ("partner_id.commercial_partner_id", "=",
                     response.partner_id.commercial_partner_id.id),
                    ("active", "=", True),
                ], limit=2)

                if len(projects) == 1:
                    response.project_id = projects

            if state != "draft":
                response.write({"state": state})

        return responses


class FeedbackResponseLine(models.Model):
    """One answer inside a response: either a number or a free text."""

    _name = "ft.feedback.response.line"
    _description = "Customer Feedback Answer"
    _order = "sequence, id"

    response_id = fields.Many2one(
        "ft.feedback.response",
        required=True,
        ondelete="cascade",
        index=True,
    )
    question_id = fields.Many2one(
        "ft.feedback.question",
        string="Question",
        required=True,
        ondelete="restrict",
    )
    # Snapshot of the question as it was when the customer answered. The
    # configured question can be reworded or retyped later without changing
    # the meaning of stored feedback.
    question_text = fields.Char(string="Question (as asked)")
    question_type = fields.Selection(QUESTION_TYPES, string="Question Type")
    section_id = fields.Many2one(
        related="question_id.section_id", store=True
    )
    sequence = fields.Integer(default=10)
    rating_value = fields.Integer(
        string="Number",
        aggregator="avg",
        help="1..5 for smiley ratings, 0..10 for scores.",
    )
    text_value = fields.Text(string="Text Response")
    is_answered = fields.Boolean(
        default=True,
        help="False when an optional question was left blank.",
    )
    partner_id = fields.Many2one(
        related="response_id.partner_id", store=True, string="Customer"
    )
    date = fields.Datetime(related="response_id.date", store=True)
    display_value = fields.Char(compute="_compute_display_value", string="Answer")


    rating_value_display = fields.Char(string="Rating Value",
        compute="_compute_rating_value_display",
    )

    @api.depends("question_type", "rating_value", "is_answered")
    def _compute_rating_value_display(self):
        for line in self:
            line.rating_value_display = (
                str(line.rating_value)
                if line.is_answered
                and line.question_type in ("rating", "score")
                else False
            )

    @api.constrains("text_value", "question_type")
    def _check_text_answer_length(self):
        for line in self:
            if len(line.text_value or "") > 2000:
                raise ValidationError(_(
                    "Free-text answers must not exceed 2000 characters."
                ))

    @api.onchange("question_id")
    def _onchange_question_id(self):
        for line in self:
            if line.question_id:
                line.question_text = line.question_id.name
                line.question_type = line.question_id.question_type

    def write(self, vals):
        parents = self.mapped("response_id")

        if vals.get("response_id"):
            parents |= self.env["ft.feedback.response"].browse(
                vals["response_id"]
            )

        if vals and any(parent.state == "submitted" for parent in parents):
            raise UserError(_(
                "Answers on submitted feedback are read-only."
            ))

        return super().write(vals)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_submitted(self):
        if any(line.response_id.state == "submitted" for line in self):
            raise UserError(_(
                "Answers on submitted feedback cannot be deleted."
            ))

    @api.model_create_multi
    def create(self, vals_list):
        default_parent = self.default_get(["response_id"]).get("response_id")
        parent_ids = {
            vals.get("response_id", default_parent)
            for vals in vals_list
        } - {False, None}

        parents = self.env["ft.feedback.response"].browse(list(parent_ids))

        if any(parent.state == "submitted" for parent in parents):
            raise UserError(_(
                "Answers cannot be added to submitted feedback."
            ))

        Question = self.env["ft.feedback.question"]

        for vals in vals_list:
            question = (
                Question.browse(vals["question_id"])
                if vals.get("question_id")
                else None
            )

            if question:
                if not vals.get("question_text"):
                    vals["question_text"] = question.name
                if not vals.get("question_type"):
                    vals["question_type"] = question.question_type

        return super().create(vals_list)

    @api.depends("question_type", "rating_value", "text_value", "is_answered")
    def _compute_display_value(self):
        for line in self:
            if not line.is_answered:
                line.display_value = ""
            elif line.question_type == "rating":
                line.display_value = "%s - %s" % (
                    line.rating_value,
                    RATING_LABELS.get(line.rating_value, ""),
                )
            elif line.question_type == "score":
                line.display_value = "%s / 10" % line.rating_value
            else:
                line.display_value = line.text_value or ""

class ResUsers(models.Model):
    _inherit = "res.users"

    feedback_submitted = fields.Boolean(
        default=False,
        readonly=True,
        copy=False,
    )
