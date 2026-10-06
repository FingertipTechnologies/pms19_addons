# -*- coding: utf-8 -*-
from odoo import fields, models

from .feedback_question import QUESTION_TYPES


class FeedbackReport(models.Model):
    """Read-only reporting view: one row per answered question of a
    submitted response.

    Draft responses and unanswered (optional) questions are excluded at the
    SQL level, and 1-5 ratings are kept in a different column from 0-10
    scores, so every pivot/graph measure is a true average of comparable
    numbers (SQL AVG ignores NULLs)."""

    _name = "ft.feedback.report"
    _description = "Customer Feedback Analysis"
    _auto = False
    _rec_name = "question_text"
    _order = "date desc, id desc"

    response_id = fields.Many2one("ft.feedback.response", string="Response", readonly=True)
    response_name = fields.Char(string="Reference", readonly=True)
    date = fields.Datetime(string="Submission Date", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    commercial_partner_id = fields.Many2one("res.partner", string="Company", readonly=True)
    user_id = fields.Many2one("res.users", string="Submitted By", readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    question_id = fields.Many2one("ft.feedback.question", string="Question", readonly=True)
    question_text = fields.Char(string="Question (as asked)", readonly=True)
    question_type = fields.Selection(QUESTION_TYPES, string="Question Type", readonly=True)
    section_id = fields.Many2one("ft.feedback.section", string="Section", readonly=True)
    rating_value = fields.Float(
        string="Rating (1-5)", readonly=True, aggregator="avg", digits=(3, 2),
        help="Average of smiley ratings. Empty for score and text questions.",
    )
    score_value = fields.Float(
        string="Score (0-10)", readonly=True, aggregator="avg", digits=(4, 2),
        help="Average of 0-10 scores. Empty for rating and text questions.",
    )
    text_value = fields.Text(string="Free Text", readonly=True)
    answer_count = fields.Integer(string="Answers", readonly=True, aggregator="sum")

    @property
    def _table_query(self):
        # q.name is a translated field (JSONB); it is only used as a fallback
        # for answer lines created before question_text was snapshotted.
        return """
            SELECT
                l.id                                    AS id,
                l.response_id                           AS response_id,
                r.name                                  AS response_name,
                r.date                                  AS date,
                r.partner_id                            AS partner_id,
                r.commercial_partner_id                 AS commercial_partner_id,
                r.user_id                               AS user_id,
                r.company_id                            AS company_id,
                l.question_id                           AS question_id,
                COALESCE(
                    l.question_text,
                    q.name->>'en_US',
                    (SELECT t.v FROM jsonb_each_text(q.name) AS t(k, v) LIMIT 1)
                )                                       AS question_text,
                COALESCE(l.question_type, q.question_type) AS question_type,
                l.section_id                            AS section_id,
                CASE WHEN COALESCE(l.question_type, q.question_type) = 'rating'
                     THEN l.rating_value END            AS rating_value,
                CASE WHEN COALESCE(l.question_type, q.question_type) = 'score'
                     THEN l.rating_value END            AS score_value,
                CASE WHEN COALESCE(l.question_type, q.question_type) = 'text'
                     THEN l.text_value END              AS text_value,
                1                                       AS answer_count
            FROM ft_feedback_response_line l
            JOIN ft_feedback_response r ON r.id = l.response_id
            LEFT JOIN ft_feedback_question q ON q.id = l.question_id
            WHERE r.state = 'submitted'
              AND l.is_answered = TRUE
        """
