"""Queue Won opportunities for CRM/PMS-to-ERP scheduled synchronization."""
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    def _is_erp_customer_won(self):
        self.ensure_one()
        if self.type != 'opportunity' or not self.active:
            return False
        if self.probability >= 100:
            return True
        if not self.stage_id:
            return False
        if 'is_won' in self.stage_id._fields and self.stage_id.is_won:
            return True
        return (self.stage_id.name or '').strip().lower() == 'won'

    def _get_erp_customer_company(self):
        self.ensure_one()
        # account_id is supplied by some CRM customizations; standard CRM uses partner_id.
        account = self.account_id if 'account_id' in self._fields else False
        partner = account or self.partner_id
        return partner.commercial_partner_id if partner else self.env['res.partner']

    def _queue_won_customer(self):
        handled = set()
        for lead in self:
            if lead._is_erp_customer_won():
                company = lead._get_erp_customer_company()
                if company and company.is_company and company.id not in handled:
                    handled.add(company.id)
                    company._set_customer_account_status()
                    company._queue_erp_customer()
                    # No HTTP call here: the cron sends this queued company to ERP.

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._queue_won_customer()
        return records

    def write(self, vals):
        was_won = {lead.id: lead._is_erp_customer_won() for lead in self}
        result = super().write(vals)
        newly_won = self.filtered(lambda lead: not was_won.get(lead.id, False) and lead._is_erp_customer_won())
        if newly_won:
            newly_won._queue_won_customer()
        return result

    def action_sync_won_customers(self):
        """Queue previously Won companies for the next CRM -> ERP cron run."""
        handled = set()
        for lead in self:
            if not lead._is_erp_customer_won():
                continue
            company = lead._get_erp_customer_company()
            if company and company.is_company and company.id not in handled:
                handled.add(company.id)
                company._set_customer_account_status()
                company._queue_erp_customer()
        return True
