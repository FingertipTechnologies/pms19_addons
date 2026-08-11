# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class FtHomepageController(http.Controller):
    @http.route("/ft_homepage/video/<int:rec_id>", type="http", auth="user")
    def homepage_video(self, rec_id, **kwargs):
        """Stream an uploaded quote/announcement video to any logged-in
        user (sudo, since regular users may not have read access to the
        model through the standard /web/content route)."""
        record = request.env["ft.quote.announcement"].sudo().browse(rec_id).exists()
        if not record or not record.video_file:
            return request.not_found()
        stream = request.env["ir.binary"]._get_stream_from(
            record, "video_file", filename=record.video_filename or "video.mp4"
        )
        return stream.get_response()
