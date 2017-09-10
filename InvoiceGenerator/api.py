# -*- coding: utf-8 -*-

import decimal
from decimal import Decimal

from InvoiceGenerator.conf import _

import qrcode

__all__ = ['Client', 'Provider', 'Creator', 'Item', 'Invoice']


class UnicodeProperty(object):
    _attrs = ()

    def __setattr__(self, key, value):
        if key in self._attrs:
            value = value
        self.__dict__[key] = value


class Address(UnicodeProperty):
    _attrs = ('summary', 'address', 'city', 'zip', 'phone', 'email',
              'bank_name', 'bank_account', 'bank_code', 'note', 'vat_id', 'ir',
              'logo_filename')

    def __init__(self, summary, address='', city='', zip='', phone='', email='',
               bank_name='', bank_account='', bank_code='', note='', vat_id='', ir='',
               logo_filename='', vat_note=''):
        self.summary = summary
        self.address = address
        self.city = city
        self.zip = zip
        self.phone = phone
        self.email = email
        self.bank_name = bank_name
        self.bank_account = bank_account
        self.bank_code = bank_code
        self.note = note
        self.vat_id = vat_id
        self.vat_note = vat_note
        self.ir = ir
        self.logo_filename = logo_filename

    def bank_account_str(self):
        if self.bank_code:
            return "%s/%s" % (self.bank_account, self.bank_code)
        else:
            return self.bank_account

    def get_address_lines(self):
        address_line = [
            self.summary,
            self.address,
            u'%s %s' % (self.zip, self.city)
            ]
        if self.vat_id:
            address_line.append(_(u'Vat in: %s') % self.vat_id)

        if self.ir:
            address_line.append(_(u'IR: %s') % self.ir)

        return address_line

    def get_contact_lines(self):
        return [
            self.phone,
            self.email,
            ]


class Client(Address):
    pass


class Provider(Address):
    pass


class Creator(UnicodeProperty):
    _attrs = ('name', 'stamp_filename')

    def __init__(self, name, stamp_filename=''):
        self.name = name
        self.stamp_filename = stamp_filename


class Item(object):

    def __init__(self, count, price, description='', unit='', tax=Decimal(0)):
        self.count = count
        self.price = price
        self._description = description
        self.unit = unit
        self.tax = tax

    @property
    def total(self):
        return self.price * self.count

    @property
    def total_tax(self):
        return self.price * self.count * (Decimal(1) + self.tax / Decimal(100))

    def count_tax(self):
        return self.total_tax - self.total

    @property
    def description(self):
        return self._description

    @description.setter
    def description(self, value):
        self._description = value

    @property
    def count(self):
        return self._count

    @count.setter
    def count(self, value):
        self._count = Decimal(value)

    @property
    def price(self):
        return self._price

    @price.setter
    def price(self, value):
        self._price = Decimal(value)

    @property
    def unit(self):
        return self._unit

    @unit.setter
    def unit(self, value):
        self._unit = value

    @property
    def tax(self):
        return self._tax

    @tax.setter
    def tax(self, value):
        if value is None:
            self._tax = Decimal(0)
        else:
            self._tax = Decimal(value)


class Invoice(UnicodeProperty):
    # Please dont use this style of attributs, it much more
    # complicated to develop something - IDE can't help with this
    _attrs = ('title', 'variable_symbol', 'specific_symbol', 'paytype',
              'number', 'iban', 'swift', )
    use_tax = False

    rounding_result = False

    rounding_strategy = decimal.ROUND_HALF_EVEN

    def __init__(self, client, provider, creator):
        assert isinstance(client, Client)
        assert isinstance(provider, Provider)
        assert isinstance(creator, Creator)

        self.client = client
        self.provider = provider
        self.creator = creator
        self._items = []
        self.date = None
        self.payback = None
        self.taxable_date = None
        self.currency_locale = "cs_CZ.UTF-8"
        self.currency = u"Kč"

        for attr in self._attrs:
            self.__setattr__(attr, '')

    def _price_tax_unrounded(self):
        return sum(item.total_tax for item in self.items)

    @property
    def price(self):
        return self._round_result(sum(item.total for item in self.items))

    @property
    def price_tax(self):
        return self._round_result(self._price_tax_unrounded())

    def add_item(self, item):
        assert isinstance(item, Item)
        self._items.append(item)

    @property
    def items(self):
        return self._items

    def _round_price(self, price):
        return decimal.Decimal(price).quantize(0, rounding=self.rounding_strategy)

    @property
    def difference_in_rounding(self):
        price = self._price_tax_unrounded()
        return Decimal(self._round_price(price)) - price

    def _get_grouped_items_by_tax(self):
        table = {}
        for item in self.items:
            if item.tax not in table:
                table[item.tax] = {'total': item.total, 'total_tax': item.total_tax, 'tax': item.count_tax()}
            else:
                table[item.tax]['total'] += item.total
                table[item.tax]['total_tax'] += item.total_tax
                table[item.tax]['tax'] += item.count_tax()

        return table

    def _round_result(self, price):
        if self.rounding_result:
            return self._round_price(price)
        return price

    def generate_breakdown_vat(self):
        return self._get_grouped_items_by_tax()

    def generate_breakdown_vat_table(self):
        rows = []
        for vat, items in self.generate_breakdown_vat().items():
            rows.append((vat, items['total'], items['total_tax'], items['tax']))

        return rows


class Correction(Invoice):
    _attrs = ('number', 'reason', 'title', 'variable_symbol', 'specific_symbol', 'paytype',
              'date', 'payback', 'taxable_date')

    def __init__(self, client, provider, creator):
        super(Correction, self).__init__(client, provider, creator)


class QrCodeBuilder(object):

    def __init__(self, invoice):
        """
        :param invoice: Invoice
        """
        self.invoice = invoice
        self.qr = self._fill(invoice)
        self.tmp_file = None

    def _fill(self, invoice):
        from qrplatba import QRPlatbaGenerator

        qr_kwargs = {
            'account': invoice.provider.bank_account,
            'amount': invoice.price_tax,
            'x_ss': invoice.specific_symbol,
        }

        if invoice.variable_symbol:
            qr_kwargs['x_vs'] = invoice.variable_symbol

        try:
            qr_kwargs['due_date'] = invoice.payback.strftime("%Y%m%d")
        except AttributeError:
            pass

        qr_kwargs = {k: v for k, v in qr_kwargs.items() if v}

        return QRPlatbaGenerator(**qr_kwargs)

    @property
    def filename(self):
        from tempfile import NamedTemporaryFile
        img = qrcode.make(self.qr.get_text())

        self.tmp_file = NamedTemporaryFile(mode='w+b', suffix='.png',
                                           delete=False)
        img.save(self.tmp_file)
        self.tmp_file.close()
        return self.tmp_file.name

    def destroy(self):
        if hasattr(self.tmp_file, 'name'):
            import os
            os.unlink(self.tmp_file.name)
