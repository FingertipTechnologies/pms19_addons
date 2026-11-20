# -*- coding: utf-8 -*-
"""Strict validation of browser-originated tracking payloads.

Pure Python.  The browser is *not trusted*: it can neither name a user (the
server uses ``env.uid``), nor send unbounded data, nor claim arbitrary times.
Everything that survives validation is a plain dict with a fixed set of keys.
"""
import re

MAX_EVENTS_PER_REQUEST = 50
MAX_PAYLOAD_KEYS = 4
KEY_RE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
MODEL_RE = re.compile(r'^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$')
MAX_SECONDS = 86400
CLOCK_PAST_MS = 24 * 3600 * 1000       # tolerate a queued offline batch
CLOCK_FUTURE_MS = 5 * 60 * 1000        # but not clocks set into the future

VISIT_EVENT_TYPES = ('page_view', 'record_view', 'list_view', 'report_view',
                     'dashboard_view', 'session_start')
SIGNAL_EVENT_TYPES = ('search', 'action_click')
VISIT_KINDS = ('record', 'list', 'form_new', 'analysis', 'dashboard', 'client',
               'other')


def _s(value, limit):
    if value is None or value is False:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _key(value):
    return value if isinstance(value, str) and KEY_RE.match(value) else None


def _model(value):
    if isinstance(value, str) and len(value) <= 80 and MODEL_RE.match(value):
        return value
    return None


def _int(value, lo=0, hi=MAX_SECONDS):
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(number, hi))


def resolve_event_ms(claimed_ms, server_now_ms):
    """Trust a claimed instant only inside a sane window around server time,
    otherwise fall back to server time (client clocks drift or lie)."""
    try:
        claimed = int(claimed_ms)
    except (TypeError, ValueError):
        return server_now_ms
    if claimed < server_now_ms - CLOCK_PAST_MS or claimed > server_now_ms + CLOCK_FUTURE_MS:
        return server_now_ms
    return claimed


def validate_event(raw, server_now_ms):
    """Return ``(clean_dict, None)`` or ``(None, reason)``."""
    if not isinstance(raw, dict):
        return None, 'not_an_object'
    kind = raw.get('t')
    key = _key(raw.get('key'))
    if key is None:
        return None, 'bad_key'
    if kind == 'visit':
        ev = raw.get('ev')
        if ev not in VISIT_EVENT_TYPES:
            return None, 'bad_event_type'
        vkind = raw.get('kind') if raw.get('kind') in VISIT_KINDS else 'other'
        model = _model(raw.get('model'))
        if raw.get('model') and model is None:
            return None, 'bad_model'
        return {
            't': 'visit', 'key': key,
            'browser_session': _key(raw.get('bs')),
            'event_type': ev, 'kind': vkind, 'model': model,
            'record_id': _int(raw.get('rid'), 1, 2 ** 31 - 1),
            'action_identifier': _s(raw.get('aid'), 120),
            'page_name': _s(raw.get('name'), 120),
            'view_type': _s(raw.get('vt'), 30),
            'ts': resolve_event_ms(raw.get('ts'), server_now_ms),
        }, None
    if kind == 'beat':
        seq = _int(raw.get('seq'), 0, 10 ** 9)
        active = _int(raw.get('act'))
        elapsed = _int(raw.get('ela'))
        if seq is None or active is None or elapsed is None:
            return None, 'bad_beat'
        return {'t': 'beat', 'key': key, 'seq': seq,
                'active_s': min(active, elapsed), 'elapsed_s': elapsed,
                'ended': bool(raw.get('end'))}, None
    if kind == 'signal':
        ev = raw.get('ev')
        if ev not in SIGNAL_EVENT_TYPES:
            return None, 'bad_event_type'
        model = _model(raw.get('model'))
        if raw.get('model') and model is None:
            return None, 'bad_model'
        return {'t': 'signal', 'key': key, 'event_type': ev, 'model': model,
                'browser_session': _key(raw.get('bs')),
                'action_identifier': _s(raw.get('aid'), 120),
                'ts': resolve_event_ms(raw.get('ts'), server_now_ms)}, None
    return None, 'bad_type'


def validate_payload(payload, server_now_ms):
    """Validate a whole request: ``(events, rejected_count, error_or_None)``."""
    if not isinstance(payload, dict) or len(payload) > MAX_PAYLOAD_KEYS:
        return [], 0, 'bad_payload'
    raw_events = payload.get('events')
    if not isinstance(raw_events, list):
        return [], 0, 'bad_payload'
    if len(raw_events) > MAX_EVENTS_PER_REQUEST:
        return [], 0, 'too_many_events'
    clean, rejected, seen = [], 0, set()
    for raw in raw_events:
        event, _reason = validate_event(raw, server_now_ms)
        if event is None:
            rejected += 1
            continue
        ident = (event['t'], event['key'], event.get('seq'))
        if ident in seen:           # same (type,key,seq) twice in one request
            rejected += 1
            continue
        seen.add(ident)
        clean.append(event)
    return clean, rejected, None


class SlidingWindowLimiter:
    """Per-key event budget over a sliding window (in-process, thread safe).

    Bounds what one browser can write per minute regardless of how many tabs it
    has open.  Each worker keeps its own counters, so the effective cap in a
    multi-worker deployment is ``workers x max_events``: a safety valve against
    runaway clients, not a security boundary.
    """

    def __init__(self, max_events=600, window_seconds=60.0, clock=None, max_keys=5000):
        import threading
        import time
        from collections import deque
        self._deque = deque
        self.max_events = max_events
        self.window = window_seconds
        self.clock = clock or time.monotonic
        self.max_keys = max_keys
        self._hits = {}
        self._lock = threading.Lock()

    def allow(self, key, n=1):
        now = self.clock()
        with self._lock:
            dq = self._hits.setdefault(key, self._deque())
            while dq and now - dq[0][0] > self.window:
                dq.popleft()
            if sum(count for _t, count in dq) + n > self.max_events:
                return False
            dq.append((now, n))
            if len(self._hits) > self.max_keys:      # bound memory
                for stale in [k for k, v in self._hits.items() if not v][: self.max_keys // 2]:
                    self._hits.pop(stale, None)
            return True
