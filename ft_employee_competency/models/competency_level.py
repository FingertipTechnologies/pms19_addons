from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .competency_utils import MAX_RATING


class EmployeeCompetencyLevel(models.Model):
    """One step of the common 1-5 rating scale — Needs Improvement, ...

    The scale itself is fixed at five steps, because every score, gap and
    readiness figure in the module is arithmetic on the rating number. What
    HR configures here is what each step MEANS: its name, the progress it
    stands for and the behaviour a reviewer should see before awarding it.
    """

    _name = 'employee.competency.level'
    _description = 'Competency Rating Level'
    _order = 'rating'

    rating = fields.Integer(
        required=True,
        help='Position on the 1-5 scale. Ratings, required levels and target '
             'levels everywhere in the module refer to this number.',
    )
    name = fields.Char(string='Level', required=True, translate=True)
    progress = fields.Integer(
        string='Progress %',
        help='How far along the scale this level is, for progress bars and '
             'reports. Must rise with every level.',
    )
    definition = fields.Text(
        translate=True,
        help='The behaviour a reviewer should see before awarding this level.',
    )

    _rating_uniq = models.Constraint(
        'unique(rating)',
        'Each rating on the scale can only be defined once.',
    )
    _rating_in_range = models.Constraint(
        f'CHECK(rating BETWEEN 1 AND {MAX_RATING})',
        f'A rating level must be between 1 and {MAX_RATING}.',
    )
    _progress_in_range = models.Constraint(
        'CHECK(progress BETWEEN 0 AND 100)',
        'Progress must be between 0 and 100%.',
    )

    @api.depends('rating', 'name')
    def _compute_display_name(self):
        for level in self:
            level.display_name = f'{level.rating} - {level.name}' if level.rating else level.name

    @api.constrains('rating', 'progress')
    def _check_progression(self):
        # A higher level has to mean more progress, or a progress bar would
        # show someone going backwards as they are rated up.
        levels = self.search([])
        previous = None
        for level in levels:
            if previous and level.progress <= previous.progress:
                raise ValidationError(self.env._(
                    'Level %(level)s must show more progress than level '
                    '%(previous)s (%(previous_progress)s%%).',
                    level=level.display_name,
                    previous=previous.display_name,
                    previous_progress=previous.progress,
                ))
            previous = level

    @api.model
    def _by_rating(self):
        """Return {rating: level} for the whole scale.

        Five rows at most, so one search per call is cheaper than any cache
        that would then have to be invalidated when HR renames a level.
        """
        return {level.rating: level for level in self.search([])}

    @api.model
    def _for_rating(self, rating):
        """Return the level record for a numeric rating, or an empty record."""
        return self._by_rating().get(int(rating or 0), self.browse())
