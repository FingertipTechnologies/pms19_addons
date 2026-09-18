{
    'name': 'Week Management',
    # 19.0.2.0.0 turns Sprints into Weeks. Bumped because the upgrade has to
    # run: project.task gains two stored columns (sprint_start_date,
    # sprint_end_date) and the pre-migration snaps every existing week onto a
    # Monday. Odoo compares the installed version against this one, so leaving
    # it alone would leave a database without the new columns, and selecting
    # them would raise UndefinedColumn.
    # 19.0.2.1.0 replaces the Tasks tab's list with a real stage board.
    # 19.0.2.2.0 sizes that board off the stock Kanban's own metrics, so the
    # columns span the screen instead of sitting narrow against the left edge.
    # 19.0.2.3.0 puts the same board on the project's Tasks tab, with one
    # column per week instead of per stage. Dragging a card there writes the
    # Week, and the deadline follows to that week's Sunday.
    # 19.0.2.4.0 keeps the board inside its own box. Its columns are wider
    # than the tab, and a flex item will not shrink below its content, so the
    # field grew to fit them and scrolled the whole form sideways with it.
    # 19.0.2.5.0 dresses the board cards like stock Kanban records: tags,
    # assignee avatars, a relative deadline that reddens when overdue, the
    # priority star, and finished work faded out.
    # 19.0.2.6.0 places a task in the week its DEADLINE falls in, not the week
    # it is linked to, so the backlog lands in its weeks unaided and the
    # columns agree with the Week form's own counts.
    # 19.0.2.7.0 dresses the board like the All Tasks board grouped by
    # deadline week: big column headings over a completion bar and a count,
    # module under the title, priority as a three-star scale.
    # 19.0.3.0.0 stops anybody having to create a week. A deadline brings its
    # week into being, and the week is named after its ISO week the way Odoo
    # names its own week groups — W40 2025. The post-migration renames the
    # weeks that exist and provisions the ones the backlog needs.
    # 19.0.3.0.1 makes the board fill the width of its tab. It was sizing to
    # its content and leaving the rest of the tab empty beside it.
    # 19.0.3.1.0 lets a week leave Project empty, meaning All Projects: the
    # summary and the board then cover every project at once, and the cards
    # name the project they came from.
    # 19.0.3.2.0 keeps sprint_id in step with the deadline. The Tasks-tab
    # board groups by deadline while the full-screen Kanban can only group by
    # a stored column, so an empty link put the whole backlog in None on one
    # board and in its proper weeks on the other.
    # 19.0.3.3.0 puts All Projects in the Project dropdown. The empty value
    # always meant it, but it could only be reached by deleting the text in
    # the field, so nobody found it — and a week left blank read as unfilled
    # rather than as covering everything.
    # 19.0.3.4.0 numbers the weeks continuously — W52 is followed by W53,
    # not by W1 of the next year — so the name carries no year, drops the
    # week's Status (an All Projects week spans projects at four different
    # stages, so none of them was ever true of it), and opens the Weeks list
    # on the All Projects rows: one row per week, counting the whole company.
    # The migrations renumber the existing weeks and drop the status column,
    # which was NOT NULL and would have refused every new week once the field
    # was gone.
    # 19.0.4.0.0 makes a week one record for the whole company. It used to be
    # cut into a copy per project plus an All Projects copy, so W41 was four
    # rows carrying a quarter of the work each. The project belongs to the
    # tasks inside the week, chosen per line in Assigned Tasks and printed on
    # every card of the board. The pre-migration merges the copies, moves the
    # tasks onto the surviving week and drops project_id from the table.
    # 19.0.4.1.0 gives the week back its Project field, as what it should
    # always have been: a filter. Picking one narrows the summary and the
    # board below to that project; empty means all of them. It is not stored,
    # so it is nobody else's filter, needs no save, and leaves the Weeks list
    # counting every project. The list itself is back to four columns, with
    # the rest of the summary under the column picker.
    # 19.0.4.2.0 starts the count at the first week of 2026: W1 is the week
    # of 29 December 2025, and January 2027 carries on at W54 rather than
    # going back to W1. Weeks from before 2026 are outside the count and keep
    # their ISO name, year and all, instead of the zero and negative numbers
    # the arithmetic would give them.
    # 19.0.4.3.0 stops the Week board drawing a stage twice. A
    # project.task.type is per-project, not global, so a PMS carries several
    # distinct rows all named Planned (project_task_default_stage attaches its
    # own eight to every new project, core's name_create adds a "New", and a
    # column added in any project's kanban adds one more). The board searched
    # those names and drew a column per ROW. It now draws one per NAME, and the
    # post-migration merges the duplicate rows into the four canonical stages.
    # The same version fixes the board disagreeing with the Task Summary above
    # it: board data comes from its own RPC, two of which could be in flight at
    # once when paging between weeks, and the response that arrived last won
    # rather than the one that was asked for last.
    # 19.0.4.4.0 takes the Stage Owner back off those four stages. They are
    # global by design — no project_ids, so every project can share them —
    # and project.task.type.user_id defaults to `not default_project_id in
    # context and env.uid`, so creating them on install stamped OdooBot as
    # their owner, which _compute_user_id only ever clears for stages that
    # HAVE projects. An owned stage is a personal one, and core guards those
    # with a rule carrying no groups — global, so ANDed for Administrators
    # too: [('user_id', 'in', (False, user.id))]. The four were therefore
    # unreadable by every real user, and so was any task sitting in one; the
    # 19.0.4.3.0 merge, which moves the duplicates' tasks onto exactly these
    # rows, is what put most of the PMS in them. The same version makes the
    # board's "+ N more" do something: it was a caption under the 40 cards a
    # column is capped at, and is now a button that redraws that one column in
    # full, remembered across drag-and-drop reloads of the same record. And
    # it gives the week a Status again, for one project at a time: with the
    # Project filter set, the status bar shows how far that project's work
    # for the week has got, read off its tasks — Completed when every one is,
    # otherwise the earliest stage one is still in. All Projects shows none,
    # for the reason 19.0.3.4.0 dropped the stored one.
    # 19.0.4.5.0 leaves the PMS with exactly four task stages. The
    # end-migration moves the tasks of every other stage: Sandbox Review and
    # anything with Testing in its name to Testing, the rest to Working. It
    # then links every project to the four and removes the other stages. New
    # projects, including ones typed into a task's Project field, get the four
    # instead of OCA's case_default set or core's "New". Nobody can add a
    # stage any more: "Add column" is hidden on every task Kanban (project,
    # My Tasks, To-do, portal) and on Task Stages, and project.task.type
    # refuses a create outside superuser mode. The boards wrap their columns
    # onto more rows instead of scrolling sideways, so every week a project has
    # work in is on screen — No Week and the earlier weeks included — just as
    # All Tasks grouped by deadline week lists them. A Week's four stage
    # columns stretch across the whole tab, and a project's boards always carry
    # the current week and the four after it, empty or not, so the coming weeks
    # can be planned by dragging tasks into them.
    # 19.0.4.6.0 makes the Week field read-only on the task form. The week is
    # set from the Deadline and by dragging the task on the week boards; the
    # form only shows it. View change only, no migration.
    # 19.0.4.7.0 takes New, Save and Discard off the Week form. Weeks are
    # created on their own from task deadlines, so New is gone from the Week
    # list and kanban too, and Start Date is read-only on the form. The Project
    # selector is a filter that is not stored, yet changing it brought up Save
    # and Discard; the form now uses the ft_week_form view, which leaves them
    # out. View and JS change only, no migration.
    # 19.0.4.8.0 keeps the Week's Project filter. It was computed empty on
    # every read, so dragging a card to another stage, clicking a button or
    # paging to the next week reset the board to All Projects. The choice is
    # now saved the moment it is made and remembered per user on a new
    # res.users column (ft_week_board_project_id), read back only by the Week
    # form, so the Weeks list still counts every project. A card also no
    # longer opens its task when the click is the end of a drag. The upgrade
    # has to run for the new column.
    # 19.0.4.9.0 keeps the filter for the visit instead of for good. Choosing
    # a project now holds while the week stays open — through a drag and drop,
    # the reload after it and the pager — and leaving the week and coming back
    # starts at All Projects again, as it always did. The 19.0.4.8.0 res.users
    # column is dropped; the upgrade removes its field definition.
    # 19.0.4.10.0 hides the Manage Weeks button in the project's Tasks tab.
    # Hidden rather than deleted: the Weeks stat button already opens the same
    # list. View change only, no migration.
    # 19.0.4.11.0 opens both week screens on the week being worked. Weeks run
    # oldest first, which is what makes them read as a calendar — up is behind
    # us, down is still to come — and it also meant the project's Tasks tab and
    # the Weeks list both opened on weeks that were already over, with today's
    # somewhere below the fold and nothing to tell it from its neighbours once
    # it was reached. The current week is now outlined and badged on the board,
    # coloured on the list row, and scrolled to the middle of the screen on
    # open, so the weeks either side of it are one scroll away in each
    # direction. Scrolled once per screen, not per redraw: dragging a card
    # reloads the board, and jumping back after every drop would take it away
    # from whoever was using it. The week gains a computed is_current_week
    # (not stored — a stored flag would be wrong from the Monday after it was
    # written), so the upgrade is views and assets only, no migration.
    # 19.0.4.12.0 makes the current week stand out on the board — a heavy
    # outline, a stronger ring and a light tint, where a 1px border had left it
    # looking like every other week — and scrolls to it once per open record
    # rather than every time the Tasks tab is reopened. Switching tabs on the
    # project and Week forms also keeps the tab bar where it is on screen: a
    # short tab after the long board used to shrink the form, the browser
    # pulled the scroll back, and the tabs dropped down the page. The Weeks
    # list's current-week row is tinted across every cell, edged top and bottom
    # and set in the theme colour; only its first cell had been tinted, so it
    # read as bold text and nothing more. Assets only, no migration.
    # 19.0.4.13.0 opens the project's Full Board without saving the project
    # first. It was an object button, which saves before it runs, and core
    # requires the hidden Closed Date whenever a Start Date is set — so every
    # project still without a Closed Date refused to open its board. Moving a
    # task on the board is unaffected and still goes through every rule. It
    # also takes the wait out of paging between weeks: each week's board now
    # fetches the boards either side of it in the background, a page turn draws
    # from them at once, and get_board_data stops running the week's whole
    # summary and a stage search per column just to draw the cards. The same
    # version fixes the board showing the PREVIOUS week after Next or Previous
    # (W40's summary over W39's empty columns): the reload on a page turn read
    # the record the form was leaving instead of the one it was opening.
    # Views, assets and Python only, no migration.
    # 19.0.4.14.0 makes a Week's Assigned Tasks tab list the same tasks as its
    # Tasks tab, and follow the Project selector the same way. It listed every
    # task whose Week pointed here, including tasks whose deadline had since
    # moved to another week and so were on no board of this one. The rows stay
    # editable. Views and Python only, no migration.
    # 19.0.4.15.0 puts the project's past weeks back on its Tasks tab. Two
    # things were dropping the work that is behind us, and between them the
    # weeks that were over read "No tasks" or had no column at all.
    #   The board's tasks came from project.task_ids. Core gives that one2many
    # the domain [('is_closed', '=', False)] and bt_project_customization
    # stamps state 1_done on anything reaching a final stage, so the field left
    # out precisely the delivered work — and a finished week is nothing BUT
    # delivered work. _compute_week_ids read the same field, so those weeks
    # were not even in the project's span: the board began at the oldest week
    # with something still open in it. A card dragged into Completed
    # disappeared on the spot for the same reason. It now reads every task of
    # the project, with active_test off so archived tasks stay on the board as
    # they were (One2many.read sets it too — that is where they came from).
    #   Placing those tasks in their weeks then searched the whole company's
    # span and intersected the answer back down to the project, which could
    # only ever return what a search can see: an archived task was in the
    # board's task set and in none of its weeks, and fell through to "No Week".
    # qa_testapp.sprint._tasks_by_week now takes the caller's own set, so the
    # project's board buckets exactly the tasks it draws — one query fewer, and
    # over its own rows rather than every project's.
    #   With the past weeks back, the current week is a long way down the
    # board, and it was not being reached: it IS scrolled to on open, but the
    # notebook keeps its tab bar still on a page switch and does that from the
    # Notebook's own onPatched — which Owl runs after the board's, a child
    # being patched before its parent — so the reveal was measured as drift and
    # undone in the same cycle. It now happens a frame later, and brings the
    # week to the TOP of the reading area rather than the middle of it: past
    # weeks are above, the weeks still to come below. The board's tail is
    # padded where there is not a screenful under the current row, or the
    # browser clamps the scroll and the week comes to rest down the page.
    # The same version pins Open Full Board on the project's Tasks tab. The
    # board runs to several screens and the button scrolled away with the
    # first of them; it now stops directly under the tab bar, which
    # bt_project_customization already pins under the status bar, so the three
    # stack and only the cards move. And it opens the full-screen Week Board
    # on the week being worked: that column is outlined, badged "This week"
    # and brought to
    # the left of the screen, so the earlier weeks are one scroll left and the
    # coming ones one scroll right. It used to open on the project's oldest
    # week. Views, assets and Python only, no migration.
    'version': '19.0.4.15.0',
    'category': 'Project',
    'summary': 'Week-based task planning for projects (list, kanban & form views)',
    'description': """
Week Management
===============
Monday-to-Sunday week planning for the Project app:
 * One week per Monday for the whole company, numbered continuously from the
   first week of 2026 — the last week of 2026 is W53 and the first of 2027 is
   W54, not W1 again.
 * A week reports on every project at once; the project belongs to the tasks
   inside it, and each card on the board names the project it came from.
 * A week summarises the tasks DUE inside it: totals by stage, plus estimated,
   open, completed and actual hours.
 * Tasks carry a Week, and setting one moves the task's deadline to that
   week's Sunday — including when the move is a Kanban drag and drop.
 * A Week Board on each project lays the tasks out with one column per week.

The model and its columns are still named ``qa_testapp.sprint`` and
``sprint_id``: the database already carries them, and renaming them buys
nothing the labels do not. Everything a user sees says "Week".
""",
    'author': 'Fingertip',
    'website': '',
    # bt_project_customization for the task's `estimated` hours and
    # hr_timesheet for `effective_hours` — the week's hour summary totals both.
    # qa_testapp owns the project form's Tasks tab, which the Week Board button
    # is added to. project_todo (auto-installed with project) for its To-do
    # Kanban, whose "Add column" is hidden too.
    'depends': [
        'project',
        'project_todo',
        'hr_timesheet',
        'bt_project_customization',
        'qa_testapp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/task_stages.xml',
        'views/week_views.xml',
        'views/project_task_views.xml',
        'views/project_project_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_sprint_management/static/src/week_task_board/week_task_board.js',
            'ft_sprint_management/static/src/week_task_board/week_task_board.xml',
            'ft_sprint_management/static/src/week_task_board/week_task_board.scss',
            'ft_sprint_management/static/src/week_form/week_form_view.js',
            'ft_sprint_management/static/src/week_form/week_form_view.xml',
            'ft_sprint_management/static/src/week_list/week_list.js',
            'ft_sprint_management/static/src/week_list/week_list.scss',
            'ft_sprint_management/static/src/week_kanban/week_kanban.js',
            'ft_sprint_management/static/src/week_kanban/week_kanban.scss',
            'ft_sprint_management/static/src/notebook_tab_anchor/notebook_tab_anchor.js',
            'ft_sprint_management/static/src/open_week_board/open_week_board.js',
            'ft_sprint_management/static/src/open_week_board/open_week_board.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
