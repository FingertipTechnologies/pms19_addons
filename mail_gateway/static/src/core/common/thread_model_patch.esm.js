import {assignDefined} from "@mail/utils/common/misc";
import {fields} from "@mail/core/common/record";
import {Thread} from "@mail/core/common/thread_model";
import {patch} from "@web/core/utils/patch";
import {url} from "@web/core/utils/urls";

patch(Thread.prototype, {
    setup() {
        super.setup();
        this.gateway = fields.One("Gateway");
        // Persona was removed in Odoo 19; operators/followers are res.partner.
        this.operator = fields.One("res.partner");
        this.gateway_notifications = [];
        this.gateway_followers = fields.Many("res.partner");
    },
    get isChatChannel() {
        return this.channel_type === "gateway" || super.isChatChannel;
    },
    get hasMemberList() {
        return this.channel_type === "gateway" || super.hasMemberList;
    },
    get avatarUrl() {
        if (this.channel_type !== "gateway") {
            return super.avatarUrl;
        }
        return url(
            `/web/image/discuss.channel/${this.id}/avatar_128`,
            assignDefined({}, {unique: this.avatarCacheKey})
        );
    },
    /** @param {Object} data */
    update(data) {
        super.update(data);
        if ("gateway_id" in data && this.channel_type === "gateway") {
            this.gateway = data.gateway_id;
        }
    },
    _computeDiscussAppCategory() {
        if (this.channel_type === "gateway") {
            return this.store.discuss.gateway;
        }
        return super._computeDiscussAppCategory(...arguments);
    },
});
