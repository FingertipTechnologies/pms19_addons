// Odoo 19 removed the "Persona" model: personas are now res.partner / mail.guest
// records. The gateway channels are pushed by the server onto res.partner
// (see res_partner.py::_to_store_defaults), so we declare the field there.
import {ResPartner} from "@mail/core/common/res_partner_model";
import {fields} from "@mail/core/common/record";
import {patch} from "@web/core/utils/patch";

patch(ResPartner.prototype, {
    setup() {
        super.setup();
        this.gateway_channels = fields.Many("GatewayChannel");
    },
});
