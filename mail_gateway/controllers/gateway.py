# Copyright 2024 Dixmit
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import json
import logging

from odoo.http import Controller, request, route

from odoo.addons.mail.tools.discuss import add_guest_to_context

_logger = logging.getLogger(__name__)


class GatewayController(Controller):
    # @route(
    #     "/gateway/<string:usage>/<string:token>/update",
    #     type="http",
    #     auth="public",
    #     methods=["GET", "POST"],
    #     csrf=False,
    # )
    # @add_guest_to_context
    # def post_update(self, usage, token, *args, **kwargs):
    #     print(request.httprequest.method)
        
    #     if request.httprequest.method == "GET":
    #         print("whatsapp integration")
    #         print(request.httprequest.GET)
    #         bot_data = request.env["mail.gateway"]._get_gateway(
    #             token, gateway_type=usage, state="pending"
    #         )
    #         if not bot_data:
    #             return request.make_response(
    #                 json.dumps({}),
    #                 [
    #                     ("Content-Type", "application/json"),
    #                 ],
    #             )
    #         return (
    #             request.env[f"mail.gateway.{usage}"]
    #             .with_user(bot_data["webhook_user_id"])
    #             .with_company(bot_data["company_id"])
    #             ._receive_get_update(bot_data, request, **kwargs)
    #         )
    #     bot_data = request.env["mail.gateway"]._get_gateway(
    #         token, gateway_type=usage, state="integrated"
    #     )
    #     if not bot_data:
    #         _logger.warning(
    #             "Gateway was not found for token %s with usage %s", token, usage
    #         )
    #         return request.make_response(
    #             json.dumps({}),
    #             [
    #                 ("Content-Type", "application/json"),
    #             ],
    #         )
    #     charset = (
    #         hasattr(request.httprequest, "charset")
    #         and request.httprequest.charset
    #         or "utf-8"
    #     )
    #     jsonrequest = json.loads(request.httprequest.get_data().decode(charset))
    #     dispatcher = (
    #         request.env[f"mail.gateway.{usage}"]
    #         .with_user(bot_data["webhook_user_id"])
    #         .with_context(no_gateway_notification=True)
    #     )
    #     if not dispatcher._verify_update(bot_data, jsonrequest):
    #         _logger.warning(
    #             "Message could not be verified for token %s with usage %s", token, usage
    #         )
    #         return request.make_response(
    #             json.dumps({}),
    #             [
    #                 ("Content-Type", "application/json"),
    #             ],
    #         )
    #     _logger.debug(
    #         "Received message for token %s with usage %s: %s",
    #         token,
    #         usage,
    #         json.dumps(jsonrequest),
    #     )
    #     gateway = dispatcher.env["mail.gateway"].browse(bot_data["id"])
    #     dispatcher._receive_update(gateway, jsonrequest)
    #     return request.make_response(
    #         json.dumps({}),
    #         [
    #             ("Content-Type", "application/json"),
    #         ],
    #     )




    @route(
        "/gateway/<string:usage>/<string:token>/update",
        type="http",
        auth="public",
        methods=["GET", "POST"],
        csrf=False,
    )
    @add_guest_to_context
    def post_update(self, usage, token, *args, **kwargs):

        print(request.httprequest.method)

        if request.httprequest.method == "GET":
            try :

                print("whatsapp integration")

                print(request.httprequest.args.to_dict())  # Better debug output

                # ===== ADD THIS: Meta webhook verification =====

                hub_mode = request.httprequest.args.get('hub.mode')

                hub_challenge = request.httprequest.args.get('hub.challenge')

                hub_verify_token = request.httprequest.args.get('hub.verify_token')

                # Check if this is a Meta WhatsApp verification request
                print("Its hitting here")
                if hub_mode == 'subscribe' and hub_challenge:
                    print("subscribe here")

                    _logger.info(

                        "WhatsApp webhook verification request received. Token: %s",

                        hub_verify_token

                    )

                    # Look up the gateway to verify the token matches

                    bot_data = request.env["mail.gateway"].sudo()._get_gateway(

                        token, gateway_type=usage, state="pending"

                    )

                    print("This is the bot data",bot_data)

                    if bot_data and hub_verify_token == "welcomenotes":

                        # ✅ Verified! Return the challenge as PLAIN TEXT

                        _logger.info("WhatsApp webhook verified successfully")

                        challenge_clean = str(hub_challenge).strip()
                        response = request.make_response(
                            challenge_clean,
                            [
                                ("Content-Type", "text/plain"),
                                ("Content-Length", str(len(challenge_clean))),
                            ],
                        )
                        response.status_code = 200
                        return response

                    else:

                        # ❌ Token mismatch

                        _logger.warning(

                            "WhatsApp webhook verification failed. Expected: %s, Got: %s",

                            token, hub_verify_token

                        )

                        return request.make_response(

                            "Forbidden",

                            [("Content-Type", "text/plain")],

                            status=403,

                        )

                # ===== END verification block =====

                # Existing logic (for non-Meta GET requests)

                bot_data = request.env["mail.gateway"]._get_gateway(

                    token, gateway_type=usage, state="pending"

                )

                if not bot_data:

                    return request.make_response(

                        json.dumps({}),

                        [("Content-Type", "application/json")],

                    )

                return (

                    request.env[f"mail.gateway.{usage}"]

                    .with_user(bot_data["webhook_user_id"])

                    .with_company(bot_data["company_id"])

                    ._receive_get_update(bot_data, request, **kwargs)

                )
            
            except Exception as e:
                print(str(e))
                print(type(e))
            # POST handling (existing code unchanged)

            bot_data = request.env["mail.gateway"]._get_gateway(

                token, gateway_type=usage, state="integrated"

            )

            # ... rest of POST logic ...
        
