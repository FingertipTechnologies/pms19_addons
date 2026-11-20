# -*- coding: utf-8 -*-
"""Normalisation, comparison and formatting of field values.

Pure Python.  Values arrive as returned by ``records.read(load=None)``:
dates/datetimes are python objects, many2one is an id (or False), x2many is a
list of ids, selection is its key, empty char/text/html is False.

Rules
-----
* Comparison is done on a *canonical* value, never on formatted text, so
  truncation can never hide a real change.
* ``False`` / ``''`` / ``None`` are all "empty" for non-boolean fields.
* Sensitive fields are identified by name and are never read nor stored.
"""
import json

MASKED_VALUE = '***masked***'

SENSITIVE_SUBSTRINGS = (
    'password', 'passwd', 'passphrase', 'secret', 'api_key', 'apikey',
    'private_key', 'access_key',
)
SENSITIVE_TOKENS = frozenset({
    'token', 'totp', 'otp', 'credential', 'credentials', 'pwd', 'pin',
})

SYSTEM_FIELDS = frozenset({
    'id', 'create_uid', 'create_date', 'write_uid', 'write_date',
    '__last_update', 'display_name', 'access_token', 'access_url',
    'access_warning', 'has_message', 'my_activity_date_deadline',
})
SYSTEM_PREFIXES = ('message_', 'activity_', 'website_message_', 'rating_')

SKIPPED_TYPES = frozenset({
    'binary', 'image', 'properties', 'properties_definition', 'serialized',
})
X2MANY_TYPES = frozenset({'one2many', 'many2many'})


def is_sensitive_name(name):
    """True when a technical field name looks like a credential/secret."""
    lowered = (name or '').lower()
    if any(part in lowered for part in SENSITIVE_SUBSTRINGS):
        return True
    return any(token in SENSITIVE_TOKENS for token in lowered.split('_'))


def is_system_field(name):
    """Audit plumbing that changes on every save and says nothing about adoption."""
    if name in SYSTEM_FIELDS:
        return True
    return name.startswith(SYSTEM_PREFIXES)


def comparable(ftype, value):
    """Canonical, hashable, type-stable representation of a field value."""
    if ftype == 'boolean':
        return bool(value)
    if value is None or value is False:
        return None
    if ftype in ('char', 'text', 'html', 'selection', 'reference'):
        return None if value == '' else str(value)
    if ftype in ('integer', 'many2one', 'many2one_reference'):
        return int(value)
    if ftype in ('float', 'monetary'):
        return round(float(value), 6)
    if ftype == 'date':
        return value.isoformat() if hasattr(value, 'isoformat') else str(value)
    if ftype == 'datetime':
        if hasattr(value, 'strftime'):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return str(value)
    if ftype in X2MANY_TYPES:
        return tuple(sorted(int(i) for i in (value or ())))
    if ftype == 'json':
        return json.dumps(value, sort_keys=True, default=str)
    return str(value)


def changed(ftype, old, new):
    """Whether two raw values differ *in meaning*."""
    return comparable(ftype, old) != comparable(ftype, new)


def x2many_delta(old, new):
    """Return (added_ids, removed_ids) for two canonical x2many tuples."""
    old_set, new_set = set(old or ()), set(new or ())
    return sorted(new_set - old_set), sorted(old_set - new_set)


def clip(text, max_len):
    if text is None:
        return None
    text = str(text)
    if max_len and len(text) > max_len:
        return text[: max(max_len - 1, 1)] + '\u2026'
    return text


def _fmt_float(value):
    text = ('%.6f' % value).rstrip('0').rstrip('.')
    return '0' if text in ('', '-0') else text


def format_value(ftype, comp, *, display=None, selection=None, masked=False,
                 max_len=255, delta=None):
    """Human readable text for a canonical value (see :func:`comparable`).

    ``display`` maps record id -> display name, ``selection`` maps key -> label,
    ``delta`` is (added, removed) for x2many so a 400-line order is stored as
    "+3 -1" rather than 400 ids.  Returns None for empty values.
    """
    if masked:
        return MASKED_VALUE if (comp is not None and comp != ()) else None
    if comp is None:
        return None
    display = display or {}
    if ftype == 'boolean':
        return 'True' if comp else 'False'
    if ftype in ('float', 'monetary'):
        return clip(_fmt_float(comp), max_len)
    if ftype in ('many2one', 'many2one_reference'):
        name = display.get(comp)
        return clip('%s [#%s]' % (name, comp) if name else '[#%s]' % comp, max_len)
    if ftype in X2MANY_TYPES:
        if delta is not None:
            added, removed = delta
            parts = []
            if added:
                parts.append('+%s' % ', '.join('#%s' % i for i in added[:20]))
            if removed:
                parts.append('-%s' % ', '.join('#%s' % i for i in removed[:20]))
            return clip(' '.join(parts) or '(no change)', max_len)
        return clip('%d record(s): %s' % (
            len(comp), ', '.join('#%s' % i for i in comp[:20])), max_len)
    if ftype == 'selection' and selection:
        label = selection.get(comp)
        if label and label != comp:
            return clip('%s (%s)' % (label, comp), max_len)
    return clip(comp, max_len)
