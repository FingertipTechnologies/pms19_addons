import re
from odoo import api, fields, models


class KBArticle(models.Model):
    _name = 'ft.helpdesk.kb.article'
    _description = 'Knowledge Base Article'
    _order = 'sequence, name'
    _rec_name = 'name'

    name = fields.Char(string='Title', required=True, translate=True, index='trigram')
    slug = fields.Char(
        string='URL Slug', required=True, index=True,
        help='URL-friendly identifier for this article.',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_review', 'In Review'),
        ('completed', 'Completed'),
    ], string='Status', default='draft', required=True, tracking=True)

    category_id = fields.Many2one(
        'ft.helpdesk.kb.category', string='Category',
        required=True, index=True,
    )
    body_html = fields.Html(
        string='Article Body', sanitize_style=True, translate=True,
    )
    summary = fields.Text(
        string='Summary', translate=True,
        help='Short summary shown in search results and suggestions.',
    )
    portal_published = fields.Boolean(
        string='Published', default=False,
    )
    author_id = fields.Many2one(
        'res.users', string='Author',
        default=lambda self: self.env.user,
    )

    # Engagement metrics
    view_count = fields.Integer(string='Views', default=0, readonly=True)
    helpful_yes = fields.Integer(string='Helpful: Yes', default=0, readonly=True)
    helpful_no = fields.Integer(string='Helpful: No', default=0, readonly=True)
    helpful_score = fields.Float(
        string='Helpfulness Score',
        compute='_compute_helpful_score', store=True,
    )

    # Tags for search
    tag_ids = fields.Many2many(
        'ft.helpdesk.tag', 'ft_kb_article_tag_rel',
        'article_id', 'tag_id', string='Tags',
    )

    # SEO
    meta_description = fields.Char(string='Meta Description', translate=True)
    keywords = fields.Char(
        string='Keywords',
        help='Comma-separated keywords for search matching.',
    )
    # Customer-specific tagging
    customer_visibility = fields.Selection([
        ('all', 'All Customers'),
        ('specific', 'Specific Customers'),
    ], string='Customer Visibility', default='all', required=True,
        help='Choose whether this article is visible to all customers or only specific ones.',
    )
    customer_ids = fields.Many2many(
        'res.partner', 'ft_kb_article_customer_rel',
        'article_id', 'partner_id', string='Customers',
        help='Restrict article visibility to these customers.',
    )

    @api.depends('helpful_yes', 'helpful_no')
    def _compute_helpful_score(self):
        for article in self:
            total = article.helpful_yes + article.helpful_no
            article.helpful_score = (
                article.helpful_yes / total * 100 if total > 0 else 0)

    @api.onchange('name')
    def _onchange_name(self):
        if self.name and not self.slug:
            self.slug = self._generate_slug(self.name)

    @api.model
    def _generate_slug(self, title):
        """Generate URL-friendly slug from title."""
        slug = title.lower().strip()
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug[:100]

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_set_in_review(self):
        self.write({'state': 'in_review'})

    def action_set_completed(self):
        self.write({'state': 'completed'})

    def action_publish(self):
        self.write({'portal_published': True})

    def action_unpublish(self):
        self.write({'portal_published': False})

    def _increment_view(self):
        """Increment view count (called from controller)."""
        self.sudo().write({'view_count': self.view_count + 1})

    def _vote_helpful(self, is_helpful):
        """Record helpful/not helpful vote."""
        if is_helpful:
            self.sudo().write({'helpful_yes': self.helpful_yes + 1})
        else:
            self.sudo().write({'helpful_no': self.helpful_no + 1})
