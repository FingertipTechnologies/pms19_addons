import {Chatter} from "@mail/chatter/web_portal/chatter";
import {patch} from "@web/core/utils/patch";

// TEMP diagnostic: confirms this asset is actually loaded into the bundle.
// If you DON'T see this line in the browser console (F12), the module's assets
// were not rebuilt -> run the server with `-u mail_gateway_whatsapp_restrict`
// and hard-refresh (Ctrl+Shift+R). Remove this log once verified.
console.log("[whatsapp-restrict] chatter patch loaded");

// The chatter WhatsApp (gateway) button is rendered with t-if="hasGatewayGroup".
// mail_gateway sets that flag purely from the user's group, so the button shows
// on every model's chatter (tasks, leads, tickets, ...). We want it ONLY on
// Contacts / CRM customer contacts, which are the res.partner model.
//
// hasGatewayGroup is a plain property assigned in mail_gateway's onWillStart
// (`this.hasGatewayGroup = await user.hasGroup(...)`). We turn it into a
// get/set pair: the original boolean is stored on a backing field via the
// setter, and the getter additionally requires the current thread to be a
// res.partner. Optional chaining guards against the thread not being loaded yet.
patch(Chatter.prototype, {
    get hasGatewayGroup() {
        return (
            Boolean(this._gatewayGroupAllowed) &&
            this.state.thread?.model === "res.partner"
        );
    },
    set hasGatewayGroup(value) {
        this._gatewayGroupAllowed = value;
    },
});
