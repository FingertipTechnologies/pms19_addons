import { patch } from "@web/core/utils/patch";
import { treeProcessorService } from "@web/core/tree_editor/tree_processor";
import { DomainSelector } from "@web/core/domain_selector/domain_selector";
import { getDomainDisplayedOperators } from "@web/core/domain_selector/domain_selector_operator_editor";
import { getOperatorEditorInfo } from "@web/core/tree_editor/tree_editor_operator_editor";
import { condition } from "@web/core/tree_editor/condition_tree";

const DATE_TYPES = ["date", "datetime"];

/**
 * Stock operator list for `fieldDef`, with `between` added back for dates.
 *
 * Position matters: `between` goes right after `in range` so the two range
 * operators sit together, and index 0 is left alone so the operator a brand
 * new rule starts with ("is in") does not change.
 */
function operatorsWithBetween(fieldDef) {
    const operators = getDomainDisplayedOperators(fieldDef);
    if (!DATE_TYPES.includes(fieldDef?.type) || operators.includes("between")) {
        return operators;
    }
    const result = [...operators];
    result.splice(operators.indexOf("in range") + 1, 0, "between");
    return result;
}

patch(DomainSelector.prototype, {
    getDefaultOperator(fieldDef) {
        return operatorsWithBetween(fieldDef)[0];
    },

    getOperatorEditorInfo(fieldDef) {
        return getOperatorEditorInfo(operatorsWithBetween(fieldDef), fieldDef);
    },
});

/**
 * Rewrite `in range` + "custom range" conditions on date fields into `between`.
 *
 * `["&", (d, ">=", a), (d, "<=", b)]` is what BOTH forms compile to, so the
 * domain carries no clue as to which one the user picked and core resolves the
 * ambiguity in favour of `in range`. Since this module offers `between` in the
 * dropdown, resolve it the other way round instead - otherwise the editor
 * rebuilds its tree from the domain and snaps the operator back to "is in" as
 * soon as a bound is typed.
 *
 * Nested `any` sub-trees are deliberately left alone: their paths resolve
 * against another model, so `getFieldDef` cannot type them here.
 */
function rewriteCustomRangeToBetween(tree, getFieldDef) {
    if (tree?.type === "connector") {
        return {
            ...tree,
            children: tree.children.map((child) =>
                rewriteCustomRangeToBetween(child, getFieldDef)
            ),
        };
    }
    if (tree?.type !== "condition") {
        return tree;
    }
    const { path, operator, value, negate, isProperty } = tree;
    if (operator !== "in range" || !Array.isArray(value) || value[1] !== "custom range") {
        return tree;
    }
    if (!DATE_TYPES.includes(getFieldDef(path)?.type)) {
        return tree;
    }
    // value is [fieldType, valueType, lowerBound, upperBound] - keep the bounds.
    return condition(path, "between", value.slice(2), negate, isProperty);
}

// Patched through the exported service object rather than a registry lookup:
// importing it declares a real dependency edge, so the loader guarantees
// tree_processor.js has been evaluated by the time this file runs. A
// `registry.category("services").get(...)` here would throw if the bundle ever
// reordered, and a throw at module-definition time takes down the whole
// backend bundle, not just this feature.
patch(treeProcessorService, {
    start() {
        const service = super.start(...arguments);
        const { treeFromDomain, makeGetFieldDef } = service;
        return {
            ...service,
            async treeFromDomain(resModel, domain, distributeNot = true) {
                const tree = await treeFromDomain(resModel, domain, distributeNot);
                const getFieldDef = await makeGetFieldDef(resModel, tree);
                return rewriteCustomRangeToBetween(tree, getFieldDef);
            },
        };
    },
});
