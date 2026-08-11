{
    'name': 'FT Message Tracking',
    'version': '19.0.1.0.0',
    'category': 'Tools',
    'summary': 'Outbound message tracking for WhatsApp and Email',
    'description': """
        FingertipTech Message Tracking
        ==============================
        - Logs outbound WhatsApp and Email messages
        - Tracks open status, open count, and last opened time
        - Provides a single store other modules (WhatsApp, Email)
          can write to and read from
    """,
    'author': 'FingertipTech',
    'website': 'https://www.fingertiptech.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'contacts',
        'mail_gateway_whatsapp',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/message_tracking_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ft_message_tracking/static/src/components/chatter/chatter_patch.esm.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
