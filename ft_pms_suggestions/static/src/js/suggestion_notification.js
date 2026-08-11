/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

// Must match BUS_NOTIFICATION_TYPE in models/pms_suggestion.py.
const NEW_SUGGESTION = "ft_pms_suggestions.new_suggestion";

/**
 * Shows a top-right popup when somebody submits a PMS suggestion.
 *
 * The server only pushes this notification to the administrators and to the
 * logins configured in the `ft_pms_suggestions.notify_logins` system
 * parameter, so there is no recipient filtering to do here: anything that
 * arrives on the bus was addressed to the current user.
 */
export const suggestionNotificationService = {
    dependencies: ["action", "bus_service", "notification"],

    start(env, { action, bus_service, notification }) {
        bus_service.subscribe(NEW_SUGGESTION, (payload) => {
            if (!payload || !payload.id) {
                return;
            }

            // Built as plain text, not markup: the title is free text typed
            // by an employee, and the notification renders its message with
            // t-out, which escapes a plain string.
            let message = [payload.name, payload.title]
                .filter(Boolean)
                .join(" — ");
            if (payload.author) {
                message += _t(" (by %s)", payload.author);
            }

            const close = notification.add(message, {
                title: _t("New Suggestion Submitted"),
                type: "info",
                // Sticky: a suggestion is waiting on a decision, so the popup
                // stays until it is acted on rather than vanishing after the
                // default four seconds.
                sticky: true,
                buttons: [
                    {
                        name: _t("Open"),
                        primary: true,
                        onClick: () => {
                            close();
                            action.doAction({
                                type: "ir.actions.act_window",
                                res_model: "pms.suggestion",
                                res_id: payload.id,
                                views: [[false, "form"]],
                                target: "current",
                            });
                        },
                    },
                ],
            });
        });
    },
};

registry
    .category("services")
    .add("ft_pms_suggestions.notification", suggestionNotificationService);
