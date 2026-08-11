from odoo import models, fields, api
from odoo.exceptions import ValidationError

# The six scored competencies, each rated 0..10.
SCORE_FIELDS = (
    'attitude',
    'communication',
    'understanding',
    'technical',
    'problem_solving',
    'self_dependency',
)

# Review Period: Day 1 … Day 150.
#
# The keys are zero-padded on purpose. Odoo stores a Selection as varchar and
# sorts/groups on the STORED value, so plain '1','2',…,'150' would order as
# 1, 10, 100, 101, …, 2, 20 in the list view and in Group By. '001' … '150'
# sorts and groups in numeric order while the user only ever sees "Day 1".
REVIEW_PERIOD = [('%03d' % day, 'Day %d' % day) for day in range(1, 151)]


class TraineeReview(models.Model):
    _name = 'ft.trainee.review'
    _description = 'Trainee Review'
    _order = 'create_date desc'
    _rec_name = 'trainee_id'

    trainee_id = fields.Many2one(
        'hr.employee', string='Trainee', required=True, ondelete='restrict',
    )
    # Who created the review, and thereafter whoever last updated it (see
    # write() below). Indexed because it is a reporting/filtering field.
    reviewer_id = fields.Many2one(
        'res.users', string='Reviewer', ondelete='restrict', index=True,
        default=lambda self: self.env.user,
        help='User who created the review, or who last updated it.',
    )
    # A review covers a PERIOD, not a single day. `review_period` keeps its
    # name and becomes the start of that period, so every review recorded
    # before this existed stays valid and reads as a period beginning on the
    # day it already carried — no migration, no reinterpretation of old data.
    review_period = fields.Selection(
        REVIEW_PERIOD, string='Review Period From', index=True,
        help='First day of the period this review covers (Day 1 to Day 150).',
    )
    review_period_to = fields.Selection(
        REVIEW_PERIOD, string='Review Period To', index=True,
        help='Last day of the period this review covers. Leave it empty for a '
             'review that covers a single day.',
    )
    description = fields.Text(
        string='Description',
        help='Overall review notes for the trainee.',
    )
    attitude = fields.Integer(string='Attitude', help='Rated 0 to 10.')
    communication = fields.Integer(string='Communication', help='Rated 0 to 10.')
    understanding = fields.Integer(string='Understanding', help='Rated 0 to 10.')
    technical = fields.Integer(string='Technical', help='Rated 0 to 10.')
    problem_solving = fields.Integer(string='Problem Solving', help='Rated 0 to 10.')
    self_dependency = fields.Integer(string='Self Dependency', help='Rated 0 to 10.')

    def write(self, vals):
        """Keep Reviewer pointing at whoever last touched the review.

        The field is set to the creator on create (via its default) and moves
        to the editor on every subsequent save, which is what "created or last
        updated" asks for. An explicit reviewer_id in the same write wins, so
        the field can still be corrected by hand.
        """
        if 'reviewer_id' not in vals:
            vals = dict(vals, reviewer_id=self.env.user.id)
        return super().write(vals)

    @api.constrains('review_period', 'review_period_to')
    def _check_review_period_range(self):
        """The period has to run forwards, and cannot end without starting.

        Comparing the selection keys as strings is correct here rather than
        lazy: REVIEW_PERIOD zero-pads them ('001' … '150') precisely so that
        string order and day order are the same thing.
        """
        for rec in self:
            if rec.review_period_to and not rec.review_period:
                raise ValidationError(
                    "Please set the start of the review period as well — "
                    "an end day on its own does not describe a period."
                )
            if (
                rec.review_period
                and rec.review_period_to
                and rec.review_period_to < rec.review_period
            ):
                labels = dict(REVIEW_PERIOD)
                raise ValidationError(
                    "The review period ends before it starts: "
                    f"{labels[rec.review_period]} to "
                    f"{labels[rec.review_period_to]}. "
                    "Please pick an end day on or after the start day."
                )

    @api.constrains(*SCORE_FIELDS)
    def _check_scores(self):
        labels = {
            fname: self._fields[fname].string for fname in SCORE_FIELDS
        }
        for rec in self:
            for fname in SCORE_FIELDS:
                value = rec[fname]
                if value < 0 or value > 10:
                    raise ValidationError(
                        f"{labels[fname]} must be between 0 and 10."
                    )
