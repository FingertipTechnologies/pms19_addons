from odoo import models, fields
from odoo.exceptions import UserError

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    proposal_ids = fields.One2many(
        'crm.proposal', 
        'opportunity_id', 
        string='Proposals'
    )

    def action_create_new_proposal(self):
        # Proposals belong to a deal, so they are raised only after the lead has
        # been converted. The button is hidden on leads; this backs that up for
        # the ways the action can still be reached (a direct call, a saved
        # shortcut, an automation) rather than letting a proposal be attached to
        # a record that has no opportunity behind it yet.
        if self.type != 'opportunity':
            raise UserError(
                "A proposal can only be created on an opportunity. "
                "Convert this lead first."
            )
        return {
            'name': 'New Proposal',
            'type': 'ir.actions.act_window',
            'res_model': 'crm.proposal',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_opportunity_id': self.id,
                'default_name': f"Proposal for {self.name}"
            },
            'params': {'size': 'large'},
        }