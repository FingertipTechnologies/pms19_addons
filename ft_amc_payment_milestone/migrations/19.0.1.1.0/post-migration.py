# -*- coding: utf-8 -*-
"""19.0.1.1.0, after the module is updated: rename the existing AMC monthly
milestones to the clarified naming.

19.0.1.0.0 named them "AMC Support – <Month YYYY>" (en dash) with the code
"AMC-YYYY-MM"; from 19.0.1.1.0 they read "Support Services for <Month YYYY>"
and "SS-YYYY-MM" (project.custom.milestone._amc_milestone_name / _code).
Only milestones that still carry the old pattern are touched: a name or code
somebody edited by hand is theirs and stays. The new values come from the
same helpers the creation uses, so renamed and newly created milestones
cannot drift apart. Tracking is disabled so no "name changed" message is
posted on every historical milestone; a single note is posted instead.

The previously generated task Excel does not exist for these milestones (the
feature is new); it is produced the next time one is completed or with the
"Generate Task Excel" button, so nothing to attach here.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

OLD_NAME_PREFIXES = ('AMC Support – ', 'AMC Support - ')
OLD_CODE_PREFIX = 'AMC-'


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True, 'mail_notrack': True})
    Milestone = env['project.custom.milestone']
    milestones = Milestone.with_context(active_test=False).search([
        ('is_amc_monthly', '=', True), ('amc_period_start', '!=', False)])
    renamed = 0
    for milestone in milestones:
        period = milestone.amc_period_start
        vals = {}
        old_names = {prefix + Milestone._amc_period_label(period) for prefix in OLD_NAME_PREFIXES}
        if (milestone.name or '') in old_names:
            vals['name'] = Milestone._amc_milestone_name(period)
        if (milestone.milestone_id or '') == OLD_CODE_PREFIX + period.strftime('%Y-%m'):
            vals['milestone_id'] = Milestone._amc_milestone_code(period)
        if not vals:
            continue
        milestone.write(vals)
        milestone.message_post(body=env._(
            "Renamed to '%(name)s' (%(code)s) by the 19.0.1.1.0 update.",
            name=milestone.name, code=milestone.milestone_id or ''))
        renamed += 1
    _logger.info("ft_amc_payment_milestone 19.0.1.1.0: %s AMC monthly milestone(s) renamed "
                 "(of %s)", renamed, len(milestones))
