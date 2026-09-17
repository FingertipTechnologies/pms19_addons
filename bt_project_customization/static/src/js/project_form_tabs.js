import { onMounted, onPatched, onWillUnmount, useRef } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

/**
 * Publishes the project form's status bar height as a CSS variable, so the
 * sticky tab bar in project_form_tabs.scss can stop right underneath it.
 *
 * Core pins the status bar (Started / Working / Completed / CLOSED) to the top
 * of the area the form scrolls in, above everything else. A tab bar pinned to
 * the same top: 0 sticks behind it and never shows. The status bar's height
 * is not a constant — it depends on the screen width, the zoom and how many
 * buttons wrap onto a second line — so it is measured, and measured again
 * whenever it changes size, rather than written into the stylesheet.
 *
 * Only on the project form (the o_form_project_project class core gives its
 * arch); every other form is left alone.
 */
patch(FormRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        const rootRef = useRef("compiled_view_root");
        let observed = null;
        let observer = null;

        const track = () => {
            const root = rootRef.el;
            if (!root || !root.closest(".o_form_project_project")) {
                return;
            }
            const statusbar = root.querySelector(".o_form_statusbar");
            if (statusbar === observed) {
                return;
            }
            observer?.disconnect();
            observed = statusbar;
            if (!statusbar) {
                root.style.removeProperty("--ft-form-statusbar-height");
                return;
            }
            observer = new ResizeObserver(() => {
                root.style.setProperty(
                    "--ft-form-statusbar-height",
                    `${statusbar.getBoundingClientRect().height}px`
                );
            });
            observer.observe(statusbar);
        };

        onMounted(track);
        // The status bar node can be replaced by a re-render (another record
        // through the pager, a stage change); pick the new one up.
        onPatched(track);
        onWillUnmount(() => observer?.disconnect());
    },
});
