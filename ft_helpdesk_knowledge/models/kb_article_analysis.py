from odoo import fields, models, tools


class KBArticleAnalysis(models.Model):
    _name = 'ft.helpdesk.kb.article.analysis'
    _description = 'KB Article Analysis'
    _auto = False
    _rec_name = 'article_id'
    _order = 'create_date desc'

    # Dimensions
    article_id = fields.Many2one(
        'ft.helpdesk.kb.article', string='Article', readonly=True,
    )
    name = fields.Char(string='Title', readonly=True)
    category_id = fields.Many2one(
        'ft.helpdesk.kb.category', string='Category', readonly=True,
    )
    author_id = fields.Many2one(
        'res.users', string='Author', readonly=True,
    )
    customer_id = fields.Many2one(
        'res.partner', string='Customer', readonly=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_review', 'In Review'),
        ('completed', 'Completed'),
    ], string='Status', readonly=True)
    portal_published = fields.Boolean(
        string='Published', readonly=True,
    )
    create_date = fields.Datetime(string='Created On', readonly=True)

    # Measures
    view_count = fields.Integer(
        string='Views', readonly=True, group_operator='sum',
    )
    helpful_yes = fields.Integer(
        string='Helpful: Yes', readonly=True, group_operator='sum',
    )
    helpful_no = fields.Integer(
        string='Helpful: No', readonly=True, group_operator='sum',
    )
    helpful_score = fields.Float(
        string='Helpfulness (%)', readonly=True, group_operator='avg',
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    ROW_NUMBER() OVER ()    AS id,
                    a.id                    AS article_id,
                    a.name                  AS name,
                    a.category_id           AS category_id,
                    a.author_id             AS author_id,
                    rel.partner_id          AS customer_id,
                    a.state                 AS state,
                    a.portal_published      AS portal_published,
                    a.create_date           AS create_date,
                    a.view_count            AS view_count,
                    a.helpful_yes           AS helpful_yes,
                    a.helpful_no            AS helpful_no,
                    CASE
                        WHEN (a.helpful_yes + a.helpful_no) > 0
                        THEN (a.helpful_yes::FLOAT / (a.helpful_yes + a.helpful_no) * 100)
                        ELSE 0
                    END                     AS helpful_score
                FROM ft_helpdesk_kb_article a
                LEFT JOIN ft_kb_article_customer_rel rel
                    ON rel.article_id = a.id
                WHERE a.active = TRUE
            )
        """ % self._table)
