# -*- coding: utf-8 -*-

from datetime import date, timedelta
from openerp import models, fields, api, _
from openerp.exceptions import except_orm


class impressbox_billing(models.TransientModel):
    _name = "impressbox.billing"
    _description = "ImpressBox Billing"

    @api.model
    def _get_last_period_id(self):
        fday_this_month = date.today().replace(day=1)
        lday_previous_month = fday_this_month - timedelta(days=1)
        period_ids = self.env['account.period'].find(lday_previous_month)[:1].ids
        return period_ids[0]

    period_id = fields.Many2one('account.period', string='Period', required=True, default=_get_last_period_id)

    @api.multi
    def onchange_period(self, period_id):
        period_obj = self.env['account.period']
        last_period = period_obj.browse(self._get_last_period_id())
        period = period_obj.browse(period_id)
        if period.date_start > last_period.date_stop:
            raise except_orm(
                _('Billing period is not correctly set!'),
                _('Period cannot be equal or greater than current period.')
            )
        return {}

    @api.multi
    def create_billing(self):
        invoice_ids = []
        existing_billing_periods = self.env['partner.billing.period'].search([('period_id','in',self.period_id.ids)])
        partner_domain = ['|',('billing_periods','not in',existing_billing_periods.ids),
                              ('billing_periods','=',False)]
        partner_ids = self.env['res.partner'].search(partner_domain)
        for partner in partner_ids:
            invoice = partner.execute_billing(self.period_id)
            if invoice != False:
                invoice_ids += invoice
        return self.open_invoice(invoice_ids)

    @api.model
    def open_invoice(self, invoice_ids):
        action_data = {}
        action_obj = self.env['ir.actions.act_window']
        model = 'account.invoice'
        action = action_obj.search_read([('res_model', '=', model)], limit=1)
        data_obj = self.env['ir.model.data']
        form_view = data_obj.get_object_reference('account', 'invoice_form')
        tree_view = data_obj.get_object_reference('account', 'invoice_tree')
        if action:
            action_data = action[0]
            action_data.update({
                        'domain': "[('id','in',%s)]" % invoice_ids,
                        'nodestroy': True,
                        'view_mode': 'tree,form',
                        'target': 'current',
                        'name': _('Invoices (ImpressBox Billing)'),
                        'view_type': 'form',
                        'res_model': 'account.invoice',
                        'view_id': False,
                        'views': [(tree_view and tree_view[1] or False, 'tree'),(form_view and form_view[1] or False, 'form')],
                        'type': 'ir.actions.act_window'
                })

        return action_data

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:

