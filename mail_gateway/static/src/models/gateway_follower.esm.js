import {Record, fields} from "@mail/core/common/record";

export class GatewayFollower extends Record {
    static id = "id";

    /** @type {Number} */
    id;
    /** @type {String} */
    name;
    // In Odoo 19 the "Persona" model was removed; followers are res.partner.
    partner = fields.One("res.partner");
    channel = fields.One("GatewayChannel");
}

GatewayFollower.register();
