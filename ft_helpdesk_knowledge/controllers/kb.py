import json
import logging

from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class KnowledgeBaseController(http.Controller):

    @http.route('/my/support/kb', type='http', auth='public', website=True)
    def kb_index(self, search='', **kw):
        """Knowledge Base index page with categories and search."""
        Article = request.env['ft.helpdesk.kb.article'].sudo()
        Category = request.env['ft.helpdesk.kb.category'].sudo()

        partner = request.env.user.partner_id if not request.env.user._is_public() else False

        # Base article domain with customer filtering
        article_domain = [('portal_published', '=', True)]
        if partner:
            article_domain += [
                '|',
                ('customer_visibility', '=', 'all'),
                '&', ('customer_visibility', '=', 'specific'), ('customer_ids', 'in', [partner.id]),
            ]

        articles = False
        if search:
            search_domain = article_domain + [
                '|', '|', '|',
                ('name', 'ilike', search),
                ('summary', 'ilike', search),
                ('keywords', 'ilike', search),
                ('body_html', 'ilike', search),
            ]
            articles = Article.search(search_domain, limit=20, order='helpful_score desc, view_count desc')

        # Filter categories: only show those with accessible articles
        all_categories = Category.search([
            ('portal_published', '=', True),
            ('parent_id', '=', False),
        ], order='sequence')

        visible_categories = Category
        category_article_counts = {}
        for cat in all_categories:
            cat_domain = article_domain + [('category_id', '=', cat.id)]
            count = Article.search_count(cat_domain)
            if count > 0:
                visible_categories |= cat
                category_article_counts[cat.id] = count

        values = {
            'page_name': 'kb_index',
            'active_tab': 'kb',
            'categories': visible_categories,
            'category_article_counts': category_article_counts,
            'articles': articles,
            'search': search,
        }

        # Add tab counts if user is authenticated
        if not request.env.user._is_public():
            try:
                from odoo.addons.ft_helpdesk_portal.controllers.portal import FtHelpdeskPortal
                portal = FtHelpdeskPortal()
                tab_values = portal._get_support_tab_values(active_tab='kb')
                values.update(tab_values)
            except Exception:
                pass

        return request.render('ft_helpdesk_knowledge.kb_portal_index', values)

    @http.route('/my/support/kb/<string:slug>', type='http',
                auth='public', website=True)
    def kb_article(self, slug, **kw):
        """Single KB article page."""
        Article = request.env['ft.helpdesk.kb.article'].sudo()
        partner = request.env.user.partner_id if not request.env.user._is_public() else False
        article_domain = [
            ('slug', '=', slug),
            ('portal_published', '=', True),
        ]
        if partner:
            article_domain += ['|', ('customer_visibility', '=', 'all'), '&', ('customer_visibility', '=', 'specific'), ('customer_ids', 'in', [partner.id])]
        article = Article.search(article_domain, limit=1)

        if not article:
            return request.redirect('/my/support/kb')

        # Increment view counter
        article._increment_view()

        # Related articles from same category (also filtered)
        related_domain = [
            ('category_id', '=', article.category_id.id),
            ('portal_published', '=', True),
            ('id', '!=', article.id),
        ]
        if partner:
            related_domain += ['|', ('customer_visibility', '=', 'all'), '&', ('customer_visibility', '=', 'specific'), ('customer_ids', 'in', [partner.id])]
        related = Article.search(related_domain, limit=5, order='view_count desc')

        values = {
            'page_name': 'kb_article',
            'article': article,
            'related_articles': related,
        }
        return request.render('ft_helpdesk_knowledge.kb_portal_article', values)

    @http.route('/my/support/kb/category/<int:category_id>', type='http',
                auth='public', website=True)
    def kb_category(self, category_id, **kw):
        """KB category page with articles list."""
        Category = request.env['ft.helpdesk.kb.category'].sudo()
        Article = request.env['ft.helpdesk.kb.article'].sudo()

        category = Category.browse(category_id)
        if not category.exists() or not category.portal_published:
            return request.redirect('/my/support/kb')

        partner = request.env.user.partner_id if not request.env.user._is_public() else False
        article_domain = [
            ('category_id', '=', category.id),
            ('portal_published', '=', True),
        ]
        if partner:
            article_domain += ['|', ('customer_visibility', '=', 'all'), '&', ('customer_visibility', '=', 'specific'), ('customer_ids', 'in', [partner.id])]

        articles = Article.search(article_domain, order='sequence, helpful_score desc')

        values = {
            'page_name': 'kb_category',
            'category': category,
            'articles': articles,
        }
        return request.render('ft_helpdesk_knowledge.kb_portal_category', values)

    @http.route('/my/support/kb/suggest', type='http', auth='user',
                website=True, methods=['GET'])
    def kb_suggest(self, q='', category_id=None, **kw):
        """AJAX endpoint for KB article suggestions during ticket creation."""
        if len(q) < 3:
            return request.make_json_response([])

        Article = request.env['ft.helpdesk.kb.article'].sudo()
        domain = [
            ('portal_published', '=', True),
            '|', '|',
            ('name', 'ilike', q),
            ('summary', 'ilike', q),
            ('keywords', 'ilike', q),
        ]

        # If category specified, try to find KB articles related to that category
        if category_id:
            kb_cats = request.env['ft.helpdesk.kb.category'].sudo().search([
                ('helpdesk_category_id', '=', int(category_id)),
            ])
            if kb_cats:
                domain = [
                    ('portal_published', '=', True),
                    ('category_id', 'in', kb_cats.ids),
                    '|', '|',
                    ('name', 'ilike', q),
                    ('summary', 'ilike', q),
                    ('keywords', 'ilike', q),
                ]

        articles = Article.search(domain, limit=5,
                                  order='helpful_score desc, view_count desc')

        result = [{
            'id': a.id,
            'title': a.name,
            'slug': a.slug,
            'summary': a.summary or '',
        } for a in articles]

        return request.make_json_response(result)

    @http.route('/my/support/kb/vote/<int:article_id>', type='jsonrpc',
                auth='user', website=True)
    def kb_vote(self, article_id, helpful=True, **kw):
        """AJAX endpoint for helpful/not helpful votes."""
        article = request.env['ft.helpdesk.kb.article'].sudo().browse(article_id)
        if article.exists() and article.portal_published:
            article._vote_helpful(helpful)
            return {'success': True}
        return {'success': False}
