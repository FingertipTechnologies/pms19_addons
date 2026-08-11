from odoo import models, fields

class CrmLead(models.Model):
    _inherit = 'crm.lead'

    proposal_ids = fields.One2many(
        'crm.proposal', 
        'opportunity_id', 
        string='Proposals'
    )

    def action_create_new_proposal(self):
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