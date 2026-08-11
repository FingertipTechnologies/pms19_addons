from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager


class HelpdeskPortal(CustomerPortal):
    """Extend the customer portal to expose helpdesk tickets and their milestones."""

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'ticket_count' in counters:
            values['ticket_count'] = request.env['ft.helpdesk.ticket'].search_count([])
        return values

    @http.route(['/my', '/my/home'], type='http', auth='user', website=True)
    def portal_my_home_redirect(self, **kw):
        user = request.env.user
        if user.has_group('base.group_portal'):
            return request.redirect('/my/support/projects')
        # Internal users: show normal home page
        return super().portal_my_home(**kw)
    # ------------------------------------------------------------------
    # /my/tickets  – ticket list
    # ------------------------------------------------------------------
    @http.route(
        ['/my/tickets', '/my/tickets/page/<int:page>'],
        type='http',
        auth='user',
        website=True,
    )
    def portal_my_tickets(self, page=1, **kw):
        ticket_obj = request.env['ft.helpdesk.ticket']
        ticket_count = ticket_obj.search_count([])
        pager = portal_pager(
            url='/my/tickets',
            total=ticket_count,
            page=page,
            step=10,
        )
        tickets = ticket_obj.search([], limit=10, offset=pager['offset'], order='id desc')

        values = {
            'tickets': tickets,
            'pager': pager,
            'page_name': 'ticket',
        }
        return request.render('ft_helpdesk_core.portal_my_tickets', values)

    # ------------------------------------------------------------------
    # /my/tickets/<id>  – ticket detail with milestones tab
    # ------------------------------------------------------------------
    @http.route(
        ['/my/tickets/<int:ticket_id>'],
        type='http',
        auth='user',
        website=True,
    )
    def portal_ticket_detail(self, ticket_id, **kw):
        ticket = request.env['ft.helpdesk.ticket'].browse(ticket_id)

        # browse() is lazy; the record rule will deny access if this ticket
        # does not belong to the logged-in portal user.
        if not ticket.exists():
            return request.not_found()

        # Fetch project milestones linked to the ticket's project
        milestones = request.env['project.custom.milestone'].sudo().search(
            [('project_id', '=', ticket.project_id.id)],
            order='due_date asc, id asc',
        ) if ticket.project_id else request.env['project.custom.milestone']

        values = {
            'ticket': ticket,
            'milestones': milestones,
            'page_name': 'ticket',
        }
        return request.render('ft_helpdesk_core.portal_ticket_detail', values)
