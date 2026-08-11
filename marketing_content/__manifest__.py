# -*- coding: utf-8 -*-
{
    "name": "Marketing Content",
    "version": "19.0.1.0.0",
    "category": "Marketing",
    "summary": "Marketing app with Articles, Pageviews, and Enquiries",
    "author": "Your Company",
    "license": "LGPL-3",
    # Project_Scorecards supplies group_scorecard_marketing, which gates the
    # Marketing root menu and each of its entries. It was already referenced
    # without being declared; declaring it fixes the load order.
    "depends": ["base","mail","Project_Scorecards"],
    "data": [
        "security/ir.model.access.csv",
        "views/marketing_views.xml",
    ],
    "application": True,
    "installable": True,
}
