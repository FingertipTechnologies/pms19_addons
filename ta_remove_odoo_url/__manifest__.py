{
    "name": "Remove Odoo in URL | Remove Odoo URL | Remove Odoo | Remove Odoo from URLs | Replace Odoo URL | Remove Odoo from URL | Remove Odoo URL | Remove Odoo Branding",
    "summary": """Looking to replace or remove /odoo from your website URL? Our premium Odoo module offers a seamless solution to clean up and customize your Odoo URLs for a professional look. 
        Eliminate the default /odoo/ path and boost your brand credibility with user-friendly, SEO-optimized URLs. Perfect for businesses aiming to improve their Odoo website experience, 
        our module works with odoo 19 and configurations. Easy to install, fully documented, and backed by expert support—buy now and give your Odoo site the clean, custom URLs it deserves. 
        Ideal for developers, agencies, and Odoo service providers, replace odoo in URL, remove odoo url, oodo url.""",
    "description": """
        🌐 **Professional URL Customization for Odoo 19**
        
        Transform your Odoo website into a branded, professional experience! This premium module removes the default `/odoo` path from your URLs, creating clean, custom URLs that enhance your brand credibility and provide a seamless user experience without Odoo branding.
        
        **✨ Key Features:**
        
        🔗 **Clean URL Structure**
        - Remove `/odoo` from all URLs
        - Custom domain integration
        - Professional URL appearance
        - Brand-focused web presence
        
        🎯 **Brand Enhancement**
        - Eliminate Odoo branding
        - Professional website appearance
        - Enhanced brand credibility
        - Custom domain support
        
        ⚙️ **Easy Configuration**
        - Simple setup process
        - Automatic URL rewriting
        - No complex configuration
        - Immediate effect after installation
        
        📱 **SEO Optimization**
        - Clean, professional URLs
        - Better search engine visibility
        - Improved user experience
        - Professional web presence
        
        **🔧 Technical Features:**
        - Odoo 19 compatible
        - Automatic URL rewriting
        - Clean installation process
        - Performance optimized
        
        **💡 Perfect For:**
        - Professional businesses
        - Brand-focused companies
        - Agencies and consultants
        - Companies wanting custom URLs
        
        **🎯 Business Benefits:**
        - Enhanced brand credibility
        - Professional web presence
        - Better user experience
        - Custom domain integration
        
        **📱 User Experience:**
        - Clean, professional URLs
        - Seamless navigation
        - Brand-focused experience
        - Professional appearance
        
        **🔄 URL Customization:**
        - Remove Odoo branding
        - Custom domain support
        - Professional URL structure
        - Brand enhancement
        
        **📊 Installation Features:**
        - Easy setup process
        - Automatic configuration
        - Clean uninstall process
        - Professional standards
        
        **💼 Use Cases:**
        - Professional websites
        - Brand-focused businesses
        - Custom domain integration
        - Professional web presence
        
        Transform your Odoo website with professional URL customization!
    """,
    "version": "19.0.0.1.2",
    "category": "Extra Tools",
    'author': "Mountain Tran",
    'support': "mountaintran2021@gmail.com",
'website': "https://mountain-coder.com",
    'license': 'OPL-1',
    'price': 10,
    'currency': 'EUR',
    "depends": ["web",'base'],
    'images': [
        'static/description/banner.png',
    ],
    "installable": True,
    'application': False,
    'auto_install': False,
    "data": [
          'data/ir_config_parameter.xml',
          'views/ir_config_parameter_views.xml'
      ],
    "assets": {
        "web.assets_backend": [
            "ta_remove_odoo_url/static/src/**/*",
        ],
    },
    'uninstall_hook': '_uninstall_cleanup',
}
