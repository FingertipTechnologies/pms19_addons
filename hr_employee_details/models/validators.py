"""Shared field-format validators for the HR Employee Details module.

Every helper returns True when the value is acceptable. Empty values are
always accepted here: whether a field must be filled in is decided by the
`required` attribute in the views, not by these format checks.
"""
import re

# Letters (any language), spaces, dot, apostrophe and hyphen. No digits.
#   e.g. "K. Ramesh", "D'Souza", "Senior Software Engineer"
_ALPHA_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ .'\-]+[^\W\d_]+)*\.?$")

# Address: letters plus the punctuation an address needs. Digits are
# rejected separately in is_alpha_address().
_ALPHA_ADDRESS_CHARS_RE = re.compile(r"^[\w .,'\-/()#&\r\n]+$")

_DIGITS_RE = re.compile(r"^\d+$")
_PHONE_CHARS_RE = re.compile(r"^\+?[\d \-]+$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _clean(value):
    return (value or '').strip()


def is_alpha_name(value):
    """Names, job title, district, bank/branch name: letters only."""
    value = _clean(value)
    return not value or bool(_ALPHA_NAME_RE.match(value))


def is_alpha_address(value):
    """Address: letters and address punctuation, but no digits."""
    value = _clean(value)
    if not value:
        return True
    if re.search(r"\d", value) or "_" in value:
        return False
    return bool(_ALPHA_ADDRESS_CHARS_RE.match(value)) and bool(re.search(r"[^\W\d_]", value))


def is_digits(value, min_len=None, max_len=None):
    """Only the digits 0-9, optionally with a length range."""
    value = _clean(value)
    if not value:
        return True
    if not _DIGITS_RE.match(value):
        return False
    if min_len and len(value) < min_len:
        return False
    if max_len and len(value) > max_len:
        return False
    return True


def digits_only(value):
    """Strip everything except digits (used to compare phone numbers)."""
    return re.sub(r"\D", "", value or "")


def is_phone(value, min_digits=10, max_digits=13):
    """Phone / mobile: digits with an optional leading '+', spaces or hyphens.
    No letters. The number of digits must be within the given range."""
    value = _clean(value)
    if not value:
        return True
    if not _PHONE_CHARS_RE.match(value):
        return False
    return min_digits <= len(digits_only(value)) <= max_digits


def is_email(value):
    value = _clean(value)
    return not value or bool(_EMAIL_RE.match(value))


def is_pan(value):
    value = _clean(value).upper()
    return not value or bool(_PAN_RE.match(value))


def is_ifsc(value):
    value = _clean(value).upper()
    return not value or bool(_IFSC_RE.match(value))
