import {Chatter} from "@mail/chatter/web_portal/chatter";
import {patch} from "@web/core/utils/patch";
import {_t} from "@web/core/l10n/translation";

patch(Chatter.prototype, {
    async toggleComposer(mode = false) {
        if (mode === "gateway") {
            const thread = this.state.thread;
            const context = {
                default_model: thread.model,
                default_res_ids: [thread.id],
                default_subtype_xmlid: "mail.mt_comment",
                default_wizard_partner_ids: Array.from(
                    new Set(
                        (thread.gateway_followers || []).map((f) => f.id)
                    )
                ),
                default_wizard_channel_ids: Array.from(
                    new Set(
                        (thread.gateway_followers || []).flatMap((f) =>
                            (f.gateway_channels || []).map((c) => c?.id)
                        )
                    )
                ),
            };
            await this.env.services.action.doAction(
                {
                    name: _t("WhatsApp message"),
                    type: "ir.actions.act_window",
                    res_model: "mail.compose.gateway.message",
                    view_mode: "form",
                    views: [[false, "form"]],
                    target: "new",
                    context: context,
                },
                {
                    onClose: () => {
                        thread?.fetchNewMessages?.();
                    },
                }
            );
            return;
        }
        return super.toggleComposer(...arguments);
    },
});
