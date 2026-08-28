"""Data provider for the Sales dashboard.

PERIOD FIELDS
=============
The dashboard mixes three different questions, so it deliberately filters on
three different date fields rather than one — see GENERATED_FIELD /
PERIOD_FIELD / OUTCOME_FIELD below:

* "What is due to close in this period, and what is it worth?" ->
  ``date_deadline`` (Expected Closing). The Opportunities card, Pipeline Value,
  the pipeline month boards, the funnel, the Conversion denominator, and the
  Opportunities / Expected Revenue columns of the executive-wise report.
  Opportunities and Pipeline Value cover one population — every stage, live
  records only (see ``_generated_domain``) — so one is the count and the other
  the sum of the same set, and both equal the matching group in the Pipeline
  list. Note this means Pipeline Value includes won and lost deals and is
  therefore NOT a forecast of money still to come.
* "What did we actually close in this period?" -> ``date_closed`` (Closed
  Date). Sales Closed, Sales Closed Value, Opportunities Lost, the Closed and
  Lost month boards, and the Sales Closed / Lost columns of the executive
  report all use it.

Which field answers which question is the whole design. Dating an OUTCOME by
Expected Closing was the original defect — a deal that slipped its forecast was
reported in the month it was supposed to close rather than the month it closed.
That is why only Pipeline Value, a genuinely forward-looking figure, still reads
Expected Closing.

TIMEZONES
=========
``date_deadline`` is a Date and carries no timezone. ``create_date`` and
``date_closed`` are Datetimes stored in UTC, while the filter names days in the
user's timezone — so their bounds are converted (see ``_period_bounds``). In IST
that moves a day boundary by 5h30m, which is the difference between counting and
missing an opportunity created at 02:00. The resolved bounds are handed to the
client in the payload so a drill-down filters on the identical window.

WON / LOST SEMANTICS (from odoo/addons/crm/models/crm_lead.py)
=============================================================
* Won  = ``probability = 100`` on a live record, OR a live record in a stage
  flagged ``is_won``. Both, because Odoo offers both: ``action_set_won`` moves
  the record into the Won stage, but typing 100 into Probability wins the deal
  without touching the stage at all — and that is precisely what the WON ribbon
  on the form tests (``invisible="probability < 100"``, crm_lead_views.xml).
  Detecting the stage alone left deals the CRM form labels WON sitting inside
  Pipeline Value, which is what this pair of clauses exists to prevent.
* Lost = ``action_set_lost`` archives the record, so ``active = False``.
* Open = live, not won by either test, and not parked in a Lost stage.

Archived is therefore what separates lost from won; being won is not enough,
because a won lead that is later archived is no longer a live sale.

WHICH FIGURES SEE ARCHIVED RECORDS
==================================
The ORM silently appends ``active = True`` to any domain that does not mention
``active`` itself (models._where_calc), so a figure could include or exclude
archived deals purely by accident. That asymmetry is why the cards, the
drill-downs, the filtered lists and a CRM export never agreed. Every query here
now goes through ``_leads()``, which disables active_test, and each domain then
states its own position explicitly:

* Opportunities and Pipeline Value — live records only (``_generated_domain``),
  so both equal the matching group in the Pipeline list, which also hides
  archived records. Archived deals are reported by Opportunities Lost instead.
* Opportunities Lost — archived records AND live ones in a Lost stage.
* Sales Closed / Sales Closed Value — live records in a won stage.

Every drill-down in static/src/js/sales_dashboard.js passes
``active_test: False`` and then repeats the same explicit condition, so a card
and the list it opens can never disagree.

SALESPERSON FILTER
==================
``get_dashboard_data(user_id=...)`` narrows every figure on the page to one
salesperson. It is applied ONCE, in ``_user_domain()``, onto the opportunity
domain that the KPIs, the funnel, the executive table and all three month
boards are each derived from — so a new card added later inherits the filter
instead of having to remember it. The resolved leaves ride along in the payload
(``user_domain``) and the drill-downs append them at the single choke point in
static/src/js/sales_dashboard.js, for the same reason the period bounds are
sent rather than recomputed.

Unassigned opportunities are selectable as ``UNASSIGNED_USER`` (-1), which
resolves to ``user_id = False``. It is not 0, because the argument arrives from
JSON and ``0 == False`` in Python, so a 0 sentinel could not be distinguished
from "no filter" by any falsiness test.

A lost opportunity keeps whatever stage it was in when it was lost, so grouping
by stage would report it under Discussion / Demo / Negotiation.
ft_sales_dashboard/models/crm_lead.py therefore moves it into the Lost stage on
archive, and the funnel pulls every Lost-stage record into one dedicated band,
so a dead deal is never displayed inside an active stage and the bands still add
up to the Opportunities card.
"""
from dateutil.relativedelta import relativedelta

from datetime import datetime, time

import pytz

from odoo import api, fields, models

from .crm_lead import LOST_STAGE_NAME, WON_PROBABILITY

# The "Opportunities" card: dated by Expected Closing, the same field as Pipeline
# Value beside it. The two cards therefore describe one population from two
# angles — how many deals are due to close in the period, and what the open ones
# among them are worth.
#
# It was briefly dated by create_date ("how many did we open in the period"),
# which is the other defensible reading of the old label. Expected Closing was
# chosen instead so the card, Pipeline Value and the funnel all answer the same
# question; the card was renamed from "Opportunities Generated" to
# "Opportunities" to match, since it no longer counts what was generated.
#
# The funnel, the Executive-wise Opportunities and Expected Revenue columns and
# the Conversion denominator all measure this same population, so the breakdowns
# and the totals row keep reconciling with the card exactly. Point this at
# 'create_date' and all of them move together.
GENERATED_FIELD = 'date_deadline'

# Pipeline Value and the pipeline month boards: dated by when the deal is
# EXPECTED to close, because "what is in the pipeline for this period" is a
# question about the forecast, not about when the record was typed in.
PERIOD_FIELD = 'date_deadline'

# Outcome-side metrics (Sales Closed, Opportunities Lost, the won/lost month
# boards and the won/lost columns of the executive report): dated by when the
# deal ACTUALLY closed. Odoo stamps date_closed on reaching probability 100 or
# on archive, so it is the only field that dates the outcome rather than the
# origin.
#
# This must stay in step with _closedDomain() in static/src/js/sales_dashboard.js,
# which the KPI drill-downs use. Pointing this at date_deadline while the JS
# still filtered on date_closed is what made the Sales Closed / Lost cards read
# 0 next to a drill-down listing 4 records.
#
# Records won or lost before this dashboard existed (or imported straight into a
# Won stage) can carry no date_closed at all, which made these KPIs under-report
# against a CRM export. crm_lead._ft_backfill_date_closed() fills those in once,
# from the last stage change, so the metric stays correctly defined instead of
# being redefined to mean "expected to close".
OUTCOME_FIELD = 'date_closed'

MONTHS_AHEAD = 6
MONTHS_BACK = 6
# Upper bound on the month cards a custom range may produce, so "2010 -> today"
# cannot render 180 cards (and fire 180 queries' worth of work).
MAX_PERIOD_MONTHS = 24
# Opportunities listed inline on each month card; the rest are reached by
# clicking through, so a busy month cannot make the card unreadable.
LIST_PER_MONTH = 5
# Safety cap on the record fetch behind the month cards. Totals are computed
# separately by read_group, so a cap here never makes a number wrong — it only
# limits how many rows can be listed inline.
FETCH_CAP = 400

# Sentinel stage id for the funnel's Lost band. Not a real crm.stage: lost deals
# keep their old stage, so they are pulled out of the stage bands entirely.
LOST_BAND = 'lost'

# Sentinel user id for the "Unassigned" entry of the salesperson filter.
# Deliberately -1 rather than 0 or False: the filter argument arrives from JSON,
# and in Python ``0 == False``, so a 0 sentinel could not be told apart from
# "no filter applied" by any falsiness test. A negative id can never collide
# with a real res.users id either.
UNASSIGNED_USER = -1


class FtSalesDashboard(models.TransientModel):
    _name = 'ft.sales.dashboard'
    _description = 'Sales Dashboard data provider'

    # ------------------------------------------------------------------
    # Domain helpers
    # ------------------------------------------------------------------
    def _leads(self):
        """``crm.lead`` including archived records.

        Lost opportunities are archived, so without this every domain that does
        not name ``active`` would silently exclude them — see the module
        docstring. Every count, sum and read_group on this dashboard goes
        through here so one population feeds every number.
        """
        return self.env['crm.lead'].with_context(active_test=False)

    def _period_bounds(self, field, date_from, date_to):
        """The (from, to) values a domain on ``field`` must use for the period.

        Returned as well as used, so the client can filter its drill-downs on
        exactly the bounds the KPI was counted with rather than recomputing them
        and drifting — see ``bounds`` in the payload.

        ``date_deadline`` is a Date and takes the plain day strings. ``create_date``
        and ``date_closed`` are Datetimes stored in UTC, while the filter names
        days in the USER's timezone, so their bounds are the UTC instants of
        local midnight and local 23:59:59 — in IST, 18:30 the previous day to
        18:29:59 on the last day. Comparing them against naive '00:00:00' /
        '23:59:59' strings would shift every window by the UTC offset: an
        opportunity created at 02:00 IST is stored as 20:30 the previous day and
        would drop out of "Today" entirely, and a pivot or export (which Odoo
        groups in the user's timezone) would never agree with the cards.
        """
        if self.env['crm.lead']._fields[field].type != 'datetime':
            return date_from or None, date_to or None

        tz = pytz.timezone(self.env.user.tz or 'UTC')

        def as_utc(day, at):
            local = tz.localize(datetime.combine(fields.Date.to_date(day), at))
            return fields.Datetime.to_string(
                local.astimezone(pytz.UTC).replace(tzinfo=None))

        return (as_utc(date_from, time(0, 0, 0)) if date_from else None,
                as_utc(date_to, time(23, 59, 59)) if date_to else None)

    def _date_domain(self, field, date_from, date_to):
        """Inclusive range on a Date or Datetime field, in the user's timezone."""
        low, high = self._period_bounds(field, date_from, date_to)
        dom = []
        if low:
            dom.append((field, '>=', low))
        if high:
            dom.append((field, '<=', high))
        return dom

    def _opp_domain(self):
        return [('type', '=', 'opportunity')]

    def _user_domain(self, user_id):
        """The salesperson half of every domain, or [] for "all salespeople".

        ANDed onto ``_opp_domain()`` once in ``get_dashboard_data``, so every
        KPI, the funnel, the executive table and all three month boards narrow
        together — there is no figure that can quietly keep showing the whole
        team while the rest of the dashboard is filtered.

        The resolved leaves are handed back to the client in the payload
        (``user_domain``) for the same reason the period bounds are: a
        drill-down repeats the server's own filter instead of rebuilding it.
        """
        if not user_id:
            return []
        user_id = int(user_id)
        if user_id == UNASSIGNED_USER:
            return [('user_id', '=', False)]
        return [('user_id', '=', user_id)]

    def _salespeople(self, selected=None):
        """Options for the salesperson filter: everyone who owns an opportunity.

        Built from the opportunities themselves rather than from a res.users
        search, so every option in the list is guaranteed to have records behind
        it and a user who has never touched the CRM does not pad the dropdown.

        Deliberately NOT restricted to the selected period: the list would then
        shrink as the filter narrows and the chosen salesperson could vanish
        from the control that selects them.
        """
        people = []
        unassigned = 0
        for group in self._leads().read_group(
                self._opp_domain(), [], ['user_id'], lazy=False):
            if group.get('user_id'):
                people.append({
                    'id': group['user_id'][0],
                    'name': group['user_id'][1],
                    'count': group['__count'],
                })
            else:
                unassigned = group['__count']
        people.sort(key=lambda p: p['name'].lower())
        # Unassigned last: it is a bucket, not a person, and it is only offered
        # when there is actually something in it.
        if unassigned:
            people.append({'id': UNASSIGNED_USER, 'name': 'Unassigned',
                           'count': unassigned})

        # A restored filter can name someone who now owns nothing — their deals
        # reassigned since, or the Unassigned bucket emptied. The dashboard is
        # still filtered to them, so they have to stay in the list: dropping
        # them would leave the control reading "All Salespeople" over figures
        # that are anything but.
        if selected and not any(p['id'] == int(selected) for p in people):
            selected = int(selected)
            if selected == UNASSIGNED_USER:
                name = 'Unassigned'
            else:
                # exists() first: the user may have been deleted outright, and
                # reading display_name off a missing record raises MissingError.
                name = self.env['res.users'].browse(
                    selected).exists().display_name or 'Unknown'
            people.append({'id': selected, 'name': name, 'count': 0})
        return people

    def _generated_domain(self):
        """The population the Opportunities and Pipeline Value cards describe.

        EVERY stage — Cold through Won and Lost — but live records only.
        Archived opportunities are deliberately left out here: they are counted
        by Opportunities Lost instead, and including them made the two cards
        impossible to reconcile against the Pipeline list, which hides archived
        records. With this, both cards equal that list's group for the period
        exactly.

        Note the two cards therefore cover the SAME set: Opportunities is its
        count and Pipeline Value its sum, so they can never disagree.
        """
        return [('active', '=', True)]

    def _lost_stage_ids(self):
        """Stages that mean "lost", matched by name.

        ``crm.stage`` carries ``is_won`` but no ``is_lost`` counterpart, so the
        Lost stage is identified the same way crm_lead.py identifies it for the
        automatic move on archive. ``active_test`` is off so an archived stage
        still resolves.
        """
        return self.env['crm.stage'].with_context(active_test=False).search(
            [('name', '=ilike', LOST_STAGE_NAME)]).ids

    def _open_domain(self):
        """Still in play: live, not won, and not parked in a Lost stage.

        The Lost-stage exclusion matters because a deal can be dragged to the
        Lost stage without ever being archived — 65 of them in the live database
        — and every one was being reported as open Pipeline Value while sitting
        in a stage called Lost.
        """
        return [('active', '=', True), ('probability', '<', WON_PROBABILITY),
                ('stage_id.is_won', '=', False),
                ('stage_id', 'not in', self._lost_stage_ids())]

    def _won_domain(self):
        """Live and won, by either of Odoo's two definitions.

        The probability clause is not redundant with the stage one: a deal moved
        straight to won — Probability set to 100 without the stage changing —
        wears the WON ribbon on its form while its stage still reads Discussion.
        Matching only ``stage_id.is_won`` reported such a deal as open pipeline,
        contradicting the record's own form.
        """
        return ['&', ('active', '=', True),
                '|', ('probability', '>=', WON_PROBABILITY),
                ('stage_id.is_won', '=', True)]

    def _not_won_domain(self):
        """Everything not won — the inverse of _won_domain, minus its ``active``.

        Callers AND this onto a population that already restricts to live
        records, so repeating ``active`` here would be noise.

        Written as an explicit OR rather than the shorter
        ``('stage_id.is_won', '=', False)`` because that form resolves to
        "stage_id IN (the not-won stages)", which silently DROPS an opportunity
        carrying no stage at all rather than keeping it. There are none in the
        current database, but a stageless deal is still in play and must not
        disappear from the pipeline figure while the Opportunities card next to
        it goes on counting it.

        Stages with ``is_won`` unset count as not-won: Odoo reads ``= False`` on
        a boolean as "false or null", which is what the three such stages here
        need.
        """
        return ['&', ('probability', '<', WON_PROBABILITY),
                '|', ('stage_id', '=', False), ('stage_id.is_won', '=', False)]

    def _lost_domain(self):
        """Lost = archived, OR sitting in a Lost stage while still active.

        Odoo records a loss by archiving, so ``active = False`` was the original
        definition. It is not sufficient on its own: unarchiving a lost deal, or
        dragging one to the Lost stage in the kanban, leaves a record that reads
        "Lost" in every list and export while counting as open pipeline on the
        dashboard. Either signal now means lost, so the card agrees with what the
        Stage column shows.

        The two halves cannot double-count: ``_open_domain`` and ``_won_domain``
        both require ``active = True``, and ``_open_domain`` excludes the Lost
        stages this admits.
        """
        return ['|', ('active', '=', False),
                ('stage_id', 'in', self._lost_stage_ids())]

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, user_id=None):
        """Every KPI, table and board for the Sales dashboard.

        The month boards come in three windows — the trailing six months, the
        next six months, and the selected period itself. The first two are
        fixed by definition; the third is what makes "This Year" show January
        through December (including the months that have no records yet)
        instead of stopping at today.

        ``user_id`` narrows the WHOLE dashboard to one salesperson (None = all,
        UNASSIGNED_USER = opportunities with no salesperson). It is applied once
        here, onto the opportunity domain every other figure is derived from, so
        no card can be left unfiltered by omission.
        """
        opp = self._opp_domain() + self._user_domain(user_id)
        # Three fields, three questions — see GENERATED_FIELD / PERIOD_FIELD /
        # OUTCOME_FIELD. What we opened, what is forecast to close, what did
        # close.
        generated = (opp + self._generated_domain()
                     + self._date_domain(GENERATED_FIELD, date_from, date_to))
        period = opp + self._date_domain(PERIOD_FIELD, date_from, date_to)
        outcome = opp + self._date_domain(OUTCOME_FIELD, date_from, date_to)

        today = fields.Date.context_today(self)
        # Next 6 months starts NEXT month: starting at the current month made
        # "Last 6 Months" (Feb->Jul) and "Next 6 Months" (Jul->Dec) both claim
        # July, so the same deals were counted on two boards.
        ahead = self._month_buckets(
            today.replace(day=1) + relativedelta(months=1), MONTHS_AHEAD)
        back = self._month_buckets(
            today.replace(day=1) - relativedelta(months=MONTHS_BACK - 1), MONTHS_BACK)
        # Every month the filter covers, empty ones included.
        selected = self._period_buckets(date_from, date_to, today) or back

        open_opps = opp + self._open_domain()
        won_opps = opp + self._won_domain()
        lost_opps = opp + self._lost_domain()

        return {
            'kpis': self._kpis(generated, outcome),
            # The bounds every figure was actually measured between, per date
            # field. The client filters its drill-downs on these rather than
            # rebuilding them, so a card and the list it opens cannot disagree —
            # including across the UTC/local shift on the two Datetime fields,
            # which the browser has no reliable way to reproduce.
            'bounds': {
                field: self._period_bounds(field, date_from, date_to)
                for field in (GENERATED_FIELD, PERIOD_FIELD, OUTCOME_FIELD)
            },
            # The salesperson filter: the options to offer, the one in force,
            # and the domain leaves it resolved to. The leaves are sent rather
            # than rebuilt in the browser so a drill-down narrows to exactly the
            # records its card counted — including the Unassigned sentinel,
            # which is ``user_id = False`` in a domain but -1 in the control.
            'salespeople': self._salespeople(user_id),
            'user_id': user_id or None,
            'user_domain': self._user_domain(user_id),
            # Which stages count as Lost, so the drill-downs can reproduce
            # _lost_domain() / _open_domain() exactly rather than hard-coding
            # "active = false" and disagreeing with the cards.
            'lost_stage_ids': self._lost_stage_ids(),
            # Which field the Opportunities card, the funnel and the executive
            # table were measured on. Sent rather than assumed by the client so
            # that changing GENERATED_FIELD moves the cards and their
            # drill-downs together instead of leaving the two out of step.
            'generated_field': GENERATED_FIELD,
            'charts': {
                # The stage picture is the funnel only. A separate
                # "revenue by stage" bar chart showed the same figures a second
                # time, so it was removed rather than kept as a duplicate.
                'funnel': self._chart_funnel(generated),
            },
            'boards': {
                # Trailing pipeline is what the spec asks for; the forward view
                # is kept alongside it because a pipeline that only looks
                # backwards cannot answer "what is coming". The front end
                # toggles between the three windows on one card.
                'pipeline_last_months': self._month_board(
                    open_opps, PERIOD_FIELD, back, '#4F46E5'),
                'pipeline_next_months': self._month_board(
                    open_opps, PERIOD_FIELD, ahead, '#06B6D4'),
                'pipeline_period_months': self._month_board(
                    open_opps, PERIOD_FIELD, selected, '#4F46E5'),
                'closed_last_months': self._month_board(
                    won_opps, OUTCOME_FIELD, back, '#10B981'),
                'closed_period_months': self._month_board(
                    won_opps, OUTCOME_FIELD, selected, '#10B981'),
                'lost_last_months': self._month_board(
                    lost_opps, OUTCOME_FIELD, back, '#EF4444'),
                'lost_period_months': self._month_board(
                    lost_opps, OUTCOME_FIELD, selected, '#EF4444'),
            },
            'executives': self._executive_report(generated, outcome),
        }

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    def _kpis(self, generated, outcome):
        Lead = self._leads()

        # Opportunities: EVERY stage — New, Discussion, Demo, Negotiation, Won,
        # Lost and any other configured stage — whose Expected Closing falls in
        # the period. Live records only; see _generated_domain().
        generated_count = Lead.search_count(generated)

        # Pipeline Value: Expected Revenue of the records the Opportunities card
        # counts, MINUS the ones already in a Won stage.
        #
        # Won money is not pipeline. Including it produced weeks like 2-8 Aug
        # 2026 — one deal won, one lost, nothing else — reading as ₹110,000 of
        # "pipeline" when there was nothing left in play at all.
        #
        # The cost of excluding it is that this card and the Opportunities card
        # no longer describe one population, so the two can no longer be checked
        # against a single Pipeline list group in one step. That reconciliation
        # is what the Won-inclusive version bought, and it is deliberately given
        # up here: a figure called Pipeline Value has to mean money still to
        # come, and the count beside it still answers "how many deals came up".
        #
        # NOTE deals parked in a Lost stage while still un-archived ARE still
        # counted here. Only Won is excluded. _open_domain() is the stricter
        # both-excluded version, used by the month boards.
        pipeline_value = self._sum_revenue(generated + self._not_won_domain())

        # Sales Closed / Lost: dated by date_closed (OUTCOME_FIELD), because
        # "what did we close this period" is a question about when the deal
        # actually closed, not when it was expected to.
        won_domain = outcome + self._won_domain()
        sales_closed = Lead.search_count(won_domain)
        sales_closed_value = self._sum_closed_amount(won_domain)

        lost = Lead.search_count(outcome + self._lost_domain())

        # Conversion over the same population the two numbers come from.
        conversion = self._ratio(sales_closed, generated_count)

        return {
            'opportunities': generated_count,
            'pipeline_value': pipeline_value,
            'sales_closed': sales_closed,
            'sales_closed_value': sales_closed_value,
            'opportunities_lost': lost,
            'conversion_ratio': conversion,
        }

    def _ratio(self, part, whole):
        """Percentage, guarding the empty-period divide by zero.

        One definition for the KPI card, every executive row and the totals
        row, so the three can never drift apart.
        """
        return round(part / whole * 100, 1) if whole else 0.0

    def _sum(self, domain, field):
        """SUM(field) over a domain in a single aggregate query."""
        groups = self._leads().read_group(domain, [f'{field}:sum'], [], lazy=False)
        return sum(g.get(field) or 0.0 for g in groups)

    def _sum_revenue(self, domain):
        """SUM(expected_revenue) — the pipeline figure."""
        return round(self._sum(domain, 'expected_revenue'), 2)

    def _sum_closed_amount(self, domain):
        """SUM of Closed Amount, falling back to Expected Revenue per record.

        ``revenue`` (Closed Amount) is only filled on some won records, so a
        plain SUM(revenue) under-reports. Split into two aggregate queries —
        records that have a closed amount, and those that do not — instead of
        looping records, so cost stays flat as the pipeline grows.
        """
        has_revenue = self._sum(domain + [('revenue', '!=', 0)], 'revenue')
        no_revenue = self._sum(domain + [('revenue', '=', 0)], 'expected_revenue')
        return round(has_revenue + no_revenue, 2)

    # ------------------------------------------------------------------
    # Stage charts
    # ------------------------------------------------------------------
    def _stage_groups(self, domain):
        """Expected Revenue + count per stage, ordered by the CRM stage flow.

        Sorted by crm.stage.sequence rather than by value so the funnel reads
        as the pipeline (Cold -> Discussion -> ... -> Won). Stages with no
        sequence and the 'Undefined' bucket sort last.
        """
        groups = self._leads().read_group(
            domain, ['expected_revenue:sum'], ['stage_id'], lazy=False)
        seq_by_stage = {
            s.id: s.sequence
            for s in self.env['crm.stage'].browse(
                [g['stage_id'][0] for g in groups if g.get('stage_id')])
        }
        groups.sort(key=lambda g: seq_by_stage.get(
            g['stage_id'][0] if g.get('stage_id') else False, 10 ** 6))
        return groups

    def _chart_funnel(self, generated):
        """Sales funnel by Expected Revenue (not opportunity count).

        Bands are stages — that is what makes it a funnel — but the value shown
        and the band width are Expected Revenue, and the period filter is
        Expected Closing, so the bands add up to the Opportunities card.

        Bands come from the same population as that card, which is live records
        only, and every live record in a Lost stage is pulled into one trailing
        "Lost" band. A lost opportunity keeps whatever
        stage it was in when it was lost, so grouping it by stage would list it
        under Discussion / Demo / Negotiation and report a dead deal as active
        pipeline. Won stages stay in the bands: a won deal is a real end state.
        """
        # Live records only, and never a Lost stage — otherwise an unarchived
        # lost deal would render its own "Lost" band beside the red one below,
        # two bands with the same label counting different records.
        groups = self._stage_groups(generated + [
            ('active', '=', True), ('stage_id', 'not in', self._lost_stage_ids())])
        labels = [g['stage_id'][1] if g.get('stage_id') else 'Undefined' for g in groups]
        values = [round(g.get('expected_revenue') or 0.0, 2) for g in groups]
        counts = [g['__count'] for g in groups]
        stage_ids = [g['stage_id'][0] if g.get('stage_id') else False for g in groups]

        # One band for everything lost, whatever stage it stopped in.
        lost_domain = generated + self._lost_domain()
        lost_count = self._leads().search_count(lost_domain)
        if lost_count:
            labels.append('Lost')
            values.append(self._sum_revenue(lost_domain))
            counts.append(lost_count)
            stage_ids.append(LOST_BAND)

        # Which bands are terminal outcomes rather than open pipeline. The
        # client paints those two with reserved status colours (won green,
        # lost red) and hands the open stages the categorical hues, so a
        # manager reads the outcome of the funnel before reading any label.
        #
        # Won is taken from the stage's ``is_won`` flag rather than from its
        # name: 'Won' is translatable and renameable, and this dashboard
        # already learned that lesson once with the Lost stage.
        # ``sid`` is an int, False for the Undefined band, or the LOST_BAND
        # STRING — which is truthy, so it has to be excluded by name and not by
        # falsiness or the browse() is handed 'lost' as an id.
        won_ids = set(self.env['crm.stage'].browse(
            [sid for sid in stage_ids if sid and sid != LOST_BAND]
        ).filtered('is_won').ids)
        kinds = [
            LOST_BAND if sid == LOST_BAND else 'won' if sid in won_ids else 'open'
            for sid in stage_ids
        ]
        return {
            'labels': labels,
            'stage_ids': stage_ids,
            'kinds': kinds,
            'counts': counts,
            'total_count': sum(counts),
            'datasets': [{
                'label': 'Expected Revenue',
                'data': values,
            }],
        }

    # ------------------------------------------------------------------
    # Month-window charts
    # ------------------------------------------------------------------
    def _month_buckets(self, start, count):
        """``count`` consecutive month starts from ``start`` (a date)."""
        first = start.replace(day=1)
        return [first + relativedelta(months=i) for i in range(count)]

    def _period_buckets(self, date_from, date_to, today):
        """Every month the selected filter touches, empty months included.

        "This Year" runs 1 January to 31 December, so this returns twelve
        buckets and the months with no records render as zero cards. Before
        this, the boards were fixed six-month windows and a year filter could
        never show August onwards. Returns None when the filter has no bounds
        at all, and the caller falls back to the trailing window.
        """
        start = fields.Date.to_date(date_from) if date_from else None
        end = fields.Date.to_date(date_to) if date_to else None
        if not start and not end:
            return None
        start = (start or end).replace(day=1)
        end = (end or today).replace(day=1)
        if end < start:
            end = start
        count = (end.year - start.year) * 12 + (end.month - start.month) + 1
        return self._month_buckets(start, min(count, MAX_PERIOD_MONTHS))

    def _month_board(self, domain, date_field, buckets, color):
        """Month cards carrying both the totals and the deals behind them.

        Replaces the plain bar chart these views used to be. A bar says "how
        much" but never "which"; a flat table of six months of records buries
        the trend. Each month returns its total, its count and the largest few
        opportunities, so the shape and the detail are readable at once and
        every number can be opened.

        Totals come from ``read_group`` and are always exact. The inline list
        is a separate fetch, ordered by value and capped, so one huge month
        cannot pull the whole table into memory — anything past
        ``LIST_PER_MONTH`` is reported as ``more`` and reached via drill-down.
        """
        Lead = self._leads()
        is_datetime = Lead._fields[date_field].type == 'datetime'

        def month_key(value):
            """YYYY-MM of ``value`` as the USER sees it.

            read_group groups a Datetime in the user's timezone but reports
            __range in UTC, so for any timezone ahead of UTC the month start
            comes back as the previous month (IST: March -> 2026-02-28 18:30).
            Slicing that string put every total on the wrong card while the
            record list, which is bucketed from the record's own date, stayed
            correct. Converting to the user's timezone first is what keeps the
            two in step. Date fields carry no timezone and pass through.
            """
            if not value:
                return None
            if is_datetime:
                dt = fields.Datetime.to_datetime(value)
                return fields.Datetime.context_timestamp(self, dt).strftime('%Y-%m')
            return str(value)[:7]

        # Widen the fetch by a day at each end: the bounds below are naive while
        # bucketing is timezone-aware, so a record within a few hours of a
        # boundary would otherwise be dropped before it could be bucketed.
        # Anything landing outside the buckets is ignored when mapping, so
        # the wider window cannot inflate a total.
        window = domain + [
            (date_field, '>=', fields.Date.to_string(
                buckets[0] - relativedelta(days=1))),
            (date_field, '<', fields.Date.to_string(
                buckets[-1] + relativedelta(months=1, days=1))),
        ]

        # --- exact totals -------------------------------------------------
        # Buckets are built in Python so an empty month still shows a card;
        # read_group only returns months that have rows.
        totals = {}
        for group in Lead.read_group(
                window, ['expected_revenue:sum'], [f'{date_field}:month'], lazy=False):
            rng = (group.get('__range') or {}).get(f'{date_field}:month')
            key = month_key(rng['from']) if rng else None
            if not key:
                continue
            totals[key] = {
                'amount': round(group.get('expected_revenue') or 0.0, 2),
                'count': group['__count'],
            }

        # --- the deals themselves ----------------------------------------
        records = Lead.search_read(
            window,
            ['name', 'partner_id', 'expected_revenue', 'user_id', date_field],
            order='expected_revenue desc, id desc',
            limit=FETCH_CAP,
        )
        by_month = {}
        for rec in records:
            value = rec.get(date_field)
            key = month_key(value)
            if not key:
                continue
            # Display the date in the user's timezone too, so a deal closed
            # late in the evening is not shown under the previous day.
            if is_datetime:
                shown = fields.Datetime.context_timestamp(
                    self, fields.Datetime.to_datetime(value)).strftime('%Y-%m-%d')
            else:
                shown = str(value)[:10]
            by_month.setdefault(key, []).append({
                'id': rec['id'],
                'name': rec['name'],
                'partner': rec['partner_id'][1] if rec.get('partner_id') else '',
                'user': rec['user_id'][1] if rec.get('user_id') else 'Unassigned',
                'amount': round(rec.get('expected_revenue') or 0.0, 2),
                'date': shown,
            })

        months = []
        for bucket in buckets:
            key = bucket.strftime('%Y-%m')
            total = totals.get(key) or {'amount': 0.0, 'count': 0}
            items = by_month.get(key, [])[:LIST_PER_MONTH]
            # The card's own drill-down window, resolved here for the same
            # reason as the period bounds above: this month was BUCKETED in the
            # user's timezone, so a client rebuilding "2026-08-01" as a UTC
            # instant would open a window shifted by the offset and miss the
            # deals sitting within it of a month boundary.
            month_from, month_to = self._period_bounds(
                date_field,
                fields.Date.to_string(bucket),
                fields.Date.to_string(bucket + relativedelta(months=1, days=-1)))
            months.append({
                'key': key,
                'label': bucket.strftime('%b %Y'),
                'short': bucket.strftime('%b'),
                'year': bucket.strftime('%Y'),
                'amount': total['amount'],
                'count': total['count'],
                'items': items,
                'more': max(total['count'] - len(items), 0),
                'from': month_from,
                'to': month_to,
            })

        # Shared scale so the bars compare across months rather than each
        # month rescaling to itself.
        return {
            'months': months,
            'max_amount': max([m['amount'] for m in months] or [0.0]),
            'total_amount': round(sum(m['amount'] for m in months), 2),
            'total_count': sum(m['count'] for m in months),
            'color': color,
            'date_field': date_field,
        }

    # ------------------------------------------------------------------
    # Executive-wise report
    # ------------------------------------------------------------------
    def _executive_report(self, generated, outcome):
        """Per-salesperson counts, Expected Revenue and conversion, plus totals.

        Four read_groups for the whole table regardless of how many
        salespeople exist — never one query per executive.

        Each column is measured on the SAME domain as the KPI card above it:
        Opportunities and Expected Revenue on Expected Closing over live records
        (the population both left-hand cards share), Sales Closed and Lost on
        Closed Date.
        That is what lets the totals row reconcile exactly with the cards — the
        check the manager actually performs. Rows are built from the UNION of
        the three groupings, because an executive can have a deal closing in the
        period without having opened one in it; dropping those rows would leave
        the Sales Closed column short of the card it is supposed to match.

        Conversion = Sales Closed / Opportunities x 100, the same definition as
        the KPI card, computed through _ratio() so the two cannot drift.
        """
        Lead = self._leads()

        def by_user(domain, value_field=None):
            fields_ = [f'{value_field}:sum'] if value_field else []
            out = {}
            for group in Lead.read_group(domain, fields_, ['user_id'], lazy=False):
                uid = group['user_id'][0] if group.get('user_id') else False
                name = group['user_id'][1] if group.get('user_id') else 'Unassigned'
                out[uid] = {
                    'name': name,
                    'value': (round(group.get(value_field) or 0.0, 2) if value_field
                              else group['__count']),
                }
            return out

        counts = by_user(generated)
        amounts = by_user(generated, value_field='expected_revenue')
        won = by_user(outcome + self._won_domain())
        lost = by_user(outcome + self._lost_domain())

        names = {}
        for source in (counts, amounts, won, lost):
            for uid, entry in source.items():
                names.setdefault(uid, entry['name'])

        rows = []
        for uid, name in names.items():
            total = counts.get(uid, {}).get('value', 0)
            won_count = won.get(uid, {}).get('value', 0)
            rows.append({
                'user_id': uid,
                'name': name,
                'count': total,
                'amount': amounts.get(uid, {}).get('value', 0.0),
                'won': won_count,
                'lost': lost.get(uid, {}).get('value', 0),
                'conversion': self._ratio(won_count, total),
            })
        # Biggest pipeline first: the ordering a sales manager reads top-down.
        rows.sort(key=lambda r: r['amount'], reverse=True)

        # Totals row. Summed from the rows rather than re-queried, so it is
        # arithmetically impossible for the table body and its own total to
        # disagree — and because each column uses the KPI's domain, these totals
        # equal the cards for whatever filter is applied.
        total_count = sum(r['count'] for r in rows)
        total_won = sum(r['won'] for r in rows)
        totals = {
            'name': 'Total',
            'count': total_count,
            'amount': round(sum(r['amount'] for r in rows), 2),
            'won': total_won,
            'lost': sum(r['lost'] for r in rows),
            'conversion': self._ratio(total_won, total_count),
        }
        return {'rows': rows, 'total': totals}
