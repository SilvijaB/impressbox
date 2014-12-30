# -*- coding: utf-8 -*-

{
    'name': 'ImpressBox',
    'version': '1.0',
    'category': '',
    'description': """ImpressBox""",
    'author': 'AKS',
    'website': '',
    'license': 'AGPL-3',
    'depends': ['crm'],
    'init_xml': [],
    'data': [
             'impressbox_view.xml',
             'wizard/impressbox_billing_view.xml',
             'security/impressbox_security.xml',
             'security/ir.model.access.csv',
            ],
    'update_xml': [],
    'test': [
             'test/impressbox_test_users.yml',
             'test/impressbox_test_products.yml',
             'test/impressbox_test_payment_plans.yml',
             'test/impressbox_test_devices.yml',
             'test/impressbox_test_activities.yml',
             'test/impressbox_billing.yml',
            ],
    'demo_xml': [],
    'active': True,
    'installable': True,
}

