import {Message} from "@mail/core/common/message_model";
import {patch} from "@web/core/utils/patch";
import {url} from "@web/core/utils/urls";
// Odoo 19: stateToUrl is no longer a direct export; it lives on the `router` object.
import {router} from "@web/core/browser/router";

patch(Message.prototype, {
    setup() {
        super.setup(...arguments);
        this.gateway_thread_data = {};
    },
    get resUrl() {
        // gateway_thread_data defaults to {} (truthy), so only take the gateway
        // branch when it actually carries a target record (model/id).
        if (!this.gateway_thread_data?.model) {
            return super.resUrl;
        }
        return url(
            router.stateToUrl({
                model: this.gateway_thread_data.model,
                resId: this.gateway_thread_data.id,
            })
        );
    },
    get editable() {
        return super.editable && !this.gateway_type;
    },
});
