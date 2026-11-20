# -*- coding: utf-8 -*-
"""Idempotent merging of heartbeats into a timed visit.

Pure Python.  The client sends *cumulative* ``active_s`` / ``elapsed_s`` for a
visit, so merging is ``max()`` and therefore a duplicated, re-ordered or
retried heartbeat can never move totals backwards or double-count.

The server never trusts the client's elapsed time beyond what its *own* clock
allows (``now - started_at`` + grace), and active can never exceed elapsed.

Definitions
-----------
elapsed  wall-clock seconds since the visit started (visible or not)
active   seconds the tab was visible, focused and had recent input
idle     elapsed - active  (hidden, unfocused, or no input)
"""
from datetime import datetime

GRACE_SECONDS = 60


def merge_beat(state, beat, now):
    """Merge ``beat`` into ``state``; returns a *new* dict.

    state: started_at, elapsed_seconds, active_seconds, heartbeat_count,
           last_seq, state ('open'|'closed'|'stale')
    beat:  seq, active_s, elapsed_s, ended
    """
    started_at = state['started_at']
    server_cap = max(0, int((now - started_at).total_seconds())) + GRACE_SECONDS

    elapsed = min(max(state.get('elapsed_seconds', 0), beat['elapsed_s']), server_cap)
    active = min(max(state.get('active_seconds', 0), beat['active_s']), elapsed)

    new = dict(state)
    new['elapsed_seconds'] = elapsed
    new['active_seconds'] = active
    last_seq = state.get('last_seq', -1)
    if beat['seq'] > last_seq:           # only a *new* sequence number counts
        new['heartbeat_count'] = state.get('heartbeat_count', 0) + 1
        new['last_seq'] = beat['seq']
    new['last_beat_at'] = now
    if beat.get('ended') and state.get('state') == 'open':
        new['state'] = 'closed'
        new['ended_at'] = now
    return new


def idle_seconds(elapsed_seconds, active_seconds):
    return max(0, (elapsed_seconds or 0) - (active_seconds or 0))


def is_stale(last_beat_at, now, stale_minutes):
    if not isinstance(last_beat_at, datetime):
        return False
    return (now - last_beat_at).total_seconds() > stale_minutes * 60
