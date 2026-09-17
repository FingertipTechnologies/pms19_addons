/** @odoo-module **/

import { Component, onMounted, onPatched, useRef, useState } from "@odoo/owl";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSortable } from "@web/core/utils/sortable_owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// A column with no record behind it — "No Week" on the project board. Carried
// as a string because it has to survive a trip through a DOM dataset, where
// false would come back as the string "false" and 0 is a legitimate id.
const NO_COLUMN = "none";

// The form records whose current week has already been scrolled to. Held
// outside the component because the component does not survive a tab switch:
// the notebook builds a page only while its tab is open, so every return to
// the Tasks tab mounts a fresh board, and a flag on the instance scrolled the
// page back to this week each time — the tab bar went with it. Keyed on the
// record object, so it lasts as long as the form has that record open and is
// garbage collected with it.
const revealedRecords = new WeakSet();

// Board payloads already fetched, by model, record and request.
//
// Paging from one week to the next waited on two round trips back to back —
// the form's own read, then this board's — and showed the previous week's
// columns until the second came in. So each board, once loaded, fetches the
// weeks either side of it in the background, and a page turn draws from here
// the moment the form lands on the record. Held at module level because the
// board component is rebuilt on every page turn.
//
// An entry younger than BOARD_CACHE_FRESH_MS is shown without asking again; an
// older one is shown at once and then replaced by a fresh answer. Anything
// that writes a task — a drop above all — clears the lot, because one card
// moving changes two columns and possibly two weeks.
const boardCache = new Map();
const BOARD_CACHE_FRESH_MS = 15000;
const BOARD_CACHE_SIZE = 24;

function boardCacheKey(resModel, resId, kwargs) {
    return JSON.stringify([resModel, resId, kwargs]);
}

function rememberBoard(key, entry) {
    // Re-inserted so the Map's order is least recently used first.
    boardCache.delete(key);
    boardCache.set(key, entry);
    while (boardCache.size > BOARD_CACHE_SIZE) {
        boardCache.delete(boardCache.keys().next().value);
    }
}

/**
 * A task board with drag and drop, drawn inside a form.
 *
 * Serves both boards in this module:
 *   - on a Week, one column per stage (a drop writes stage_id);
 *   - on a Project, one column per week (a drop writes sprint_id, and
 *     project.task then moves the deadline to that week's Sunday).
 *
 * Odoo cannot do this on its own: an x2many field is backed by a StaticList,
 * which has no grouping whatsoever, and the Kanban renderer decides whether to
 * draw columns and whether cards may be dragged from `list.isGrouped`. A plain
 * <kanban> in a form tab therefore yields one flat grid of cards.
 *
 * Both the columns and the field a drop writes come from the record's own
 * get_board_data(). Nothing about either board is encoded here — this
 * component renders what it is given and writes what it is told to.
 */
export class WeekTaskBoard extends Component {
    static template = "ft_sprint_management.WeekTaskBoard";
    static props = {
        ...standardFieldProps,
        // Name of a field on the same record holding a project to narrow the
        // board to. Set on the Week, where it is the Project selector above
        // the board; unset on the Project, whose board is one project already.
        filterField: { type: String, optional: true },
        // Fetch the boards of the records either side of this one in the
        // pager, so turning the page draws at once. Set on the Week form only:
        // a project's board provisions weeks as it is read, which is not
        // something to do for a project nobody has opened.
        prefetchPager: { type: Boolean, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            columns: [],
            field: null,
            showStage: false,
            showProject: false,
            loaded: false,
        });
        this.rootRef = useRef("root");
        // Sequence number for board loads; see loadBoard.
        this.loadToken = 0;
        // Column keys whose "+ N more" has been clicked, and the record they
        // were clicked on. Kept here rather than in state: nothing renders
        // from the set itself, the board is redrawn from the server's answer.
        // Kept across reloads of the same record so a drag and drop does not
        // fold a column somebody had just opened out, and dropped when the
        // record changes because W36's Completed column is not W35's.
        this.expandedColumns = new Set();
        this.expandedRecordId = null;
        // The board is a calendar running from the project's first deadline to
        // four weeks out, so on any project with history behind it the week
        // being worked is rows below the fold and the tab opened on weeks that
        // are already over. It is scrolled to ONCE per record (see
        // revealedRecords): a drag and drop reloads the board and a tab switch
        // remounts it, and yanking the page back after either would take the
        // board away from whoever was using it.

        // The scroll cannot be done from loadBoard: the columns it puts in
        // state have not been rendered when it returns, so there is no element
        // to scroll to yet. Done on the patch that draws them instead — and on
        // mount, which is where it actually fires, because the form's notebook
        // builds a page only when its tab is opened.
        onMounted(() => this.revealCurrentWeek());
        onPatched(() => this.revealCurrentWeek());

        // The board is drawn from an RPC, not from the field's own value, so
        // nothing redraws it when the record underneath changes. That is felt
        // the moment a Week is moved between one project and All Projects: the
        // columns are still the old project's until the page is reloaded by
        // hand.
        //
        // Observed rather than reloaded on every render: the effect subscribes
        // only to the values read below, so a re-render on its own costs no
        // round trip, and the first run replaces the onWillStart this used to
        // do. The task ids are what actually change when the record is saved,
        // and the Project filter is what changes without any save at all — so
        // between them they are the signal that the board has something new to
        // show.
        useRecordObserver(async (record) => {
            // Keep the Project filter for as long as this week stays open. It
            // is not stored, so every reload — the one after a drag and drop
            // above all — used to compute it empty and jump the board to All
            // Projects. Written into the form's own context, it is sent with
            // each of those reloads and comes back unchanged (see
            // _compute_board_project_id). The context belongs to this form
            // only: leaving the week and coming back starts a new one, at All
            // Projects.
            if (this.props.filterField) {
                record.context.ft_week_board_project_id = this.filterProjectId(record);
            }
            const signal = JSON.stringify([
                record.resId,
                this.filterProjectId(record),
                this.taskIds(record),
            ]);
            if (signal === this.boardSignal) {
                return;
            }
            this.boardSignal = signal;
            // The record handed in, never this.props.record. On a page turn
            // the observer runs from onWillUpdateProps, while this.props still
            // holds the week being LEFT: reading it there fetched the previous
            // week's board and drew it under the new week's Task Summary —
            // W40 showing W39's empty columns — until something else happened
            // to reload the board.
            await this.loadBoard(record);
        });

        useSortable({
            ref: this.rootRef,
            elements: ".o_week_card",
            groups: ".o_week_column",
            connectGroups: true,
            cursor: "move",
            placeholderClasses: ["o_week_card_placeholder"],
            // Flags a drag in progress so the card's own click handler cannot
            // take the end of it for a click and open the task page on top of
            // the week. Cleared on the next tick, after that click has fired.
            onDragStart: () => {
                this.dragging = true;
            },
            onDragEnd: () => {
                setTimeout(() => {
                    this.dragging = false;
                });
            },
            onDrop: (params) => this.onCardDropped(params),
        });
    }

    get recordId() {
        return this.props.record.resId;
    }

    /** The ids behind the field, whichever shape the record holds them in. */
    taskIds(record) {
        const value = record.data[this.props.name];
        return Array.isArray(value) ? value : value?.currentIds || [];
    }

    /**
     * The project the board is filtered to, or false for all of them.
     *
     * Read from the record and sent with every board request rather than left
     * for the server to look up: the field behind it is not stored, so a read
     * on the server would only ever compute it empty.
     */
    filterProjectId(record) {
        if (!this.props.filterField) {
            return false;
        }
        return record.data[this.props.filterField]?.id || false;
    }

    async loadBoard(record = this.props.record) {
        // An unsaved record has no id to read tasks for, and nothing to show.
        if (!record.resId) {
            this.state.columns = [];
            this.state.loaded = true;
            return;
        }
        // Which load this is. Paging through weeks fires one load per record,
        // and two requests in flight come back in whatever order the server
        // and the network settle on — not the order they were sent. Without
        // this the LAST response to arrive won, so landing on a week could
        // leave the previous week's columns under the current week's Task
        // Summary: the two disagreed on screen, and the board was the half
        // that was wrong.
        const token = ++this.loadToken;
        const recordId = record.resId;
        // The same record loading again means something on it changed — a
        // save, a drop, the Project filter — so the cache is no answer for it.
        // A different record is a page turn, which is what the cache is for.
        const sameRecord = recordId === this.expandedRecordId;
        if (!sameRecord) {
            this.expandedColumns.clear();
            this.expandedRecordId = recordId;
        }
        const kwargs = this.boardKwargs(record, [...this.expandedColumns]);
        const resModel = record.resModel;
        const cached = boardCache.get(boardCacheKey(resModel, recordId, kwargs));
        if (cached?.data && !sameRecord) {
            this.applyBoard(cached.data);
            if (Date.now() - cached.time < BOARD_CACHE_FRESH_MS) {
                this.prefetchNeighbours(record);
                return;
            }
        }
        const data = await this.fetchBoard(resModel, recordId, kwargs, {
            fresh: sameRecord,
        });
        // A newer load started while this one was in flight. Its answer is the
        // one that matches what is on screen, so this one is dropped.
        if (token !== this.loadToken) {
            return;
        }
        this.applyBoard(data);
        this.prefetchNeighbours(record);
    }

    /** What get_board_data is asked for, for this record. */
    boardKwargs(record, expandedKeys) {
        const kwargs = {
            expanded_column_ids: expandedKeys.map((key) =>
                key === NO_COLUMN ? false : parseInt(key, 10)
            ),
        };
        if (this.props.filterField) {
            kwargs.project_id = this.filterProjectId(record);
        }
        return kwargs;
    }

    /**
     * get_board_data, through the cache.
     *
     * A request already in flight for the same board is joined rather than
     * sent twice — which is what a page turn does when it lands on a week
     * whose background fetch has not come back yet. `fresh` skips both the
     * stored answer and the one in flight, since either may predate a write.
     */
    fetchBoard(resModel, resId, kwargs, { fresh = false } = {}) {
        const key = boardCacheKey(resModel, resId, kwargs);
        const entry = boardCache.get(key);
        if (entry?.promise && !fresh) {
            return entry.promise;
        }
        const promise = this.orm
            .call(resModel, "get_board_data", [[resId]], kwargs)
            .then(
                (data) => {
                    if (boardCache.get(key)?.promise === promise) {
                        rememberBoard(key, { data, time: Date.now() });
                    }
                    return data;
                },
                (error) => {
                    if (boardCache.get(key)?.promise === promise) {
                        boardCache.delete(key);
                    }
                    throw error;
                }
            );
        rememberBoard(key, { ...entry, promise });
        return promise;
    }

    /**
     * Fetch the boards of the previous and next record in the pager.
     *
     * In the background and silently: a failure here costs nothing but the
     * head start, and the page turn fetches the board the ordinary way.
     */
    prefetchNeighbours(record) {
        const resIds = this.props.prefetchPager ? record.resIds || [] : [];
        const index = resIds.indexOf(record.resId);
        if (index < 0) {
            return;
        }
        // Neighbours open with no column expanded: expandColumns is cleared
        // whenever the record changes.
        const kwargs = this.boardKwargs(record, []);
        for (const resId of [resIds[index + 1], resIds[index - 1]]) {
            if (!resId) {
                continue;
            }
            const entry = boardCache.get(boardCacheKey(record.resModel, resId, kwargs));
            if (entry?.promise || (entry && Date.now() - entry.time < BOARD_CACHE_FRESH_MS)) {
                continue;
            }
            this.fetchBoard(record.resModel, resId, kwargs).catch(() => {});
        }
    }

    applyBoard(data) {
        this.state.field = data.field;
        this.state.showStage = data.show_stage;
        this.state.showProject = data.show_project;
        this.state.columns = data.columns;
        this.state.loaded = true;
    }

    /**
     * Bring the current week on screen, once per open record.
     *
     * `block: "center"` rather than "nearest": the columns wrap onto as many
     * rows as they need, so the week before this one is the row above and the
     * week after is the row below, and centring is what puts both within a
     * scroll of where the reader lands. Anchored on the column HEADING, not on
     * the column, because a column runs to 60vh — centring the box itself
     * would put its middle on screen and the week's name off the top of it.
     */
    revealCurrentWeek() {
        const record = this.props.record;
        if (!this.recordId || revealedRecords.has(record)) {
            return;
        }
        const heading = this.rootRef.el?.querySelector(
            ".o_week_column_current .o_week_column_header"
        );
        // No board drawn yet, or a board with no current week on it (a Week's
        // own stage columns). Left unmarked so the next patch can try again.
        if (!heading) {
            return;
        }
        revealedRecords.add(record);
        heading.scrollIntoView({ block: "center", inline: "nearest" });
    }

    /**
     * "+ N more" was clicked: draw that column in full from now on.
     *
     * A reload rather than a second fetch spliced into the column: the server
     * is the only thing that knows the order the cards come in, and the same
     * request already draws the board — asking it again with one more column
     * marked expanded keeps one code path and one answer.
     */
    async expandColumn(columnKey) {
        this.expandedColumns.add(columnKey);
        await this.loadBoard();
    }

    /** Serialises a column id for the DOM. @see NO_COLUMN */
    columnKey(columnId) {
        return columnId ? String(columnId) : NO_COLUMN;
    }

    columnByKey(key) {
        return this.state.columns.find((col) => this.columnKey(col.id) === key);
    }

    /** The column a card is currently drawn in, so a no-op drop writes nothing. */
    columnOfCard(taskId) {
        const column = this.state.columns.find((col) =>
            col.cards.some((card) => card.id === taskId)
        );
        return column ? this.columnKey(column.id) : null;
    }

    async onCardDropped({ element, parent }) {
        if (!parent) {
            return;
        }
        const taskId = parseInt(element.dataset.taskId, 10);
        const columnKey = parent.dataset.columnId;
        if (!taskId || !columnKey || this.columnOfCard(taskId) === columnKey) {
            return;
        }
        // A column can refuse drops. "No Week" on the project board does:
        // membership there means the deadline falls in no defined week, and a
        // drop has no deadline to derive — clearing one is a deliberate act
        // for the task form, not a side effect of a drag. The card springs
        // back on its own, because the sortable hook does not move the DOM.
        const target = this.columnByKey(columnKey);
        if (target && target.droppable === false) {
            return;
        }
        const value = columnKey === NO_COLUMN ? false : parseInt(columnKey, 10);
        await this.orm.write("project.task", [taskId], { [this.state.field]: value });
        // Every board held may count this task, not just this one.
        boardCache.clear();
        await this.loadBoard();
        // Reload the record the board sits on, so the figures around it move
        // with the card: a Week's Task Summary and Hour Tracking are computed
        // on read and not stored, so without this they would keep showing what
        // they showed before the drag until the page was reloaded by hand.
        await this.props.record.load();
        this.props.record.model.notify();
    }

    openTask(taskId) {
        // The click that ends a drag and drop is not a request to open the task.
        if (this.dragging) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "project.task",
            res_id: taskId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

export const weekTaskBoard = {
    component: WeekTaskBoard,
    supportedTypes: ["many2many", "one2many"],
    extractProps: ({ options }) => ({
        filterField: options.filter_field,
        prefetchPager: Boolean(options.prefetch_pager),
    }),
    supportedOptions: [
        {
            label: "Filter field",
            name: "filter_field",
            type: "field",
            availableTypes: ["many2one"],
        },
        {
            label: "Prefetch pager neighbours",
            name: "prefetch_pager",
            type: "boolean",
        },
    ],
};

registry.category("fields").add("week_task_board", weekTaskBoard);
