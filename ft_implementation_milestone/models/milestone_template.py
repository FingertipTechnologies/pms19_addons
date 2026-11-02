# -*- coding: utf-8 -*-
"""Milestone templates: the named milestones every Implementation project
starts with.

Since 19.0.1.2.0 a template IS one milestone (Advance, BRD Approval, After
Sandbox Review, ...): the Milestone Templates menu lists them directly, there
is no parent "plan" record and no percentage on them. When an Implementation
project is created (with no milestone of its own) every active template is
copied onto it as a project.custom.milestone with 0% and no due date; the
Project Manager then enters the agreed percentages during KICKOFF, and the
100% rule (project_project._pwf_transition_missing) gates the move to DISC.

The percent helpers below are shared with the project side and the change
requests (the plan on the project still has to total 100%).
"""
from odoo import _, fields, models
from odoo.tools import float_compare

# Percent totals are compared to this many decimals (0.01%).
PERCENT_DIGITS = 2

# The Implementation lifecycle stage keys (project.project.stage._ft_stage_key)
# a template may be tagged with. Informational only: it tells the reader
# which delivery stage the payment belongs to and is not enforced anywhere.
STAGE_KEY_SELECTION = [
    ('kickoff', 'KICKOFF'),
    ('disc', 'DISC'),
    ('dev', 'DEV'),
    ('reg', 'REG'),
    ('srv', 'SRV'),
    ('uat', 'UAT'),
    ('data', 'DATA'),
    ('tra', 'TRA'),
    ('support', 'SUPPORT'),
    ('closed', 'CLOSED'),
]


def ft_percent_is_100(total):
    """True when ``total`` is 100% within PERCENT_DIGITS."""
    return float_compare(total, 100.0, precision_digits=PERCENT_DIGITS) == 0


def ft_format_percent(value):
    """'70', '33.33': the percentage as people write it, no trailing zeros."""
    text = ('%.2f' % (value or 0.0)).rstrip('0').rstrip('.')
    return text or '0'


class FtMilestoneTemplate(models.Model):
    _name = 'ft.milestone.template'
    _description = 'Implementation Milestone Template'
    _order = 'sequence, id'

    name = fields.Char(string='Milestone', required=True, translate=True)
    sequence = fields.Integer(
        default=10,
        help='Order in which the milestones are added to a new project.')
    active = fields.Boolean(
        default=True,
        help='Archived templates are no longer added to new projects.')
    stage_key = fields.Selection(
        STAGE_KEY_SELECTION, string='Delivery Stage',
        help='The lifecycle stage this payment belongs to. For information '
             'only; it does not drive the milestone.')
    description = fields.Text(
        string='Description',
        help='Copied onto the project milestone as its description.')

    _name_unique = models.Constraint(
        'UNIQUE(name)',
        'A milestone template with this name already exists.')

    def _ft_milestone_vals(self, project=None):
        """project.custom.milestone values for this template: 0% and no due
        date (both are agreed per project during KICKOFF), no amount (there
        is no percentage to apply to the contract value yet). Without
        ``project`` the values are meant for a One2many create command."""
        self.ensure_one()
        vals = {
            'name': self.name,
            'description': self.description or False,
            'percentage': 0.0,
            'amount': 0.0,
            'status': 'not_started',
        }
        if project is not None:
            vals['project_id'] = project.id
        return vals

    def copy_data(self, default=None):
        default = dict(default or {})
        vals_list = super().copy_data(default=default)
        for template, vals in zip(self, vals_list):
            if 'name' not in default:
                vals['name'] = _("%s (copy)", template.name)
        return vals_list
