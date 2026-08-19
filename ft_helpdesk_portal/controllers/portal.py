import base64
import json
import logging

from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import pager as portal_pager
from odoo.addons.web.controllers.home import Home
from odoo.exceptions import AccessError, MissingError
from odoo.fields import Domain
from odoo.addons.ft_helpdesk_core.controllers.portal import HelpdeskPortal as HelpdeskPortalBase


def AND(domains):
    # Odoo 19 deprecated odoo.osv.expression; keep the legacy list-domain result.
    return list(Domain.AND(domains))

_logger = logging.getLogger(__name__)

TICKETS_PER_PAGE = 10


class HelpdeskPortal(HelpdeskPortalBase):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            partner = request.env.user.partner_id
            values['ticket_count'] = request.env['ft.helpdesk.ticket'].search_count([
                ('customer_id.commercial_partner_id', '=',
                 partner.commercial_partner_id.id),
            ])
        return values

    # =============================
    # Common tab values helper
    # =============================

    def _get_support_tab_values(self, active_tab='tickets'):
        """Return values shared by all support tabs (counts for badges)."""
        user = request.env.user
        partner = user.partner_id
        commercial_partner = partner.commercial_partner_id
        Ticket = request.env['ft.helpdesk.ticket'].sudo()
        ticket_domain = [('customer_id.commercial_partner_id', '=', commercial_partner.id)]

        # Find project IDs linked to the customer's tickets
        tickets = Ticket.search(ticket_domain)
        project_ids = tickets.mapped('project_id').ids

        milestone_count = request.env['project.custom.milestone'].sudo().search_count(
            [('project_id', 'in', project_ids)]
        ) if project_ids else 0

        release_count = request.env['ft.helpdesk.release'].sudo().search_count(
            [('project_id', 'in', project_ids)]
        ) if project_ids else 0

        kb_count = request.env['ft.helpdesk.kb.article'].sudo().search_count(
            [('portal_published', '=', True)]
        )

        if user.has_group('base.group_user'):
            project_count = request.env['project.project'].sudo().search_count([
                ('user_id', '=', user.id),
            ])
        else:
            project_count = request.env['project.project'].sudo().search_count([
                ('partner_id', '=', commercial_partner.id),
            ])

        return {
            'page_name': 'support_home',
            'active_tab': active_tab,
            'ticket_count': Ticket.search_count(ticket_domain),
            'project_count': project_count,
            'milestone_count': milestone_count,
            'release_count': release_count,
            'kb_count': kb_count,
            'project_ids': project_ids,
            'ticket_domain': ticket_domain,
        }

    # =============================
    # Redirect portal users to /my/support
    # =============================

    @http.route()
    def home(self, **kw):
        """Portal users get the support portal instead of the stock /my page.

        Odoo 19 renamed ``CustomerPortal.portal_my_home`` to ``home``. Keeping
        the old name only added a duplicate ``/my`` rule that werkzeug never
        matched, so customers kept landing on the stock "My account" page.
        """
        if request.env.user.has_group('base.group_portal'):
            return request.redirect(PORTAL_LANDING)
        return super().home(**kw)

    # =============================
    # Support Home — landing page
    # =============================

    @http.route('/my/support', type='http', auth='user', website=True)
    def portal_support_home(self, **kw):
        values = self._get_support_tab_values()
        values['active_tab'] = ''
        return request.render('ft_helpdesk_portal.portal_support_landing', values)

    # =============================
    # Projects Tab
    # =============================

    @http.route('/my/support/projects', type='http', auth='user', website=True)
    def portal_support_projects(self, **kw):
        values = self._get_support_tab_values('projects')
        values.pop('project_ids')
        values.pop('ticket_domain')

        user = request.env.user
        partner = user.partner_id
        if user.has_group('base.group_user'):
            projects = request.env['project.project'].sudo().search([
                ('user_id', '=', user.id),
            ], order='name')
        else:
            projects = request.env['project.project'].sudo().search([
                ('partner_id', '=', partner.commercial_partner_id.id),
            ], order='name')

        values['projects'] = projects
        return request.render('ft_helpdesk_portal.portal_support_projects', values)

    # =============================
    # Milestones Tab
    # =============================

    @http.route('/my/support/milestones', type='http', auth='user', website=True)
    def portal_support_milestones(self, sortby='due_date_asc', filterby='all', search='', **kw):
        values = self._get_support_tab_values('milestones')
        project_ids = values.pop('project_ids')
        values.pop('ticket_domain')

        Milestone = request.env['project.custom.milestone'].sudo()
        domain = [('project_id', 'in', project_ids)] if project_ids else [('id', '=', False)]

        # Sorting — one asc/desc entry per sortable column
        sortings = {
            'milestone_id_asc': {'order': 'milestone_id asc, id asc'},
            'milestone_id_desc': {'order': 'milestone_id desc, id desc'},
            'name_asc': {'order': 'name asc, id asc'},
            'name_desc': {'order': 'name desc, id desc'},
            'project_asc': {'order': 'project_id asc, due_date asc'},
            'project_desc': {'order': 'project_id desc, due_date asc'},
            'amount_asc': {'order': 'amount asc, id asc'},
            'amount_desc': {'order': 'amount desc, id asc'},
            'paid_amount_asc': {'order': 'paid_amount asc, id asc'},
            'paid_amount_desc': {'order': 'paid_amount desc, id asc'},
            'due_date_asc': {'order': 'due_date asc, id asc'},
            'due_date_desc': {'order': 'due_date desc, id desc'},
            'status_asc': {'order': 'status asc, due_date asc'},
            'status_desc': {'order': 'status desc, due_date asc'},
        }
        order = sortings.get(sortby, sortings['due_date_asc'])['order']

        # Filtering
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'not_started': {'label': _('Not Started'), 'domain': [('status', '=', 'not_started')]},
            'completed': {'label': _('Completed'), 'domain': [('status', '=', 'completed')]},
            'invoice_raised': {'label': _('Invoice Raised'), 'domain': [('status', '=', 'invoice_raised')]},
            'partially_paid': {'label': _('Partially Paid'), 'domain': [('status', '=', 'partially_paid')]},
            'paid': {'label': _('Paid'), 'domain': [('status', '=', 'paid')]},
        }
        if filterby in filters:
            domain = AND([domain, filters[filterby]['domain']])

        # Search
        if search:
            domain = AND([domain, ['|', ('name', 'ilike', search), ('milestone_id', 'ilike', search)]])

        milestones = Milestone.search(domain, order=order)

        values.update({
            'milestones': milestones,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'search': search,
        })
        return request.render('ft_helpdesk_portal.portal_support_milestones', values)

    # =============================
    # Releases Tab
    # =============================

    @http.route('/my/support/releases', type='http', auth='user', website=True)
    def portal_support_releases(self, sortby='release_date_desc', filterby='all', search='', **kw):
        values = self._get_support_tab_values('releases')
        project_ids = values.pop('project_ids')
        values.pop('ticket_domain')

        Release = request.env['ft.helpdesk.release'].sudo()
        domain = [('project_id', 'in', project_ids)] if project_ids else [('id', '=', False)]

        # Sorting — one asc/desc entry per sortable column
        sortings = {
            'name_asc': {'order': 'name asc, id asc'},
            'name_desc': {'order': 'name desc, id desc'},
            'version_asc': {'order': 'version asc, id asc'},
            'version_desc': {'order': 'version desc, id desc'},
            'project_asc': {'order': 'project_id asc, release_date desc'},
            'project_desc': {'order': 'project_id desc, release_date desc'},
            'release_date_asc': {'order': 'release_date asc, id asc'},
            'release_date_desc': {'order': 'release_date desc, id desc'},
            'status_asc': {'order': 'status asc, release_date desc'},
            'status_desc': {'order': 'status desc, release_date desc'},
        }
        order = sortings.get(sortby, sortings['release_date_desc'])['order']

        # Filtering
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'planned': {'label': _('Planned'), 'domain': [('status', '=', 'planned')]},
            'in_progress': {'label': _('In Progress'), 'domain': [('status', '=', 'in_progress')]},
            'released': {'label': _('Released'), 'domain': [('status', '=', 'released')]},
            'cancelled': {'label': _('Cancelled'), 'domain': [('status', '=', 'cancelled')]},
        }
        if filterby in filters:
            domain = AND([domain, filters[filterby]['domain']])

        # Search
        if search:
            domain = AND([domain, ['|', ('name', 'ilike', search), ('version', 'ilike', search)]])

        releases = Release.search(domain, order=order)

        values.update({
            'releases': releases,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'search': search,
        })
        return request.render('ft_helpdesk_portal.portal_support_releases', values)

    # =============================
    # Ticket List
    # =============================

    @http.route(['/my/support/tickets', '/my/support/tickets/page/<int:page>'], type='http', auth='user', website=True)
    def portal_ticket_list(self, page=1, sortby='create_date_desc', filterby='all',
                           search='', search_in='all', **kw):
        partner = request.env.user.partner_id
        commercial_partner = partner.commercial_partner_id
        Ticket = request.env['ft.helpdesk.ticket'].sudo()

        domain = [('customer_id.commercial_partner_id', '=', commercial_partner.id)]

        # Sorting — one asc/desc entry per sortable column
        sortings = {
            'ticket_no_asc': {'order': 'ticket_no asc, id asc'},
            'ticket_no_desc': {'order': 'ticket_no desc, id desc'},
            'name_asc': {'order': 'name asc, id asc'},
            'name_desc': {'order': 'name desc, id desc'},
            'priority_asc': {'order': 'priority asc, create_date desc'},
            'priority_desc': {'order': 'priority desc, create_date desc'},
            'category_asc': {'order': 'category_id asc, create_date desc'},
            'category_desc': {'order': 'category_id desc, create_date desc'},
            'assignee_asc': {'order': 'assigned_user_id asc, create_date desc'},
            'assignee_desc': {'order': 'assigned_user_id desc, create_date desc'},
            'create_date_asc': {'order': 'create_date asc, id asc'},
            'create_date_desc': {'order': 'create_date desc, id desc'},
            'state_asc': {'order': 'state asc, create_date desc'},
            'state_desc': {'order': 'state desc, create_date desc'},
        }
        order = sortings.get(sortby, sortings['create_date_desc'])['order']

        # Filtering
        filters = {
            'all': {'label': _('All'), 'domain': []},
            'new': {'label': _('New'),
                    'domain': [('state', '=', 'new')]},
            'open': {'label': _('In Progress'),
                     'domain': [('state', '=', 'open')]},
            'pending_internal': {'label': _('Pending Internal'),
                                 'domain': [('state', '=', 'pending_internal')]},
            'pending_customer': {'label': _('Pending My Reply'),
                                 'domain': [('state', '=', 'pending_customer')]},
            'resolved': {'label': _('Resolved'),
                         'domain': [('state', '=', 'resolved')]},
            'closed': {'label': _('Closed'),
                       'domain': [('state', '=', 'closed')]},
            'cancelled': {'label': _('Cancelled'),
                          'domain': [('state', '=', 'cancelled')]},
        }
        if filterby in filters:
            domain = AND([domain, filters[filterby]['domain']])

        # Search
        if search:
            search_domains = {
                'all': ['|', '|',
                        ('name', 'ilike', search),
                        ('ticket_no', 'ilike', search),
                        ('description', 'ilike', search)],
                'subject': [('name', 'ilike', search)],
                'ticket_no': [('ticket_no', 'ilike', search)],
                'description': [('description', 'ilike', search)],
            }
            search_domain = search_domains.get(search_in, search_domains['all'])
            domain = AND([domain, search_domain])

        # Pager
        ticket_count = Ticket.search_count(domain)
        pager_values = portal_pager(
            url='/my/support/tickets',
            url_args={
                'sortby': sortby, 'filterby': filterby,
                'search': search, 'search_in': search_in,
            },
            total=ticket_count,
            page=page,
            step=TICKETS_PER_PAGE,
        )

        tickets = Ticket.search(
            domain, order=order,
            limit=TICKETS_PER_PAGE,
            offset=pager_values['offset'],
        )

        values = self._get_support_tab_values('tickets')
        values.pop('project_ids')
        values.pop('ticket_domain')
        values.update({
            'page_name': 'ticket_list',
            'tickets': tickets,
            'pager': pager_values,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'search': search,
            'search_in': search_in,
            'search_in_options': {
                'all': _('All'),
                'subject': _('Subject'),
                'ticket_no': _('Ticket #'),
                'description': _('Description'),
            },
            'default_url': '/my/support/tickets',
        })
        return request.render('ft_helpdesk_portal.portal_ticket_list', values)

    # =============================
    # Create Ticket
    # =============================

    @http.route('/my/support/ticket/new', type='http', auth='user', website=True)
    def portal_ticket_create(self, **kw):
        categories = request.env['ft.helpdesk.category'].sudo().search([
            ('portal_visible', '=', True),
            ('parent_id', '=', False),
        ], order='sequence')
        ticket_types = request.env['ft.helpdesk.ticket.type'].sudo().search([
            ('portal_visible', '=', True),
        ], order='sequence')
        teams = request.env['ft.helpdesk.team'].sudo().search([
            ('portal_enabled', '=', True),
        ], order='sequence')
        user = request.env.user
        partner = user.partner_id
        # Internal users (admin/agents) see projects they manage (by user_id).
        # Portal users (customers) see projects linked to their company (by partner_id).
        if user.has_group('base.group_user'):
            projects = request.env['project.project'].sudo().search([
                ('user_id', '=', user.id),
            ], order='name')
        else:
            projects = request.env['project.project'].sudo().search([
                ('partner_id', '=', partner.commercial_partner_id.id),
            ], order='name')

        is_portal_user = not user.has_group('base.group_user')
        values = {
            'page_name': 'ticket_create',
            'categories': categories,
            'ticket_types': ticket_types,
            'teams': teams,
            'projects': projects,
            'is_portal_user': is_portal_user,
            'error': {},
            'error_message': [],
        }
        return request.render('ft_helpdesk_portal.portal_ticket_create', values)

    @http.route('/my/support/ticket/create', type='http', auth='user',
                website=True, methods=['POST'], csrf=True)
    def portal_ticket_submit(self, **post):
        partner = request.env.user.partner_id
        error = {}
        error_message = []

        # Validation
        if not post.get('name', '').strip():
            error['name'] = True
            error_message.append(_('Subject is required.'))
        if not post.get('description', '').strip():
            error['description'] = True
            error_message.append(_('Description is required.'))

        if error:
            categories = request.env['ft.helpdesk.category'].sudo().search([
                ('portal_visible', '=', True), ('parent_id', '=', False),
            ], order='sequence')
            ticket_types = request.env['ft.helpdesk.ticket.type'].sudo().search([
                ('portal_visible', '=', True),
            ], order='sequence')
            teams = request.env['ft.helpdesk.team'].sudo().search([
                ('portal_enabled', '=', True),
            ], order='sequence')
            user = request.env.user
            if user.has_group('base.group_user'):
                projects = request.env['project.project'].sudo().search([
                    ('user_id', '=', user.id),
                ], order='name')
            else:
                projects = request.env['project.project'].sudo().search([
                    ('partner_id', '=', partner.commercial_partner_id.id),
                ], order='name')
            is_portal_user = not user.has_group('base.group_user')
            values = {
                'page_name': 'ticket_create',
                'categories': categories,
                'ticket_types': ticket_types,
                'teams': teams,
                'projects': projects,
                'is_portal_user': is_portal_user,
                'error': error,
                'error_message': error_message,
                **post,
            }
            return request.render('ft_helpdesk_portal.portal_ticket_create', values)

        # Build ticket values
        vals = {
            'name': post.get('name', '').strip(),
            'description': post.get('description', '').strip(),
            'customer_id': partner.id,
            'channel': 'portal',
        }

        if post.get('category_id'):
            vals['category_id'] = int(post['category_id'])
        if post.get('subcategory_id'):
            vals['subcategory_id'] = int(post['subcategory_id'])
        if post.get('type_id'):
            vals['type_id'] = int(post['type_id'])
        if post.get('priority'):
            vals['priority'] = post['priority']
        if post.get('project_id'):
            project = request.env['project.project'].sudo().browse(
                int(post['project_id']))
            user = request.env.user
            if user.has_group('base.group_user'):
                # Internal user (admin/agent): allow projects they manage
                if project.exists() and project.user_id.id == user.id:
                    vals['project_id'] = project.id
            else:
                # Portal user (customer): allow projects linked to their company
                if project.exists() and project.partner_id.commercial_partner_id == partner.commercial_partner_id:
                    vals['project_id'] = project.id

        # Get default team. The customer's configured Support Team wins;
        # fall back to the ticket type's default team, then the system default.
        customer_team = (
            partner.commercial_partner_id.sudo().helpdesk_team_id
            or partner.sudo().helpdesk_team_id
        )
        if customer_team:
            vals['team_id'] = customer_team.id
        if not vals.get('team_id') and post.get('type_id'):
            ttype = request.env['ft.helpdesk.ticket.type'].sudo().browse(
                int(post['type_id']))
            if ttype.default_team_id:
                vals['team_id'] = ttype.default_team_id.id
        if not vals.get('team_id'):
            default_team = request.env['ir.config_parameter'].sudo().get_param(
                'ft_helpdesk.default_team_id')
            if default_team:
                vals['team_id'] = int(default_team)

        # Handle dynamic fields
        dynamic_values = {}
        for key, value in post.items():
            if key.startswith('dynamic_'):
                field_name = key[8:]  # Remove 'dynamic_' prefix
                dynamic_values[field_name] = value
        if dynamic_values:
            vals['dynamic_values'] = dynamic_values

        # Create ticket
        ticket = request.env['ft.helpdesk.ticket'].sudo().with_context(
            mail_create_nosubscribe=True,
        ).create(vals)

        # Post initial message first so attachments can be linked to it
        # (must come before attachment handling — Customer Conversation reads
        # mail.message.attachment_ids, not attachments linked to the ticket).
        message = ticket.sudo().message_post(
            body=vals.get('description', ''),
            message_type='comment',
            subtype_xmlid='ft_helpdesk_core.mt_ticket_new',
            author_id=partner.id,
        )

        # Handle attachments — link them to the initial message
        files = request.httprequest.files.getlist('attachments')
        attachment_ids = []
        for f in files:
            if f.filename:
                data = f.read()
                if data:
                    att = request.env['ir.attachment'].sudo().create({
                        'name': f.filename,
                        'datas': base64.b64encode(data),
                        'res_model': 'mail.message',
                        'res_id': message.id,
                    })
                    attachment_ids.append(att.id)
        if attachment_ids:
            message.sudo().write({
                'attachment_ids': [(4, aid) for aid in attachment_ids],
            })

        return request.redirect('/my/support/ticket/%s?just_created=1' % ticket.id)

    # =============================
    # Ticket Detail
    # =============================

    @http.route('/my/support/ticket/<int:ticket_id>', type='http',
                auth='user', website=True)
    def portal_ticket_detail(self, ticket_id, **kw):
        try:
            self._document_check_access(
                'ft.helpdesk.ticket', ticket_id)
            ticket = request.env['ft.helpdesk.ticket'].sudo().browse(ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/support/tickets')

        # Get only public messages (exclude internal notes)
        internal_subtype = request.env.ref(
            'ft_helpdesk_core.mt_ticket_internal_note', raise_if_not_found=False)
        msg_domain = [
            ('res_id', '=', ticket.id),
            ('model', '=', 'ft.helpdesk.ticket'),
            ('message_type', 'in', ('comment', 'email')),
        ]
        if internal_subtype:
            msg_domain.append(('subtype_id', '!=', internal_subtype.id))

        messages = request.env['mail.message'].sudo().search(
            msg_domain, order='create_date asc')

        # Generate access tokens for message attachments
        for msg in messages:
            for att in msg.attachment_ids:
                att.sudo().generate_access_token()

        # Get attachments
        attachments = request.env['ir.attachment'].sudo().search([
            ('res_model', '=', 'ft.helpdesk.ticket'),
            ('res_id', '=', ticket.id),
        ])
        for att in attachments:
            att.sudo().generate_access_token()

        # Portal settings
        allow_close = request.env['ir.config_parameter'].sudo().get_param(
            'ft_helpdesk.portal_allow_close', 'False') == 'True'
        allow_reopen = request.env['ir.config_parameter'].sudo().get_param(
            'ft_helpdesk.portal_allow_reopen', 'False') == 'True'

        values = {
            'page_name': 'ticket_detail',
            'ticket': ticket,
            'messages': messages,
            'attachments': attachments,
            'allow_close': allow_close,
            'allow_reopen': allow_reopen,
            'just_created': kw.get('just_created'),
        }
        return request.render('ft_helpdesk_portal.portal_ticket_detail', values)

    # =============================
    # Ticket Reply
    # =============================

    @http.route('/my/support/ticket/<int:ticket_id>/reply', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_reply(self, ticket_id, **post):
        try:
            ticket = self._document_check_access(
                'ft.helpdesk.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/support/tickets')

        body = post.get('body', '').strip()
        if not body:
            return request.redirect('/my/support/ticket/%s' % ticket_id)

        partner = request.env.user.partner_id

        # Post message
        message = ticket.sudo().message_post(
            body=body,
            message_type='comment',
            subtype_xmlid='ft_helpdesk_core.mt_ticket_public_reply',
            author_id=partner.id,
        )

        # Handle attachments
        files = request.httprequest.files.getlist('attachments')
        attachment_ids = []
        for f in files:
            if f.filename:
                data = f.read()
                if data:
                    att = request.env['ir.attachment'].sudo().create({
                        'name': f.filename,
                        'datas': base64.b64encode(data),
                        'res_model': 'mail.message',
                        'res_id': message.id,
                    })
                    attachment_ids.append(att.id)
        if attachment_ids:
            message.sudo().write({
                'attachment_ids': [(4, aid) for aid in attachment_ids],
            })

        return request.redirect('/my/support/ticket/%s' % ticket_id)

    # =============================
    # Ticket Close / Reopen (Portal)
    # =============================

    @http.route('/my/support/ticket/<int:ticket_id>/close', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_close(self, ticket_id, **post):
        allow_close = request.env['ir.config_parameter'].sudo().get_param(
            'ft_helpdesk.portal_allow_close', 'False') == 'True'
        if not allow_close:
            return request.redirect('/my/support/ticket/%s' % ticket_id)
        try:
            ticket = self._document_check_access(
                'ft.helpdesk.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/support/tickets')

        if ticket.state not in ('closed', 'cancelled'):
            ticket.sudo().write({'state': 'closed'})
            ticket.sudo().message_post(
                body=_('Ticket closed by customer via portal.'),
                message_type='notification',
                subtype_xmlid='ft_helpdesk_core.mt_ticket_state_change',
            )
        return request.redirect('/my/support/ticket/%s' % ticket_id)

    @http.route('/my/support/ticket/<int:ticket_id>/reopen', type='http',
                auth='user', website=True, methods=['POST'], csrf=True)
    def portal_ticket_reopen(self, ticket_id, **post):
        allow_reopen = request.env['ir.config_parameter'].sudo().get_param(
            'ft_helpdesk.portal_allow_reopen', 'False') == 'True'
        if not allow_reopen:
            return request.redirect('/my/support/ticket/%s' % ticket_id)
        try:
            ticket = self._document_check_access(
                'ft.helpdesk.ticket', ticket_id)
        except (AccessError, MissingError):
            return request.redirect('/my/support/tickets')

        if ticket.state in ('resolved', 'closed'):
            ticket.sudo().action_reopen()
            ticket.sudo().message_post(
                body=_('Ticket reopened by customer via portal.'),
                message_type='notification',
                subtype_xmlid='ft_helpdesk_core.mt_ticket_state_change',
            )
        return request.redirect('/my/support/ticket/%s' % ticket_id)

    # =============================
    # AJAX: Get subcategories
    # =============================

    @http.route('/my/support/subcategories', type='jsonrpc', auth='user', website=True)
    def get_subcategories(self, category_id, **kw):
        subcategories = request.env['ft.helpdesk.subcategory'].sudo().search([
            ('category_id', '=', int(category_id)),
            ('portal_visible', '=', True),
        ], order='sequence')
        return [{'id': s.id, 'name': s.name} for s in subcategories]

    # =============================
    # AJAX: Get dynamic fields for type
    # =============================

    @http.route('/my/support/dynamic_fields', type='jsonrpc', auth='user', website=True)
    def get_dynamic_fields(self, type_id, **kw):
        ticket_type = request.env['ft.helpdesk.ticket.type'].sudo().browse(int(type_id))
        if not ticket_type.fieldset_id:
            return []
        fields_data = []
        for field in ticket_type.fieldset_id.field_ids:
            if not field.portal_visible:
                continue
            field_info = {
                'name': field.technical_name,
                'label': field.name,
                'type': field.field_type,
                'required': field.required,
                'placeholder': field.placeholder or '',
                'help_text': field.help_text or '',
            }
            if field.field_type == 'selection' and field.selection_options:
                field_info['options'] = [
                    opt.strip() for opt in field.selection_options.split('\n')
                    if opt.strip()
                ]
            fields_data.append(field_info)
        return fields_data


PORTAL_LANDING = '/my/support'

# Default post-login targets we take over for portal users. Odoo sends a
# non-internal user to /web/login_successful, which lands them on Odoo's stock
# /my portal home; /my and /my/home are the same page reached directly.
_GENERIC_LANDINGS = {'/my', '/my/home', '/web/login_successful'}


class HelpdeskLoginRedirect(Home):
    """Land portal users on the support portal after login."""

    def _login_redirect(self, uid, redirect=None):
        """Override the single chokepoint every login path funnels through.

        Overriding web_login alone was not enough: it only acted when no
        ``redirect`` parameter was supplied, so a request carrying
        ?redirect=/my still dropped the user on Odoo's default portal home.

        Only fully-authenticated sessions are touched. During a partial (MFA)
        session request.session.uid is unset and the base implementation must
        run so the user reaches the MFA form instead of the portal.

        A genuine deep link - e.g. bouncing through login to reach a specific
        ticket - is preserved; only the generic landings are replaced.
        """
        if request.session.uid and (not redirect or redirect in _GENERIC_LANDINGS):
            user = request.env['res.users'].sudo().browse(uid)
            if user.has_group('base.group_portal'):
                return PORTAL_LANDING
        return super()._login_redirect(uid, redirect=redirect)
