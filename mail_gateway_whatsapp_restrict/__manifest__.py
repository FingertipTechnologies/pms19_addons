{
    "name": "Mail Whatsapp Gateway Restrict",
    "summary": "Restrict WhatsApp gateway access to Sales and Marketing teams",
    "version": "19.0.1.0.0",
    "license": "AGPL-3",
    "author": "FingertipTech",
    "category": "Marketing",
    "depends": [
        "mail_gateway",
        "mail_gateway_whatsapp",
        "ft_message_tracking",
        "sales_team",
        "mass_mailing",
    ],
    "data": [
        "security/ir.model.access.csv",
        "security/whatsapp_restrict_security.xml",
        "views/menu_overrides.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "mail_gateway_whatsapp_restrict/static/src/**/*",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
