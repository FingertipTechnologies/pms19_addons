"""Three data repairs the Sales dashboard depends on: Closed Date, Lost stage
and Won stage.

WON STAGE
=========
Odoo has two ways to win a deal and they do not agree with each other.
``action_set_won`` sets ``probability = 100`` AND moves the record into a stage
flagged ``is_won``; typing 100 into Probability on the form sets the probability
alone. The form then paints its WON ribbon — it tests nothing but
``probability < 100`` — while the stage bar above it still highlights Demo, and
the list, the kanban and every export go on showing Demo.

``write()`` below closes that gap: an opportunity reaching 100% is moved into
the Won stage in the same write, so the stage a record displays is the outcome
it actually has, everywhere. ``_ft_sync_won_stage()`` repairs the records won
before this existed.

Note the Won button cannot fix these by hand: it is hidden by
``invisible="not active or probability == 100 or type == 'lead'"``, so a deal
already at 100% has no button left to press.

LOST STAGE
==========
Odoo records a loss by archiving the opportunity and leaves ``stage_id`` alone,
so a lost deal keeps whichever stage it died in. The dashboard reads every
archived record as Lost, but a list view, an export or a pivot shows the raw
stage — which is why a dead deal appears under Discussion, Demo or Negotiation
and why those reports could not be reconciled with the dashboard by eye.

``write()`` below moves an opportunity into the Lost stage as it is archived,
and ``_ft_sync_lost_stage()`` repairs the ones archived before that existed.
Note this required relaxing two rules in bt_crm_customization (Lost left
QUALIFIED_PLUS_STAGES, and Next Action is no longer demanded on Lost): a deal
that has already ended cannot be asked for forward-looking qualification data,
and the constraints would otherwise have blocked the move outright.

CLOSED DATE
===========
Closed Date repair for opportunities that never got one.

Sales Closed and Opportunities Lost are dated by ``date_closed`` — the only
field that says when a deal actually ended (see models/sales_dashboard.py).
Odoo stamps it in ``crm.lead.write()`` when probability reaches 100 or when the
record is archived, so anything won or lost through the UI carries it.

Two populations do not:

* records imported straight into a Won stage — the import writes the stage in
  ``create()``, which never passes through that branch of ``write()``;
* records won or lost before an upgrade that introduced the stamping.

Those deals then existed in the database and in a CRM export while counting for
nothing on the dashboard, which is exactly the "card says 15, export says more"
mismatch. The fix is to fill the missing dates once, not to redefine "closed"
as "expected to close".

``date_last_stage_update`` is the best available answer to "when did this reach
its final stage"; ``write_date`` is the fallback when even that is absent. The
pass only ever fills a blank, never overwrites a real Closed Date, so running it
twice changes nothing.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Name of the stage lost opportunities are moved to, matched case-insensitively.
LOST_STAGE_NAME = 'lost'

# The probability at which crm.lead considers a deal won and the form paints its
# WON ribbon (crm/views/crm_lead_views.xml: invisible="probability < 100").
# Named because the same threshold has to hold in three places: the stage sync
# below, the dashboard's domains (sales_dashboard.py) and the client's mirror of
# those domains (static/src/js/sales_dashboard.js).
WON_PROBABILITY = 100

# Set on the automatic stage syncs below. bt_crm_customization reads it to let
# them through: they reconcile the stage with an outcome the record ALREADY has,
# so a rule demanding data the user has not typed yet would only leave the stage
# permanently wrong. Manual stage changes are unaffected and still validated.
STAGE_SYNC_CONTEXT = 'ft_stage_sync'


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    @api.model
    def _ft_backfill_date_closed(self):
        """Stamp a Closed Date on won/lost opportunities missing one.

        Idempotent: only records with ``date_closed`` unset are touched.
        Returns the number of records repaired, so it is usable from a shell
        or a server action as well as from the upgrade hook.
        """
        leads = self.with_context(active_test=False).search([
            ('type', '=', 'opportunity'),
            ('date_closed', '=', False),
            '|',
            ('active', '=', False),                 # lost
            ('stage_id.is_won', '=', True),         # won
        ])
        for lead in leads:
            # Writing date_closed alone does not touch probability, active or
            # stage_id, so crm.lead.write() passes the value straight through
            # instead of recomputing (or clearing) it.
            lead.date_closed = lead.date_last_stage_update or lead.write_date
        if leads:
            _logger.info(
                'ft_sales_dashboard: backfilled Closed Date on %s opportunities',
                len(leads))
        return len(leads)

    # ------------------------------------------------------------------
    # Lost opportunities belong in the Lost stage
    # ------------------------------------------------------------------
    @api.model
    def _ft_lost_stage(self):
        """The stage lost opportunities are parked in, empty if none exists.

        Matched by name rather than by a flag because ``crm.stage`` has
        ``is_won`` but no ``is_lost`` counterpart — the same way
        bt_crm_customization identifies its Cold / Won stages. ``active_test``
        is off so an archived Lost stage is still found; parking a dead deal in
        an archived stage is better than leaving it in Discussion.
        """
        return self.env['crm.stage'].with_context(active_test=False).search(
            [('name', '=ilike', LOST_STAGE_NAME)], order='sequence, id', limit=1)

    @api.model
    def _ft_won_stage(self):
        """The stage won opportunities are moved to, empty if none exists.

        ``crm.stage.is_won`` is a real flag, so unlike the Lost stage this needs
        no name matching. The first one in sequence order is taken; Odoo's own
        ``action_set_won`` prefers a won stage sitting after the lead's current
        one, which only differs on a pipeline with several won stages
        interleaved between standard ones. There is one here.
        """
        return self.env['crm.stage'].with_context(active_test=False).search(
            [('is_won', '=', True)], order='sequence, id', limit=1)

    def write(self, vals):
        """Keep ``stage_id`` in step with the outcome the write records.

        Odoo leaves the stage alone in both directions: ``action_set_lost``
        archives the record, and setting Probability to 100 wins it, neither
        touching ``stage_id``. The dashboard compensates by reading archived as
        lost and 100% as won, but a list view, an export or a pivot shows the
        raw stage — which is how a dead deal ends up displayed under Discussion
        and a won one under Demo, and why those reports could not be verified
        against the dashboard by eye.

        Only opportunities are moved, and only when the caller has not set a
        stage itself, so an explicit stage change always wins. The recordset is
        split rather than mutating ``vals`` for everyone, so writing to a mixed
        selection cannot drag leads or already-correct records along with it.
        """
        if vals.get('active') is False and 'stage_id' not in vals:
            stage = self._ft_lost_stage()
            if stage:
                movable = self.filtered(
                    lambda l: l.type == 'opportunity' and l.stage_id != stage)
                if movable:
                    rest = self - movable
                    res = super(CrmLead, movable).write(
                        dict(vals, stage_id=stage.id))
                    if rest:
                        res = super(CrmLead, rest).write(vals) and res
                    return res
            return super().write(vals)

        res = super().write(vals)
        # A win, unless the same write archives the record — an archived deal is
        # lost however high its probability was, and the branch above owns it.
        if (vals.get('probability', 0) >= WON_PROBABILITY
                and 'stage_id' not in vals and vals.get('active', True)):
            self._ft_move_to_won_stage()
        return res

    def _ft_move_to_won_stage(self):
        """Move the live opportunities in ``self`` into the Won stage.

        A SECOND write rather than folding ``stage_id`` into the first, which is
        how the Lost branch above does it. The mandatory-field rules in
        bt_crm_customization run at the END of its own ``write()``, against the
        recordset that write was called with — so a context applied part-way
        down the ``super()`` chain never reaches them, and the move is rejected
        for want of a Closed Amount nobody has typed. Starting a fresh write
        from the top, with the flag already on the recordset, does reach them.

        Not recursive: this write names ``stage_id``, which is what the branch
        above tests for before calling here.
        """
        stage = self._ft_won_stage()
        if not stage:
            _logger.warning(
                'ft_sales_dashboard: no stage flagged is_won; opportunities won '
                'by probability keep their original stage')
            return
        movable = self.filtered(
            lambda l: l.type == 'opportunity' and l.active and l.stage_id != stage)
        if movable:
            movable.with_context(**{STAGE_SYNC_CONTEXT: True}).write(
                {'stage_id': stage.id})

    @api.model
    def _ft_sync_lost_stage(self):
        """Move already-archived opportunities into the Lost stage.

        The write() hook above only catches losses from here on; the records
        archived before it existed still sit in their old stage. Idempotent —
        it only ever selects records that are NOT already in the Lost stage — so
        install and upgrade both running it is harmless.
        """
        stage = self._ft_lost_stage()
        if not stage:
            _logger.warning(
                'ft_sales_dashboard: no stage named "%s"; archived opportunities '
                'keep their original stage', LOST_STAGE_NAME)
            return 0
        leads = self.with_context(active_test=False).search([
            ('type', '=', 'opportunity'),
            ('active', '=', False),
            ('stage_id', '!=', stage.id),
        ])
        if leads:
            # probability MUST be in the write, and 0 is the correct value for a
            # lost deal anyway. crm.lead.write() ends a stage change into a
            # non-won stage with
            #     elif stage_updated and not stage_is_won and not 'probability' in vals:
            #         vals['date_closed'] = False
            # so moving these records on stage_id alone would silently clear the
            # Closed Date on every one of them — the exact field Sales Closed and
            # Opportunities Lost are measured on, which _ft_backfill_date_closed()
            # exists to populate. Naming probability skips that branch and the
            # existing Closed Dates survive.
            leads.write({'stage_id': stage.id, 'probability': 0})
            _logger.info(
                'ft_sales_dashboard: moved %s archived opportunities into the '
                '"%s" stage', len(leads), stage.name)
        return len(leads)


    @api.model
    def _ft_sync_won_stage(self):
        """Move already-won opportunities into the Won stage.

        The write() hook above only catches wins from here on; the deals won by
        probability before it existed still sit in the stage they were in when
        somebody typed 100. Idempotent — it only ever selects records that are
        NOT already in the Won stage.

        Archived records are left alone: they are lost, whatever probability
        they carry, and _ft_sync_lost_stage owns them.
        """
        stage = self._ft_won_stage()
        if not stage:
            _logger.warning(
                'ft_sales_dashboard: no stage flagged is_won; opportunities won '
                'by probability keep their original stage')
            return 0
        leads = self.search([
            ('type', '=', 'opportunity'),
            ('probability', '>=', WON_PROBABILITY),
            ('stage_id', '!=', stage.id),
        ])
        if not leads:
            return 0
        # crm.lead.write() re-stamps date_closed with "now" on any write
        # carrying probability >= 100:
        #     if vals.get('probability', 0) >= 100 or not vals.get('active', True):
        #         vals['date_closed'] = fields.Datetime.now()
        # and a move into a won stage sets that probability itself, so the real
        # closing dates are read first and written back after. Sales Closed is
        # measured on date_closed — without this every repaired deal would
        # abandon the month it was won in and pile into today's figures.
        closed = {lead.id: lead.date_closed for lead in leads}
        synced = leads.with_context(**{STAGE_SYNC_CONTEXT: True})
        synced.write({'stage_id': stage.id, 'probability': WON_PROBABILITY})
        for lead in synced:
            if closed[lead.id] and lead.date_closed != closed[lead.id]:
                lead.date_closed = closed[lead.id]
        _logger.info(
            'ft_sales_dashboard: moved %s won opportunities into the "%s" stage',
            len(leads), stage.name)
        return len(leads)


def post_init_hook(env):
    """Repair Closed Dates and Lost/Won stages on install and on every upgrade."""
    env['crm.lead']._ft_backfill_date_closed()
    env['crm.lead']._ft_sync_lost_stage()
    env['crm.lead']._ft_sync_won_stage()
