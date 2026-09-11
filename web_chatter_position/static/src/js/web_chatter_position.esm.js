/*
    Copyright 2023 Camptocamp SA (https://www.camptocamp.com).
    License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).
*/

import {FormCompiler} from "@web/views/form/form_compiler";
import {patch} from "@web/core/utils/patch";
import {append, setAttributes} from "@web/core/utils/xml";
import {SIZES} from "@web/core/ui/ui_service";

patch(FormCompiler.prototype, {
    /**
     * @override
     */
    compile(node, params) {
        const res = super.compile(node, params);
        const webClientViewAttachmentViewHookXml = res.querySelector(
            ".o_attachment_preview"
        );
        const chatterContainerHookXml = res.querySelector(
            ".o-mail-Form-chatter:not(.o-isInFormSheetBg)"
        );
        if (!chatterContainerHookXml) {
            // No chatter, keep the result as it is
            return res;
        }
        const chatterContainerXml = chatterContainerHookXml.querySelector(
            "t[t-component='__comp__.mailComponents.Chatter']"
        );
        // Const chatterParent = chatterContainerXml.parentNode;
        const formSheetBgXml = res.querySelector(".o_form_sheet_bg");
        const parentXml = formSheetBgXml && formSheetBgXml.parentNode;
        if (!parentXml) {
            // Miss-config: a sheet-bg is required for the rest
            return res;
        }

        // Don't patch anything if the setting is "auto": this is the core behaviour
        if (odoo.web_chatter_position === "auto") {
            return res;
            // For "sided", we have to remote the bottom chatter
            // (except if there is an attachment viewer, as we have to force bottom)
        } else if (odoo.web_chatter_position === "sided") {
            setAttributes(chatterContainerXml, {
                isInFormSheetBg: `__comp__.uiService.size < ${SIZES.XXL}`,
                isChatterAside: `__comp__.uiService.size >= ${SIZES.XXL}`,
            });
            // classList.add, NOT setAttributes({class: ...}).
            //
            // `setAttributes` calls `setAttribute("class", ...)`, which REPLACES
            // the whole attribute. Core built this element with
            // `classList.add("o-mail-ChatterContainer", "o-mail-Form-chatter")`,
            // so overwriting it left the chatter with `o-aside` alone — and an
            // element that is no longer `.o-mail-Form-chatter` matches none of
            // the width rules, neither core's nor this module's 30% one.
            //
            // With no width rule the chatter is a plain flex item sized by its
            // content: a short activity note looked roughly right, while a long
            // one grew the chatter to ~73% and squeezed the form sheet to ~27%.
            // That is the "can't see the form" symptom, and it only ever hit
            // users whose Chatter Position preference is "Sided" — which is why
            // it survived the CSS fix.
            chatterContainerHookXml.classList.add("o-aside");
            // For "bottom", we keep the chatter in the form sheet
            // (the one used for the attachment viewer case)
            // If it's not there, we create it.
        } else if (odoo.web_chatter_position === "bottom") {
            if (webClientViewAttachmentViewHookXml) {
                const sheetBgChatterContainerHookXml = res.querySelector(
                    ".o-mail-Form-chatter.o-isInFormSheetBg"
                );
                setAttributes(sheetBgChatterContainerHookXml, {
                    "t-if": "true",
                });
                setAttributes(chatterContainerHookXml, {
                    "t-if": "false",
                });
            } else {
                const sheetBgChatterContainerHookXml =
                    chatterContainerHookXml.cloneNode(true);
                sheetBgChatterContainerHookXml.classList.add("o-isInFormSheetBg");
                setAttributes(sheetBgChatterContainerHookXml, {
                    "t-if": "true",
                    "t-attf-class": `{{ (__comp__.uiService.size >= ${SIZES.XXL} && ${
                        odoo.web_chatter_position !== "bottom"
                    }) ? "o-aside" : "mt-4 mt-md-0" }}`,
                });
                append(formSheetBgXml, sheetBgChatterContainerHookXml);
                const sheetBgChatterContainerXml =
                    sheetBgChatterContainerHookXml.querySelector(
                        "t[t-component='__comp__.mailComponents.Chatter']"
                    );

                setAttributes(sheetBgChatterContainerXml, {
                    isInFormSheetBg: "true",
                });
                setAttributes(chatterContainerHookXml, {
                    "t-if": "false",
                });
            }
        }
        return res;
    },
    compileForm(el, params) {
        const form = super.compileForm(el, params);
        const sheet = form.querySelector(".o_form_sheet_bg");
        if (sheet && odoo.web_chatter_position === "sided") {
            // Same trap as above, on the renderer this time: overwriting `class`
            // dropped `o_form_renderer`, and clearing `t-attf-class` dropped the
            // state classes core puts there (`o_form_editable` / `o_form_readonly`,
            // `o_form_dirty` / `o_form_saved`). Add the row classes instead.
            //
            // Nothing is lost by keeping core's `t-attf-class`: at XXL it already
            // resolves to the same `flex-nowrap h-100`, and below XXL this module
            // puts the chatter inside the sheet, where core's `flex-column` is the
            // layout we want anyway.
            form.classList.add("d-flex", "d-print-block", "flex-nowrap", "h-100");
        }
        return form;
    },
});
