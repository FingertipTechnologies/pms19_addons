from datetime import timedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

WEEK_SELECTION = [('week_%02d' % w, f'Week {w}') for w in range(1, 31)]

DOMAIN_SELECTION = [
    ('salesforce', 'Salesforce'),
    ('odoo', 'Odoo'),
    ('python', 'Python'),
    ('react', 'React'),
    ('flutter', 'Flutter'),
    ('react_native', 'React Native'),
]

WORK_COMPLETED_SELECTION = [
    ('completed', 'Completed'),
    ('partially_completed', 'Partially Completed'),
    ('not_completed', 'Not Completed'),
    ('not_evaluated', 'Not Evaluated'),
]

TECHNICAL_PERFORMANCE_SELECTION = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('average', 'Average'),
    ('needs_improvement', 'Needs Improvement'),
    ('poor', 'Poor'),
    ('not_evaluated', 'Not Evaluated'),
]

LEARNING_IMPROVEMENT_SELECTION = [
    ('good', 'Good'),
    ('improving', 'Improving'),
    ('no_improvement', 'No Improvement'),
    ('not_evaluated', 'Not Evaluated'),
]

COMMUNICATION_SELECTION = [
    ('excellent', 'Excellent'),
    ('good', 'Good'),
    ('average', 'Average'),
    ('needs_improvement', 'Needs Improvement'),
    ('not_evaluated', 'Not Evaluated'),
]

INDEPENDENCE_SELECTION = [
    ('independent', 'Independent'),
    ('need_support', 'Need Support'),
    ('dependent', 'Dependent'),
    ('not_evaluated', 'Not Evaluated'),
]

OVERALL_STATUS_SELECTION = [
    ('t1', 'T1 \u2013 Excellent Progress'),
    ('t2', 'T2 \u2013 Good Progress'),
    ('t3', 'T3 \u2013 Improving'),
    ('t4', 'T4 \u2013 Needs Improvement'),
    ('t5', 'T5 \u2013 Insufficient Progress'),
    ('t6', 'T6 \u2013 Not Evaluated'),
]

RECOMMENDATION_SELECTION = [
    ('c1', 'C1 \u2013 Happy to Continue'),
    ('c2', 'C2 \u2013 Continue and Monitor'),
    ('c3', 'C3 \u2013 Final Improvement Period'),
    ('c4', 'C4 \u2013 Do Not Continue'),
]


class TraineeWeeklyReview(models.Model):
    _name = 'ft.trainee.weekly.review'
    _description = 'Trainee Weekly Review'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'review_date desc, id desc'

    active = fields.Boolean(
        string='Active',
        default=True,
        tracking=True,
        help='Uncheck to archive the review record.',
    )
    trainee_id = fields.Many2one(
        'hr.employee',
        string='Trainee',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    pm_tl_id = fields.Many2one(
        'hr.employee',
        string='PM / TL',
        required=True,
        ondelete='restrict',
        index=True,
        default=lambda self: self.env.user.employee_id,
        tracking=True,
        help='Select the responsible Project Manager or Team Lead.',
    )
    week = fields.Selection(
        WEEK_SELECTION,
        string='Week',
        required=True,
        index=True,
        tracking=True,
        help='Week 1 through Week 30',
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        tracking=True,
        help='Start date of the selected review week',
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        tracking=True,
        help='End date of the selected review week',
    )
    review_date = fields.Date(
        string='Review Date',
        required=True,
        default=fields.Date.context_today,
        readonly=True,
        tracking=True,
        help='Date on which the review is performed (automatically set to today)',
    )
    technology = fields.Selection(
        DOMAIN_SELECTION,
        string='Technology',
        required=True,
        tracking=True,
        help='Domain / Technology stack',
    )
    work_details = fields.Text(
        string='Work Details',
        required=True,
        tracking=True,
        help='Mention the tasks/work handled by the trainee during the week',
    )
    work_completed = fields.Selection(
        WORK_COMPLETED_SELECTION,
        string='Work Completed',
        required=True,
        tracking=True,
    )
    technical_performance = fields.Selection(
        TECHNICAL_PERFORMANCE_SELECTION,
        string='Technical Performance',
        required=True,
        tracking=True,
    )
    learning_improvement = fields.Selection(
        LEARNING_IMPROVEMENT_SELECTION,
        string='Learning / Improvement',
        required=True,
        tracking=True,
    )
    communication = fields.Selection(
        COMMUNICATION_SELECTION,
        string='Communication',
        required=True,
        tracking=True,
    )
    independence = fields.Selection(
        INDEPENDENCE_SELECTION,
        string='Independence',
        required=True,
        tracking=True,
    )
    overall_status = fields.Selection(
        OVERALL_STATUS_SELECTION,
        string='Overall Trainee Status',
        required=True,
        tracking=True,
    )
    pm_tl_recommendation = fields.Selection(
        RECOMMENDATION_SELECTION,
        string='PM / TL Recommendation',
        required=True,
        tracking=True,
    )
    pm_tl_comments = fields.Text(
        string='PM / TL Comments',
        required=True,
        tracking=True,
        help='Comments/feedback from the PM or TL',
    )

    _sql_constraints = [
        (
            'trainee_week_uniq',
            'unique(trainee_id, week)',
            'A review for this trainee and week already exists. Duplicate reviews are not allowed.',
        ),
    ]

    @api.depends('trainee_id', 'week')
    def _compute_display_name(self):
        week_dict = dict(WEEK_SELECTION)
        for rec in self:
            trainee_name = rec.trainee_id.name or _("New")
            week_label = week_dict.get(rec.week, "")
            if week_label:
                rec.display_name = f"[{week_label}] {trainee_name}"
            else:
                rec.display_name = trainee_name

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                if rec.date_to < rec.date_from:
                    raise ValidationError(_("To Date cannot be earlier than From Date."))
                span_days = (rec.date_to - rec.date_from).days + 1
                if span_days > 7:
                    raise ValidationError(_(
                        "The review date span is greater than one week (maximum 7 days). "
                        "The selected period from %(date_from)s to %(date_to)s is %(days)d days.",
                        date_from=rec.date_from,
                        date_to=rec.date_to,
                        days=span_days,
                    ))

    @api.onchange('date_from')
    def _onchange_date_from(self):
        if self.date_from and (not self.date_to or self.date_to < self.date_from):
            self.date_to = self.date_from + timedelta(days=6)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('review_date'):
                vals['review_date'] = fields.Date.context_today(self)
            trainee_id = vals.get('trainee_id')
            week = vals.get('week')
            if trainee_id and week:
                existing = self.search([
                    ('trainee_id', '=', trainee_id),
                    ('week', '=', week),
                ], limit=1)
                if existing:
                    trainee = self.env['hr.employee'].browse(trainee_id)
                    week_label = dict(WEEK_SELECTION).get(week, week)
                    raise ValidationError(_(
                        "A review for '%(trainee)s' in %(week)s already exists. Duplicate reviews for the same trainee and week are not allowed.",
                        trainee=trainee.name,
                        week=week_label,
                    ))
        return super().create(vals_list)

    def write(self, vals):
        if 'trainee_id' in vals or 'week' in vals:
            for rec in self:
                trainee_id = vals.get('trainee_id', rec.trainee_id.id)
                week = vals.get('week', rec.week)
                if trainee_id and week:
                    existing = self.search([
                        ('id', '!=', rec.id),
                        ('trainee_id', '=', trainee_id),
                        ('week', '=', week),
                    ], limit=1)
                    if existing:
                        trainee = self.env['hr.employee'].browse(trainee_id)
                        week_label = dict(WEEK_SELECTION).get(week, week)
                        raise ValidationError(_(
                            "A review for '%(trainee)s' in %(week)s already exists. Duplicate reviews for the same trainee and week are not allowed.",
                            trainee=trainee.name,
                            week=week_label,
                        ))
        return super().write(vals)

    @api.constrains('trainee_id', 'week')
    def _check_unique_trainee_week(self):
        for rec in self:
            if rec.trainee_id and rec.week:
                duplicate = self.search([
                    ('id', '!=', rec.id),
                    ('trainee_id', '=', rec.trainee_id.id),
                    ('week', '=', rec.week),
                ], limit=1)
                if duplicate:
                    week_label = dict(WEEK_SELECTION).get(rec.week, rec.week)
                    raise ValidationError(_(
                        "A review for '%(trainee)s' in %(week)s already exists. Duplicate reviews for the same trainee and week are not allowed.",
                        trainee=rec.trainee_id.name,
                        week=week_label,
                    ))
