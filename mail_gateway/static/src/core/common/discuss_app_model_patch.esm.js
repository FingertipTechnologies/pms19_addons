import {DiscussApp} from "@mail/core/public_web/discuss_app_model";
import {fields} from "@mail/core/common/record";

import {_t} from "@web/core/l10n/translation";
import {patch} from "@web/core/utils/patch";

patch(DiscussApp.prototype, {
    setup(env) {
        super.setup(env);
        this.gateway = fields.One("DiscussAppCategory", {
            compute() {
                return {
                    extraClass: "o-mail-DiscussSidebarCategory-gateway",
                    id: "gateway",
                    name: _t("Gateway"),
                    isOpen: false,
                    canView: false,
                    canAdd: true,
                    addTitle: _t("Search Gateway Channel"),
                    serverStateKey: "is_discuss_sidebar_category_gateway_open",
                };
            },
        });
    },
});
