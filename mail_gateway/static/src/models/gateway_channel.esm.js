import {Record, fields} from "@mail/core/common/record";

export class GatewayChannel extends Record {
    static id = "id";

    /** @type {Number} */
    id;
    /** @type {String} */
    name;
    gateway = fields.One("Gateway");
}
GatewayChannel.register();
