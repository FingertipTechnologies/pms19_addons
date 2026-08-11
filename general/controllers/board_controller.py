# -*- coding: utf-8 -*-
from odoo.addons.board.controllers.main import Board
from odoo.http import request, route


class BoardPatched(Board):

    @route('/web/view/edit_custom', type='jsonrpc', auth="user")
    def edit_custom(self, custom_id=None, arch=None):
        """Odoo 18 board.board 'Change Layout' posts to /web/view/edit_custom
        but in some flows omits custom_id, causing:
            TypeError: edit_custom() missing 1 required positional
            argument: 'custom_id'
        Make custom_id optional and handle the missing case gracefully.
        """
        if not custom_id:
            return {'status': 'ok'}
        custom_view = request.env['ir.ui.view.custom'].browse(custom_id)
        custom_view.write({'arch': arch})
        return {'status': 'ok'}