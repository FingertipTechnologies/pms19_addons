from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import html2plaintext
from odoo.exceptions import ValidationError


class ProjectWeeklyReview(models.Model):
    """One review per project per ISO week. Previous weeks are kept."""

    _name = "ft.project.weekly.review"
    _description = "Project Weekly Review"
    _order = "week_start desc, id desc"
    _rec_name = "week_label"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="project_id.company_id",
        store=True,
        readonly=True,
    )
    week_start = fields.Date(
        string="Week Start",
        required=True,
        default=lambda self: self._default_week_start(),
        help="Monday of the ISO week this review covers.",
    )
    year = fields.Integer(
        string="ISO Year", compute="_compute_week", store=True,
    )
    week = fields.Integer(
        string="ISO Week", compute="_compute_week", store=True,
    )
    week_label = fields.Char(
        string="Week", compute="_compute_week", store=True,
    )
    challenges = fields.Html(string="Challenges", sanitize=True, required=True)
    reviewer_id = fields.Many2one(
        "res.users",
        string="Reviewer",
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
    )
    last_updated = fields.Datetime(
        string="Last Updated", readonly=True, copy=False,
    )

    _project_week_uniq = models.Constraint(
        "unique(project_id, week_start)",
        "A review already exists for this project for this week.",
    )

    @api.model
    def _default_week_start(self):
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    @api.depends("week_start")
    def _compute_week(self):
        for rec in self:
            if rec.week_start:
                iso_year, iso_week, _ = rec.week_start.isocalendar()
                rec.year = iso_year
                rec.week = iso_week
                rec.week_label = "%s-W%02d" % (iso_year, iso_week)
            else:
                rec.year = 0
                rec.week = 0
                rec.week_label = False

    @api.constrains("challenges")
    def _check_challenges(self):
        # required=True alone accepts an "empty" editor (e.g. <p><br></p>).
        for rec in self:
            if not html2plaintext(rec.challenges or "").strip():
                raise ValidationError(_("Please fill in the Challenges of the week."))

    @api.constrains("project_id", "week_start")
    def _check_unique_week(self):
        for rec in self:
            if not rec.project_id or not rec.week_start:
                continue
            duplicate = self.search_count([
                ("project_id", "=", rec.project_id.id),
                ("week_start", "=", rec.week_start),
                ("id", "!=", rec.id),
            ])
            if duplicate:
                raise ValidationError(self.env._(
                    "A review already exists for this project for week %s.",
                    rec.week_label,
                ))

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            # Always snap to the Monday of the chosen week so the unique
            # constraint is per ISO week, not per day.
            if vals.get("week_start"):
                day = fields.Date.to_date(vals["week_start"])
                vals["week_start"] = day - timedelta(days=day.weekday())
            vals["reviewer_id"] = self.env.user.id
            vals["last_updated"] = now
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("week_start"):
            day = fields.Date.to_date(vals["week_start"])
            vals["week_start"] = day - timedelta(days=day.weekday())
        vals["last_updated"] = fields.Datetime.now()
        return super().write(vals)
