/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { TextField, textField } from "@web/views/fields/text/text_field";
import { useEffect, useState } from "@odoo/owl";

/**
 * Odoo's `text` widget with a hard character limit and a live counter.
 *
 * ft.quote.announcement already refuses to SAVE text longer than
 * TEXT_MAX_LENGTH, but a limit the author only meets after writing three
 * paragraphs and pressing save is a limit they hit as an error rather than as
 * a guide. This stops the textarea at the cap while it is being typed (and
 * truncates an over-long paste, which is what the browser's own `maxlength`
 * does), so the save-time constraint becomes the backstop it was meant to be.
 *
 * Usage:
 *   <field name="text_content" widget="ft_limited_text"
 *          options="{'max_length': 300}"/>
 *
 * `max_length` must be kept in step with the model's own constant — see
 * ft_homepage/models/ft_quote_announcement.py.
 */
export class FtLimitedTextField extends TextField {
    static template = "ft_homepage.LimitedTextField";
    static props = {
        ...TextField.props,
        maxLength: { type: Number, optional: true },
    };
    static defaultProps = {
        ...TextField.defaultProps,
        maxLength: 300,
    };

    setup() {
        super.setup();
        // The record's value only updates when the field is committed (on
        // blur / save), so the counter keeps its own count and follows every
        // keystroke instead.
        this.counter = useState({ length: this.recordLength });
        // ...and resyncs whenever the value changes underneath it — a discard,
        // an onchange, or moving to another record.
        useEffect(
            () => {
                this.counter.length = this.recordLength;
            },
            () => [this.props.record.data[this.props.name]]
        );
    }

    get recordLength() {
        return (this.props.record.data[this.props.name] || "").length;
    }

    get isFull() {
        return this.counter.length >= this.props.maxLength;
    }

    onInput(ev) {
        this.counter.length = ev.target.value.length;
    }
}

export const ftLimitedTextField = {
    ...textField,
    component: FtLimitedTextField,
    displayName: _t("Multiline Text (character limit)"),
    supportedOptions: [
        ...textField.supportedOptions,
        {
            label: _t("Maximum characters"),
            name: "max_length",
            type: "number",
            default: 300,
        },
    ],
    extractProps: (params) => ({
        ...textField.extractProps(params),
        // Left undefined when the option is absent, so defaultProps applies.
        maxLength: params.options?.max_length
            ? Number(params.options.max_length)
            : undefined,
    }),
};

registry.category("fields").add("ft_limited_text", ftLimitedTextField);
