from odoo import api, fields, models
import re


class MarketingArticle(models.Model):
    _name = "marketing.article"
    _description = "Marketing Article"
    _rec_name = "subject"
    _order = "published_on desc, create_date desc"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    industry = fields.Selection(
        selection=[
            ("real_estate", "Real Estate"),
            ("manufacturing", "Manufacturing"),
            ("consumer_goods", "Consumer Goods"),
            ("nbfc", "NBFC"),
            ("healthcare", "Healthcare"),
            ("hi_tech", "Hi Tech"),
            ("education", "Education"),
            ("agriculture", "Agriculture"),
        ],
        string="Industry",
        index=True,
        tracking=True,
    )

    technology = fields.Selection(
        selection=[
            ("salesforce", "Salesforce"),
            ("odoo", "Odoo"),
            ("web", "Web"),
            ("mobile", "Mobile"),
            ("ai", "AI"),
            ("ml", "ML"),
            ("website", "Website"),
        ],
        string="Technology",
        required=True,
        index=True,
        tracking=True,
    )

    type = fields.Selection(
        selection=[
            ("blog", "Blog"),
            ("work", "Work"),
        ],
        string="Type",
        required=True,
        default="blog",
        index=True,
        tracking=True,
    )

    site = fields.Selection(
        selection=[
            ("fingertip", "Fingertip"),
            ("symake", "Symake"),
            ("bussus", "Bussus"),
        ],
        string="Site",
        required=True,
        default="fingertip",
        index=True,
        tracking=True,
    )

    # Main content fields
    subject = fields.Char(
        string="Heading",
        required=True,
        index=True,
        tracking=True,
        help="Main page heading (H1)."
    )
    body_html = fields.Html(
        string="Body",
        sanitize=True,
    )
    excerpt = fields.Text(
        string="Excerpt / Summary",
        help="Short summary used in blog listings and as fallback for meta description."
    )
    image_url = fields.Char(string="Featured Image URL")

    # SEO fields
    slug = fields.Char(
        string="Slug",
        required=True,
        index=True,
        copy=False,
        help="SEO-friendly URL part. Example: crm-vs-erp-guide"
    )
    meta_title = fields.Char(
        string="Meta Title",
        help="Title shown in Google search results. Best around 50 to 60 characters."
    )
    meta_description = fields.Text(
        string="Meta Description",
        help="Description shown in Google search results. Best around 150 to 160 characters."
    )
    canonical_url = fields.Char(
        string="Canonical URL",
        help="Main preferred URL for search engines."
    )
    meta_keywords = fields.Char(
        string="Meta Keywords",
        help="Optional internal SEO keywords reference."
    )

    # Social sharing fields
    og_title = fields.Char(
        string="Social Share Title",
        help="Title used when shared on LinkedIn, WhatsApp, Facebook, etc."
    )
    og_description = fields.Text(
        string="Social Share Description",
        help="Description used when shared on social platforms."
    )
    og_image = fields.Char(
        string="Social Share Image URL",
        help="Image used when shared on social platforms."
    )

    # Publishing control
    active = fields.Boolean(default=True)
    is_published = fields.Boolean(
        string="Published",
        default=False,
        tracking=True,
    )
    noindex = fields.Boolean(
        string="No Index",
        default=False,
        help="If enabled, search engines should not index this page."
    )
    published_on = fields.Datetime(
        string="Published On",
        tracking=True,
    )

    # Author / display fields
    author_name = fields.Char(
        string="Author",
        default=lambda self: self.env.user.name,
    )
    creator_image = fields.Binary(
        related="create_uid.image_1920",
        string="Creator Image"
    )

    # Work / case-study related fields
    client = fields.Char(string="Client")
    technologies = fields.Char(string="Technologies")
    timeline = fields.Char(string="Timeline")
    team_size = fields.Integer(string="Team Size")

    # Optional structured data support
    schema_type = fields.Selection(
        selection=[
            ("article", "Article"),
            ("blogposting", "Blog Posting"),
            ("newsarticle", "News Article"),
            ("case_study", "Case Study"),
        ],
        string="Schema Type",
        default="blogposting",
    )

    reading_time = fields.Integer(
        string="Reading Time (mins)",
        compute="_compute_reading_time",
        store=True,
    )

    _slug_site_unique = models.Constraint(
        "unique(slug, site)",
        "Slug must be unique per site.",
    )

    @api.depends("body_html")
    def _compute_reading_time(self):
        for record in self:
            text = re.sub(r"<[^>]+>", " ", record.body_html or "")
            words = len(text.split())
            record.reading_time = max(1, round(words / 200)) if words else 1

    @api.onchange("subject")
    def _onchange_subject_set_slug(self):
        for record in self:
            if record.subject and not record.slug:
                slug = record.subject.strip().lower()
                slug = re.sub(r"[^a-z0-9\s-]", "", slug)
                slug = re.sub(r"\s+", "-", slug)
                slug = re.sub(r"-+", "-", slug)
                record.slug = slug

    @api.onchange("excerpt")
    def _onchange_excerpt_set_meta_description(self):
        for record in self:
            if record.excerpt and not record.meta_description:
                record.meta_description = record.excerpt[:160]

    @api.onchange("subject")
    def _onchange_subject_set_meta_title(self):
        for record in self:
            if record.subject and not record.meta_title:
                record.meta_title = record.subject