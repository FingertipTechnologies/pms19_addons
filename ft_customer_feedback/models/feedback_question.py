# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Label shown under each smiley on the portal and in the backend, keyed by
# the stored numeric value. The portal template and the response line both
# read this dict so the wording is defined once.
RATING_LABELS = {
    1: "Poor",
    2: "Fair",
    3: "Good",
    4: "Very Good",
    5: "Excellent",
}

# Answer types. Shared with the response line, which snapshots the type at
# submission time so later edits of a question do not rewrite old feedback.
QUESTION_TYPES = [
    ("rating", "Rating (Poor - Excellent)"),
    ("score", "Score (0 - 10)"),
    ("text", "Free Text"),
]

# Colour band for the 0-10 score scale (portal rendering).
SCORE_BANDS = [
    (0, 6, "poor"),
    (7, 8, "good"),
    (9, 10, "excellent"),
]


class FeedbackQuestion(models.Model):
    _name = "ft.feedback.question"
    _description = "Customer Feedback Question"
    _order = "section_sequence, sequence, id"

    name = fields.Char(string="Question", required=True, translate=True)
    question_type = fields.Selection(
        [
            ("rating", "Rating (Poor - Excellent)"),
            ("score", "Score (0 - 10)"),
            ("text", "Free Text"),
        ],
        string="Question Type",
        required=True,
        default="rating",
        help="Rating: five smiley faces stored as 1..5.\n"
        "Score: a 0..10 scale stored as 0..10.\n"
        "Free Text: a text area.",
    )
    section_id = fields.Many2one(
        "ft.feedback.section",
        string="Section",
        ondelete="set null",
        help="Questions are grouped under this heading on the portal page.",
    )
    section_sequence = fields.Integer(
        related="section_id.sequence", store=True, string="Section Sequence"
    )
    sequence = fields.Integer(default=10)
    required = fields.Boolean(
        default=True,
        help="Customers must answer this question before submitting.",
    )
    active = fields.Boolean(default=True)
    placeholder = fields.Char(
        string="Placeholder",
        translate=True,
        help="Hint text shown inside the text area (free text questions only).",
    )

    @api.constrains("name")
    def _check_duplicate_question(self):
        Question = self.sudo().with_context(active_test=False)
        for question in self:
            normalized = " ".join((question.name or "").split()).casefold()
            others = Question.search([("id", "!=", question.id)])
            if any(
                " ".join((other.name or "").split()).casefold() == normalized
                for other in others
            ):
                raise ValidationError(_(
                    "A feedback question with this text already exists."
                ))

    @api.model
    def _get_portal_questions(self):
        """Active questions in portal order (section first, then question)."""
        return self.search([("active", "=", True)])

    def _get_rating_labels(self):
        return RATING_LABELS

    def _get_score_bands(self):
        return SCORE_BANDS
