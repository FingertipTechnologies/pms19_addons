import {Record} from "@mail/core/common/record";

export class Gateway extends Record {
    static id = "id";

    /** @type {Number} */
    id;
    /** @type {String} */
    type;
    /** @type {String} */
    name;
}
Gateway.register();
