/** @odoo-module **/
import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

registry.category("services").add("qa_testapp.bug_notifications", {
    dependencies: ["orm", "notification", "action", "bus_service"],
    start(env, { orm, notification, action, bus_service }) {
        const displayed = new Set();
        let loading = false;
        async function refresh() {
            if (loading) return;
            loading = true;
            try {
                const items = await orm.call("qa_testapp.bug_notification", "pending_popups", []);
                for (const item of items) {
                    if (displayed.has(item.id)) continue;
                    displayed.add(item.id);
                    const dismiss = () => orm.call("qa_testapp.bug_notification", "dismiss_popup", [[item.id]])
                        .catch(() => displayed.delete(item.id));
                    const close = notification.add(item.message, {
                        title: item.title || (item.kind === "fixed" ? _t("Bug fixed — please verify") : _t("Bug assigned to you")),
                        type: "info", sticky: true,
                        onClose: dismiss,
                        buttons: [{ name: _t("Open Bug"), primary: true, onClick: async () => {
                            await action.doAction({ type: "ir.actions.act_window", res_model: "qa_testapp.ticket",
                                res_id: item.ticket_id, views: [[false, "form"]], target: "current" });
                            await dismiss();
                            close();
                        }}],
                    });
                }
            } catch (error) {
                // Retry on reconnect/focus; never prevent the web client from opening.
            } finally { loading = false; }
        }
        bus_service.subscribe("qa_testapp.bug_notification", refresh);
        window.addEventListener("focus", refresh);
        window.setInterval(refresh, 60000);
        refresh();
    },
});
