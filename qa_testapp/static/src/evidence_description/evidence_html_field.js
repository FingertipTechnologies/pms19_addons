/** @odoo-module **/

import { useExternalListener } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { HtmlField, htmlField } from "@html_editor/fields/html_field";

/**
 * Evidence Description field.
 *
 * A thin extension of the standard Html field: typing and pasting behave
 * exactly as the stock editor, so pasting a screenshot keeps working and the
 * image persists with the record. Two additions only:
 *   - pasted images are shrunk to a small icon via scoped CSS (see evidence.scss);
 *   - clicking an image opens it full size in Odoo's file viewer.
 *
 * Nothing in the editor internals is touched — the preview is driven purely by
 * a delegated click on rendered <img> elements inside this field.
 */
export class EvidenceHtmlField extends HtmlField {
    setup() {
        super.setup();
        this.fileViewer = useFileViewer();
        // Capture phase so the preview opens before the editor claims the click.
        // Only acts on images inside THIS field, and only when the field is
        // readonly (i.e. viewing the bug) — in edit mode the editor's own image
        // tools stay in charge.
        useExternalListener(document, "click", this.onEvidenceClick, { capture: true });
    }

    onEvidenceClick(ev) {
        if (!this.props.readonly) {
            return;
        }
        const img = ev.target;
        if (!img || img.tagName !== "IMG") {
            return;
        }
        if (!img.closest(`.o_field_widget[name='${this.props.name}']`)) {
            return;
        }
        const src = img.getAttribute("src");
        if (!src) {
            return;
        }
        ev.preventDefault();
        // FileViewer only needs these getters; a plain object is enough for a
        // single inline image whose source we already have.
        const file = {
            isImage: true,
            isViewable: true,
            defaultSource: src,
            downloadUrl: src,
            displayName: img.getAttribute("alt") || "Image",
            mimetype: "image/png",
        };
        this.fileViewer.open(file, [file]);
    }
}

export const evidenceHtmlField = {
    ...htmlField,
    component: EvidenceHtmlField,
};

registry.category("fields").add("qa_evidence_html", evidenceHtmlField);
