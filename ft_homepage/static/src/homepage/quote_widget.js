/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { AppsMenu } from "@web_responsive/components/apps_menu/apps_menu.esm";

// The footer shows at most this many media posts. The server refuses to
// activate a fifth (ft.quote.announcement.MAX_ACTIVE_MEDIA), so this is a
// backstop for data that predates that rule rather than the rule itself —
// keep the two numbers in step.
const MAX_FOOTER_POSTS = 4;

/**
 * Shared data and helpers for the two Homepage widgets.
 *
 * The split is by CONTENT TYPE, not by `kind`: every text entry goes to the
 * panel beside the app icons whether it was recorded as a Quote, an
 * Announcement or an Org-wide Update, and every media entry goes to the
 * footer. Routing on `kind` used to send a text Quote to the footer marquee
 * and a text Announcement to the panel, so where a quote appeared depended on
 * a dropdown the author had no reason to connect with placement.
 *
 * They are two components rendered in two places over the same set of records
 * rather than one component owning both, because the panel and the footer sit
 * at different points in web_responsive's template.
 */
class FtHomepageContent extends Component {
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({ items: [], loaded: false });

        onWillStart(async () => {
            try {
                const items = await this.orm.call(
                    "ft.quote.announcement",
                    "get_homepage_content",
                    []
                );
                this.state.items = Array.isArray(items) ? items : [];
            } catch (e) {
                // Never let these widgets break the Homepage for any user.
                console.warn("ft_homepage: could not load quote/announcement", e);
                this.state.items = [];
            }
            this.state.loaded = true;
        });
    }

    /**
     * Every text entry, for the panel beside the app icons — regardless of
     * whether it is a Quote, an Announcement or an Org-wide Update.
     */
    get panelItems() {
        return this.state.items.filter((item) => item.content_type === "text");
    }

    /** Image/video/social entries — the cards in the footer, max 4. */
    get posts() {
        return this.state.items
            .filter((item) => item.content_type !== "text")
            .slice(0, MAX_FOOTER_POSTS);
    }

    isYoutube(item) {
        const url = item.video_url;
        return !!url && (url.includes("youtube.com") || url.includes("youtu.be"));
    }

    youtubeEmbedUrl(item) {
        const url = item.video_url;
        let videoId = "";
        if (url.includes("youtu.be/")) {
            videoId = url.split("youtu.be/")[1];
        } else if (url.includes("v=")) {
            videoId = url.split("v=")[1];
        }
        videoId = videoId ? videoId.split("&")[0].split("?")[0] : "";
        // autoplay=1 starts the video immediately; browsers only allow
        // autoplay when muted (mute=1). loop needs the playlist param.
        return `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=1&loop=1&playlist=${videoId}`;
    }
}

/** Quotes/posts row, rendered as the Homepage footer. */
export class FtQuoteWidget extends FtHomepageContent {
    static template = "ft_homepage.QuoteWidget";
}

/** Announcements panel, rendered to the right of the app icons grid. */
export class FtAnnouncementsPanel extends FtHomepageContent {
    static template = "ft_homepage.AnnouncementsPanel";
}

// Register both as child components of web_responsive's AppsMenu so they can
// be rendered inside its template (see quote_widget.xml).
patch(AppsMenu, {
    components: { ...AppsMenu.components, FtQuoteWidget, FtAnnouncementsPanel },
});
