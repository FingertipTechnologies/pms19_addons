"""Values shared by every model in the competency framework.

The 1-5 rating scale is the spine of the module: a job says which level it
needs, an assessment says which level the employee reached, and every score,
gap and readiness figure is arithmetic on the difference. Keeping the scale in
one place means the wording of "3 - Competent" is the same on the job matrix,
the assessment line and the development plan.
"""

# The rating scale, as Selection pairs. Stored as a Char digit rather than an
# Integer so the label travels with the value into filters and group headers.
RATING_SELECTION = [
    ('1', '1 - Needs Improvement'),
    ('2', '2 - Developing'),
    ('3', '3 - Competent'),
    ('4', '4 - Strong'),
    ('5', '5 - Expert / Role Model'),
]

# Top of the scale. Every percentage in the module is a rating expressed
# against this, so it is named rather than written as a bare 5.
MAX_RATING = 5

# How a competency counts towards the three headline scores. Core competencies
# are expected of everybody, functional ones belong to the craft of the job,
# and leadership ones only apply to people who lead.
SCOPE_SELECTION = [
    ('core', 'Core'),
    ('functional', 'Functional'),
    ('leadership', 'Leadership'),
]

# Readiness bands. Read as "at least this percent is this band", best first, so
# the first match wins.
READINESS_BANDS = [
    (90.0, 'ready'),
    (75.0, 'near_ready'),
    (60.0, 'progressing'),
    (0.0, 'developing'),
]

READINESS_SELECTION = [
    ('developing', 'Developing'),
    ('progressing', 'Progressing'),
    ('near_ready', 'Near Ready'),
    ('ready', 'Ready'),
]

# Weightages are floats, so "totals 100" has to allow for the last decimal
# place. Two decimals of tolerance matches the precision the field is shown at.
WEIGHTAGE_TOLERANCE = 0.01


def rating_to_int(value):
    """Return a Selection rating as an int, with an unset rating reading 0."""
    return int(value) if value else 0


def readiness_band(percent):
    """Return the readiness band a percentage falls in."""
    for floor, band in READINESS_BANDS:
        if percent >= floor:
            return band
    return 'developing'


def readiness_of(mandatory_lines, reached):
    """BR-016 and BR-017 for one person against one job.

    ``mandatory_lines`` are the job's mandatory matrix lines, ``reached`` maps
    competency id to the level the person has. Returns (percent, band), or
    (0.0, False) when the job has no mandatory competency to measure against.
    A critical gap - two levels or more short - on a mandatory competency
    holds the band at Near Ready however high the percentage runs.
    """
    if not mandatory_lines:
        return 0.0, False
    shortfalls = [
        reached.get(line.competency_id.id, 0) - rating_to_int(line.required_level)
        for line in mandatory_lines
    ]
    percent = sum(1 for short in shortfalls if short >= 0) / len(shortfalls) * 100.0
    band = readiness_band(percent)
    if band == 'ready' and any(short <= -2 for short in shortfalls):
        band = 'near_ready'
    return percent, band


# The two groups that may REVIEW somebody: a department manager, and an HR
# competency manager.
#
# Both have to be named, every time. They used to be one test, because
# HR implied the department manager group — and that is exactly what made the
# self-service menus impossible to get right: a menu shown to employees was
# shown to HR too, so "My Assessments" appeared for an admin who has no
# assessment of their own and, once widened to be useful, listed the whole
# company under a label that said "My". Since 19.0.1.2.0 HR is a group of its
# own, so anything that asks "is this person a reviewer?" asks about both.
COMPETENCY_MANAGER_GROUPS = (
    'ft_employee_competency.group_competency_manager',
    'ft_employee_competency.group_competency_hr_manager',
)


def is_competency_manager(env):
    """True for a department manager or an HR competency manager."""
    return any(env.user.has_group(group) for group in COMPETENCY_MANAGER_GROUPS)


def is_hr_manager(env):
    """True for an HR competency manager: the approver of the final review."""
    return env.user.has_group('ft_employee_competency.group_competency_hr_manager')


# ----------------------------------------------------------------------
# Outgoing mail
#
# Every competency email goes out from a fixed company mailbox, never from
# the person whose click triggered it: the cycle opening, the self
# assessment chasers and the completion notice come from HR, everything
# about the review and development process from the common support mailbox.
# A template's own email_from is not relied on - the templates are noupdate,
# so an address fixed there would never reach a database that already has
# them - the sender is passed with every send instead.
#
# The two addresses can be changed without code, through the system
# parameters named below (Settings > Technical > System Parameters).
# ----------------------------------------------------------------------
MAIL_SENDERS = {
    'hr': ('ft_employee_competency.hr_email', 'hr@fingertipplus.com'),
    'support': ('ft_employee_competency.support_email', 'support@fingertipplus.com'),
}


def competency_sender(env, kind):
    """The From address for a competency email of the given kind."""
    param, default = MAIL_SENDERS[kind]
    return env['ir.config_parameter'].sudo().get_param(param) or default


def join_emails(*values):
    """A comma-separated address list, blanks and duplicates dropped."""
    seen, emails = set(), []
    for value in values:
        for address in (value or '').split(','):
            address = address.strip()
            if address and address.lower() not in seen:
                seen.add(address.lower())
                emails.append(address)
    return ', '.join(emails)


def hr_emails(env):
    """The addresses of the HR competency managers - "HR/Admin"."""
    group = env.ref('ft_employee_competency.group_competency_hr_manager', raise_if_not_found=False)
    if not group:
        return ''
    return join_emails(*group.sudo().all_user_ids.filtered('active').mapped('email'))


def send_competency_mail(record, template_xmlid, kind, email_to=None, email_cc=None):
    """Send one competency email for ``record`` from the ``kind`` mailbox.

    ``email_to`` / ``email_cc`` replace the template's own recipients when
    given. Nothing is sent when there is nobody to send to.
    """
    template = record.env.ref(f'ft_employee_competency.{template_xmlid}', raise_if_not_found=False)
    if not template:
        return
    sender = competency_sender(record.env, kind)
    values = {'email_from': sender, 'reply_to': sender}
    if email_to is not None:
        if not email_to:
            return
        values['email_to'] = email_to
    if email_cc:
        values['email_cc'] = email_cc
    template.sudo().send_mail(record.id, force_send=False, email_values=values)

