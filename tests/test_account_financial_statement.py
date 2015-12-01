# This file is part of the account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import unittest
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase


class AccountFinancialStatementTestCase(ModuleTestCase):
    'Test Account Financial Statement module'
    module = 'account_financial_statement'


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountFinancialStatementTestCase))
    return suite