from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    crm_erp_api_url = fields.Char(
        string="ERP Customer API URL",
        config_parameter="crm_erp_customer_sync.api_url",
        help="Arjun's ERP customer create/update API endpoint.",
    )

    crm_erp_api_token = fields.Char(
        string="ERP API Token",
        config_parameter="crm_erp_customer_sync.api_token",
        groups="base.group_system",
        help="Authentication token provided by the ERP team.",
    )

    crm_pms_receiver_token = fields.Char(
        string="ERP-to-CRM Receiver Bearer Token",
        config_parameter="crm_erp_customer_sync.receiver_token",
        groups="base.group_system",
        help="ERP must send this token when pushing existing ERP customers to CRM/PMS.",
    )
