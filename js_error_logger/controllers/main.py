import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger("CLIENT_JS")


class JsErrorLogger(http.Controller):
    @http.route(
        "/js_error_log",
        type="http",
        auth="public",
        csrf=False,
        methods=["POST"],
        save_session=False,
    )
    def js_error_log(self, **kw):
        try:
            data = request.httprequest.get_data(as_text=True)
        except Exception as exc:  # pragma: no cover - diagnostic only
            data = f"<could not read body: {exc}>"
        _logger.error("BROWSER JS ERROR >>> %s", data)
        return ""
