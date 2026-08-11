/** @odoo-module **/

import { WebClient } from "@web/webclient/webclient"
import {patch} from "@web/core/utils/patch";
import { user } from "@web/core/user";

patch(WebClient.prototype,  {
    setup() {
        super.setup();
        // Odoo 19: the current company is exposed via `user.activeCompany`.
        // The old `company` service (env.services.company.currentCompany) was
        // removed, so accessing it threw and blanked the whole web client.
        const favicon = `/web/image/res.company/${user.activeCompany.id}/favicon`;
        const icons = document.querySelectorAll("link[rel*='icon']");
        const msIcon = document.querySelector("meta[name='msapplication-TileImage']");
        for (const icon of icons) {
            icon.href = favicon;
        }
        if (msIcon) {
            msIcon.content = favicon;
        }
    },
});
