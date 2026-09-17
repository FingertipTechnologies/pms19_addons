/** @odoo-module **/

import { onPatched } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { patch } from "@web/core/utils/patch";

// The forms whose notebook keeps its tab bar still. Both carry the week board
// in a tab, and the board is what makes the problem show: it runs to several
// screens, so it is read scrolled well down the form.
const ANCHORED_MODELS = new Set(["project.project", "qa_testapp.sprint"]);

/** The nearest ancestor that actually scrolls, or the document. */
function scrollParent(el) {
    for (let node = el.parentElement; node; node = node.parentElement) {
        const { overflowY } = getComputedStyle(node);
        if (
            (overflowY === "auto" || overflowY === "scroll") &&
            node.scrollHeight > node.clientHeight
        ) {
            return node;
        }
    }
    return document.scrollingElement;
}

/**
 * Keep the tab bar where it is on screen when switching tabs.
 *
 * Read scrolled down the Tasks board, then click Timesheets: the new page is a
 * fraction of the board's height, the form is suddenly too short to stay
 * scrolled that far, and the browser clamps it — the tab bar dropped down the
 * screen and the header of the form slid back into view on its own. Whoever
 * switched tabs wanted to read the next tab, not the top of the form.
 *
 * So the header's position is noted before the switch and put back after it.
 * Putting it back needs the form to be tall enough to stay scrolled, which a
 * short page is not, so the page area is given a min-height that reaches the
 * bottom of the screen. That is only ever blank space below the page, and it
 * is recomputed on every switch, so it goes away once a tall page is open.
 */
patch(Notebook.prototype, {
    setup() {
        super.setup(...arguments);
        this.tabAnchor = null;
        onPatched(() => {
            const anchor = this.tabAnchor;
            // Still on the page it was taken from: the switch was refused
            // (onWillActivatePage) or has not been drawn yet.
            if (!anchor || anchor.page === this.state.currentPage) {
                return;
            }
            this.tabAnchor = null;
            this.restoreTabAnchor(anchor);
        });
    },

    activatePage(pageIndex) {
        const resModel = this.env.model?.root?.resModel;
        if (ANCHORED_MODELS.has(resModel) && this.state.currentPage !== pageIndex) {
            this.tabAnchor = this.captureTabAnchor();
        }
        return super.activatePage(...arguments);
    },

    captureTabAnchor() {
        const headers = this.activePane.el
            ?.closest(".o_notebook")
            ?.querySelector(":scope > .o_notebook_headers");
        if (!headers) {
            return null;
        }
        return {
            page: this.state.currentPage,
            headers,
            scroller: scrollParent(headers),
            top: headers.getBoundingClientRect().top,
        };
    },

    restoreTabAnchor({ headers, scroller, top }) {
        const content = this.activePane.el?.parentElement;
        if (!content || !headers.isConnected) {
            return;
        }
        content.style.minHeight = "";
        const viewBottom =
            scroller === document.scrollingElement
                ? window.innerHeight
                : scroller.getBoundingClientRect().bottom;
        // How far the page area sits below the tab bar. Both move together
        // when the form scrolls, so this holds before and after the scroll
        // below, and tells where the page area will start once it is done.
        const offset = content.getBoundingClientRect().top - headers.getBoundingClientRect().top;
        const needed = Math.ceil(viewBottom - (top + offset));
        if (needed > content.offsetHeight) {
            content.style.minHeight = `${needed}px`;
        }
        const drift = headers.getBoundingClientRect().top - top;
        if (drift) {
            scroller.scrollTop += drift;
        }
    },
});
