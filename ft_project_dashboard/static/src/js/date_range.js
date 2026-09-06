/** @odoo-module **/

/**
 * The named date ranges the board offers, and the one function that turns a
 * name into a pair of dates.
 *
 * Extracted from project_dashboard.js when the project form's Analysis tab
 * started offering the same ranges. Two copies of this switch would have meant
 * "This Quarter" could quietly come to mean two different things on two screens
 * reading the same figures off the same server methods — the exact failure the
 * dashboard's single header was built to avoid.
 */
export const PERIODS = [
    { id: "today", label: "Today" },
    { id: "week", label: "This Week" },
    { id: "month", label: "This Month" },
    { id: "last_month", label: "Last Month" },
    { id: "last_two_months", label: "Last Two Months" },
    { id: "last_30_days", label: "Last 30 Days" },
    { id: "last_60_days", label: "Last 60 Days" },
    { id: "last_90_days", label: "Last 90 Days" },
    { id: "quarter", label: "This Quarter" },
    { id: "year", label: "This Year" },
    // No date bounds at all — the whole history of every project. The board
    // otherwise always had a range applied, with no way to step back and see a
    // project end to end. The server already accepts null dates everywhere, so
    // this is simply the absence of the two leaves rather than a special case.
    { id: "all", label: "All Time" },
    { id: "custom", label: "Custom" },
];

/** -> 'YYYY-MM-DD' in local time. */
export function fmt(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

/**
 * The bounds for a named period, as `{ dateFrom, dateTo }` ISO date strings.
 *
 * `current` supplies the dates already in the custom inputs; "custom" is the
 * one period that keeps whatever is there rather than computing anything, and
 * "all" is the one that returns both bounds null.
 */
export function computeRange(period, current = {}) {
    const now = new Date();
    let from = null;
    let to = fmt(now);
    switch (period) {
        case "today":
            from = fmt(now);
            break;
        case "week": {
            const d = new Date(now);
            const day = (d.getDay() + 6) % 7; // Monday = 0
            d.setDate(d.getDate() - day);
            from = fmt(d);
            break;
        }
        case "month":
            from = fmt(new Date(now.getFullYear(), now.getMonth(), 1));
            break;
        case "last_month":
            from = fmt(new Date(now.getFullYear(), now.getMonth() - 1, 1));
            to = fmt(new Date(now.getFullYear(), now.getMonth(), 0));
            break;
        case "last_two_months":
            from = fmt(new Date(now.getFullYear(), now.getMonth() - 2, 1));
            to = fmt(new Date(now.getFullYear(), now.getMonth(), 0));
            break;
        case "last_30_days":
        case "last_60_days":
        case "last_90_days": {
            const days = parseInt(period.match(/\d+/)[0], 10);
            const d = new Date(now);
            d.setDate(d.getDate() - (days - 1));
            from = fmt(d);
            break;
        }
        case "quarter": {
            const q = Math.floor(now.getMonth() / 3);
            from = fmt(new Date(now.getFullYear(), q * 3, 1));
            break;
        }
        case "year":
            from = fmt(new Date(now.getFullYear(), 0, 1));
            break;
        case "all":
            // Both ends open. `to` is reset as well as `from`, since it
            // defaults to today above and would otherwise still cut off
            // anything dated in the future — deadlines especially.
            from = null;
            to = null;
            break;
        case "custom":
            // Keep whatever is already in the custom inputs.
            from = current.dateFrom || null;
            to = current.dateTo || null;
            break;
    }
    return { dateFrom: from, dateTo: to };
}
