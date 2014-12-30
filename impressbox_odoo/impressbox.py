# -*- coding: utf-8 -*-

import openerp
from openerp import models, fields, api, _
from openerp.exceptions import except_orm
from openerp.tools.safe_eval import safe_eval
from openerp.http import request

from datetime import date, datetime
import calendar

import requests
import ast

GET_PAYMENT_PLANS_QUERY = """SELECT model, name
                             FROM ir_model
                             WHERE model ilike 'payment.plan.%'
                             ORDER BY id"""


class crm_case_industry(models.Model):
    _description = "Industry"
    _name = "crm.case.industry"
    _order = "name asc"

    name = fields.Char(string='Name', translate=True)


class crm_lead(models.Model):
    _inherit = "crm.lead"
    _name = "crm.lead"

    nbr_subdivision = fields.Integer('Number of Subdivisions')
    nbr_screen = fields.Integer('Number of Screens')
    service_type = fields.Selection([('acquisition', 'Acquisition'),
                                      ('lease', 'Lease')], string='Service Type')
    industry = fields.Many2one('crm.case.industry', string='Industry')


class payment_plan(models.AbstractModel):
    _name = "payment.plan"
    _description = "Payment Plan Abstract"
    _order = "payment_plan_name asc"
    _rec_name = "payment_plan_name"

    payment_plan_name = fields.Char(string='Name', translate=True, required=True)


class payment_plan_standard(models.Model):
    _inherit = "payment.plan"
    _name = "payment.plan.standard"
    _description = "Standard Payment Plan"

    product_id = fields.Many2one('product.product', string='Monthly Product', required=True)

    @api.model
    def execute_billing(self, device):
       return {'product_id': self.product_id.id}


class payment_plan_data(models.Model):
    _inherit = "payment.plan.standard"
    _name = "payment.plan.data"
    _description = "Data Payment Plan"

    data_product_id = fields.Many2one('product.product', string='Data Product', required=True)


class main_impressbox(models.Model):
    _name = "main.impressbox"
    _rec_name = "identifier"

    @api.model
    def _get_payment_plans(self):
        self._cr.execute(GET_PAYMENT_PLANS_QUERY)
        return self._cr.fetchall()

    identifier = fields.Char(string='Identifier', readonly=True)
    pin_code = fields.Char(string='PIN Code', readonly=True)
    user_id = fields.Integer('ImpressBox User', readonly=True)
    payment_plan = fields.Reference(selection='_get_payment_plans')


class impressbox_activity(models.Model):
    _name = "impressbox.activity"
    _rec_name = 'device_id'

    device_id = fields.Many2one('main.impressbox', string="ImpressBox", required=True)
    date_start = fields.Datetime('Date Start', required=True)
    date_stop = fields.Datetime('Date Stop')

    @api.one
    @api.constrains('device_id', 'date_start', 'date_stop')
    def _check_date_stop(self):
        if self.date_stop < self.date_start and self.date_stop != False:
            raise Warning(_('Date Stop cannot be set before Start Date.'))

        device_activities = self.search([('device_id','=',self.device_id.id),('id','!=',self.id)])
        if len(device_activities) > 0:
            for device in device_activities:
                if (device.date_start < self.date_start and (device.date_stop > self.date_start or device.date_stop == False)) or \
                (self.date_start < device.date_start and (self.date_stop > device.date_start or self.date_stop == False)):
                    raise Warning(_('Device activity dates are overlapping!'))

    @api.model
    def get_days_in_month(self, period):
        period_start = datetime.strptime(period.date_start,'%Y-%m-%d')
        period_year = period_start.strftime('%Y')
        period_month = period_start.strftime('%m')
        weekday_of_first_day, days_in_month = calendar.monthrange(int(period_year),int(period_month))
        return days_in_month

    @api.model
    def execute_billing(self, device, period):
        res = {}
        date_format = '%Y-%m-%d'
        amount_ratio = 0.0
        days_in_month = self.get_days_in_month(period)
        device_activities = self.search([('device_id','=',device.id)])
        if len(device_activities.ids) == 0:
            self.create({'device_id': device.id, 'date_start': date.today()})
            return res
        for act in device_activities:
            date_start = period.date_start
            date_stop = period.date_stop
            if act.date_start > date_stop or (act.date_stop < date_start and act.date_stop != False):
                continue
            elif act.date_start > date_start and act.date_start <= date_stop:
                date_start = datetime.strptime(act.date_start,'%Y-%m-%d %H:%M:%S').strftime(date_format)

            if act.date_stop >= period.date_start and act.date_stop < date_stop:
                date_stop = datetime.strptime(act.date_stop,'%Y-%m-%d %H:%M:%S').strftime(date_format)
            days = (datetime.strptime(date_stop,date_format) - datetime.strptime(date_start,date_format)).days + 1
            amount_ratio += float(days) / days_in_month
        res['amount_ratio'] = amount_ratio
        return res

class main_impressboxhost(models.Model):
    _name = "main.impressboxhost"
    _rec_name = "label"

    
    label = fields.Char(string='Label', readonly=True)
    host = fields.Char(string='Host', readonly=True)
    secret = fields.Char(string='Secret', readonly=True)


class res_partner(models.Model):
    _inherit = "res.partner"
    _name = "res.partner"

    @api.model
    def _get_payment_plans(self):
        self._cr.execute(GET_PAYMENT_PLANS_QUERY)
        return self._cr.fetchall()

    default_payment_plan = fields.Reference(selection='_get_payment_plans')
    billing_periods = fields.One2many('partner.billing.period', 'partner_id', string="Successful Billing Periods", readonly=True)
    impressbox_host_id = fields.Many2one('main.impressboxhost', string="ImpressBox Host")
    secret = fields.Char(string="Secret Code")

    @api.model
    def execute_billing(self, period):
        # return: False, when there is no user with partner_id = self.id and oauth_uid != False
        #         List of Invoice IDs created (one invoice id per partner or [])
        result = {}
        billing_details = []
        user = self.env['res.users'].search([('partner_id','=',self.id)], limit=1)
        oauth_provider = self.env['auth.oauth.provider'].search(['|',('name','like','ImpressBox'),('name','like','Impress Box')], limit=1)
        oauth_uid = user.oauth_uid
        if oauth_uid == False:
            return False
        if oauth_uid != False and (user.oauth_provider_id.id != False and len(oauth_provider.ids) == 0):
            return False
        devices = self.env['main.impressbox'].search([('user_id','=',int(oauth_uid))])
        for device in devices:
            billing_dict = {}
            payment_plan = device.payment_plan
            if payment_plan == False:
                if self.default_payment_plan != False:
                    payment_plan = self.default_payment_plan
                else:
                    raise except_orm(_('Error!'),
                                     _('Please define Payment Plan for ImpressBox with identifier: %s\n or define Default Payment Plan for partner: %s.') % (device.identifier, self.name))
            product = payment_plan.execute_billing(device)
            amount = self.env['impressbox.activity'].execute_billing(device, period)
            if 'amount_ratio' in amount:
                if amount['amount_ratio'] > 0.0:
                    billing_dict.update(product) 
                    billing_dict.update(amount)
                    billing_details.append(billing_dict)
        result.update({self: billing_details})
        invoice = self.create_invoice(result)
        self.update_billing_periods(period, invoice)
        return invoice

    @api.model
    def update_billing_periods(self, period, invoice):
        billing_period_obj = self.env['partner.billing.period']
        billing_periods = billing_period_obj.search([('partner_id','=',self.id),('period_id','=',period.id)]).ids
        if len(billing_periods) == 0:
            values = {'partner_id': self.id, 'period_id': period.id}
            if len(invoice) != 0:
                values.update({'invoice_id': invoice[0]})
            billing_period_obj.create(values)
        return True

    @api.model
    def create_invoice(self, billing_data):
        invoice_ids = []
        for partner in billing_data.keys():
            if billing_data[partner] == []:
                return invoice_ids
            invoice_values = {
                              'partner_id': partner.id,
                              'date_invoice': date.today(),
                              'company_id': partner.company_id.id,
                              'origin': 'ImpressBox Billing Wizard',
                              'type': 'out_invoice',
                              'account_id': partner.property_account_receivable.id,
                              'invoice_line': [(6,0,self.create_invoice_line(billing_data[partner], partner))],
                              'currency_id': partner.property_product_pricelist.currency_id.id or partner.company_id.currency_id.id,
                              'fiscal_position': partner.property_account_position.id,
                              'journal_id': self.get_company_journal_id(partner.company_id)[0].id,
                             }
            invoice = self.env['account.invoice'].create(invoice_values)
            invoice.button_compute()
            invoice_ids.append(invoice.id)
        return invoice_ids

    @api.model
    def get_company_journal_id(self, company_id):
        journal_ids = self.env['account.journal'].search([('type', '=', 'sale'),
                                                          ('company_id', '=', company_id.id)], limit=1)
        if not journal_ids:
            raise except_orm(_('Error!'),
                             _('Please define sales journal for this company: "%s" (id:%d).') % (company_id.name, company_id.id))
        return journal_ids

    @api.model
    def create_invoice_line(self, data, partner):
        inv_line_obj = self.env['account.invoice.line']
        fpos_obj = self.env['account.fiscal.position']
        create_ids = []
        sum = dict()
        for product in data:
            product_id = self.env['product.product'].browse(product['product_id'])
            taxes = partner.property_account_position.map_tax(product_id.taxes_id)
            price = self.get_price_unit(product_id, partner, product['amount_ratio']) 
            prod = product_id.id
            if prod in sum:
                sum[prod]['quantity'] += product['amount_ratio']
            else: 
                sum[prod] = {
                             'name': product_id.name,
                             'account_id': partner.property_account_receivable.id,
                             'price_unit': price or product_id.list_price or 0.0,
                             'quantity': product['amount_ratio'],
                             'uos_id': product_id.uos_id.id or product_id.uom_id.id or False,
                             'product_id': prod,
                             'invoice_line_tax_id': [(6,0,taxes.ids)],
                             }
        for prod in sum:
            lines = inv_line_obj.create(sum[prod])
            create_ids.append(lines.id)
        return create_ids

    @api.model
    def get_price_unit(self, product_id, partner, amount):
        price_unit = 0.0
        pricelist = partner.property_product_pricelist
        if not pricelist:
            raise Warning( _('No Pricelist! You have to set a pricelist for a customer: %s!' % partner.name))
        else:
            price = pricelist.with_context({
                        'uom': product_id.uos_id.id or product_id.uom_id.id,
                        }).price_get(
                    product_id.id, amount or 1.0, partner.id)[pricelist.id]
            if price is False:
                raise Warning(_("No valid pricelist line found! Cannot find a pricelist line matching this product and quantity.\nYou have to change either the product, the quantity or the pricelist."))

            else:
                price_unit =  price
        return price_unit

    @api.model
    def create(self, values):
        res = super(res_partner, self).create(values)
        if 'user_created' not in self._context and ('is_company' in values and values['is_company'] != False):
            values.update({'login': values['email'], 'partner_id': res.id, 'groups_id': [(6,0,[self.env.ref('base.group_portal').id])]})
            self.env['res.users'].create(values)
        return res

    @api.multi
    def write(self, values):
        res = super(res_partner, self).write(values)
        if 'user_created' in self._context:
            return res
        user = self.env['res.users'].search([('partner_id','=',self.id)], limit=1)
        if 'is_company' in values and values['is_company'] == True:
            if user.id == False:
                vals = {'login': self.email, 'name': self.name, 'email': self.email, 'partner_id': self.id, 'groups_id': [(6,0,[self.env.ref('base.group_portal').id])]}
                self.env['res.users'].create(vals)
            else:
                if user.oauth_provider_id.id == False and user.oauth_uid == False:
                   user.create_impressbox_user(user.read()[0])
        return res


class partner_billing_period(models.Model):
    _name = "partner.billing.period"
    _description = "Successful Partner Billing Periods"
    _order = "period_id asc"

    period_id = fields.Many2one('account.period', string='Period')
    partner_id = fields.Many2one('res.partner', string='Partner')
    invoice_id = fields.Many2one('account.invoice', string='Invoice')


class res_users(models.Model):
    _name = "res.users"
    _inherit = "res.users"

    @api.model
    def check_is_employee(self, values):
        # Returns True if created user is an Employee, Officer or HR Manager
        res = True
        group_ids = []

        employee_group_id = self.env.ref('base.group_user')
        officer_group_id = self.env.ref('base.group_hr_user')
        manager_group_id = self.env.ref('base.group_hr_manager')
        hr_sel_groups = 'sel_groups_%s_%s_%s' % (employee_group_id.id, officer_group_id.id, manager_group_id.id,)

        if 'groups_id' in values:
            groups_id = values['groups_id']
            for group in groups_id:
                if groups_id[0][0] == 6:
                    group_ids += groups_id[0][2]
            if employee_group_id.id not in group_ids:
                 res = False
        elif hr_sel_groups in values and values[hr_sel_groups] == False:
            res = False
        return res

    @api.model
    def create(self, values):
        # If created user is not an employee,
        # related partner will be set as company (is_company == True)
        icp = self.env['ir.config_parameter']

        if 'secret' not in values or ('secret' in values and (values['secret'] == False or values['secret'] == '')):
            values.update({'secret': safe_eval(icp.get_param('impressbox_odoo.impressbox_secret', 'False'))}) 

        if 'secret' in values and values['secret'] != False and values['secret'] != '':
            impressbox_host_id = self.env['main.impressboxhost'].search([('secret','=',values['secret'])], limit = 1)
            if len(impressbox_host_id.ids) != 0:
                values.update({'impressbox_host_id': impressbox_host_id.id})
            else:
                raise Warning(_("""Your 'Secret Code' is not valid!\nSet valid 'Secret Code' or leave this field empty!"""))

        is_employee = self.check_is_employee(values)
        if is_employee == False:
            if 'password' not in values:
                values.update({'password': 'odoo'})
            values.update({'is_company': True, 'in_group_1': True})
            res = super(res_users, self.with_context(user_created=True)).create(values)
            if 'oauth_provider_id' not in values or ('oauth_provider_id' in values and values['oauth_provider_id'] == False):
                res.oauth_provider_id = self.get_impressbox_oauth_provider().id
                res.oauth_uid = self.create_impressbox_user(values)
        else:
            res = super(res_users, self.with_context(user_created=True)).create(values)
        return res

    @api.model
    def get_impressbox_oauth_provider(self):
        # Returns ImpressBox OAuth provider 
        provider_id = False
        domain =['|',('name','like','ImpressBox'),
                     ('name','like','Impress Box')] 
        provider_id = self.env['auth.oauth.provider'].search(domain, limit=1)
        return provider_id

    @api.multi
    def create_impressbox_user(self, values):
        # Creates a user in ImpressBox system
        # Required values: username, email, rabbitmqhost, password
        # ImpressBox system returns id of newly created user
        ibox_user_id = False
        url = 'http://aruodai7.lan:8001/main/create_user/'
        if 'impressbox_host_id' not in values:
            raise Warning(_('Please check ImpressBox details (Secret, ImpressBox Host, etc.)'))
        if 'email' not in values:
            raise Warning(_('Please define email for partner: %s' % values['name']))
        params = {
            'username': values['email'],
            'first_name': values['name'],
            #'last_name': 'Test',
            'email': values['email'],
            'impressboxhost': values['impressbox_host_id'],
            'password': 'odoo'
        }
        r = requests.post(url, params)
        r_dict = ast.literal_eval(r.content)
        if 'user_id' not in r_dict:
            if request.debug == True:
                raise Warning(('%s' % r.text))
            else:
                raise Warning(_('Sign Up failed.\nCheck Your data and try again.\n(If everything seems to be valid and Sign Up still fails, contact Your System Administrator.)'))
        user_id = r_dict['user_id']

        return user_id


import openerp.addons.web.controllers.main as main


class AuthSignupHome(main.Home):
    _cp_path = "/web/signup"

    def _signup_with_values(self, token, values):
        qcontext = self.get_auth_signup_qcontext()
        if 'secret' in qcontext:
            values.update({'secret': qcontext['secret']})
        super(AuthSignupHome, self)._signup_with_values(token, values)


class base_config_settings(models.TransientModel):
    _inherit = "base.config.settings"
    _name = "base.config.settings"

    impressbox_secret = fields.Char(string='ImpressBox Secret Code',
        help="""Set ImpressBox Secret Code, it will be used as default Secret Code for new ImpressBox users without Secret Code""")

    @api.model
    def get_default_impressbox_secret(self, fields):
        icp = self.env['ir.config_parameter']
        return {
            'impressbox_secret': safe_eval(icp.get_param('impressbox_odoo.impressbox_secret', 'False')),
        }

    @api.multi
    def set_impressbox_secret(self):
        icp = self.env['ir.config_parameter']
        icp.set_param('impressbox_odoo.impressbox_secret', repr(self.impressbox_secret))


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
