# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class FeedbackSection(models.Model):
    """Optional heading that groups questions on the portal page
    (e.g. "Over All", "Facilities")."""

    _name = "ft.feedback.section"
    _description = "Customer Feedback Section"
    _order = "sequence, id"

    name = fields.Char(string="Section Title", required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    question_ids = fields.One2many(
        "ft.feedback.question", "section_id", string="Questions"
    )
    question_count = fields.Integer(compute="_compute_question_count")

    @api.constrains("name")
    def _check_duplicate_section(self):
        Section = self.sudo().with_context(active_test=False)
        for section in self:
            normalized = " ".join((section.name or "").split()).casefold()
            others = Section.search([("id", "!=", section.id)])
            if any(
                " ".join((other.name or "").split()).casefold() == normalized
                for other in others
            ):
                raise ValidationError(_(
                    "A feedback section with this title already exists."
                ))

    def _compute_question_count(self):
        for section in self:
            section.question_count = len(section.question_ids)
