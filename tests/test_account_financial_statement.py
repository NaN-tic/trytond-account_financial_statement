#!/usr/bin/env python
#This file is part account_financial_statement module for Tryton.
#The COPYRIGHT file at the top level of this repository contains
#the full copyright notices and license terms.
import sys
import os
DIR = os.path.abspath(os.path.normpath(os.path.join(__file__,
    '..', '..', '..', '..', '..', 'trytond')))
if os.path.isdir(DIR):
    sys.path.insert(0, os.path.dirname(DIR))

import unittest
import trytond.tests.test_tryton
from decimal import Decimal
from trytond.tests.test_tryton import test_view, test_depends
from trytond.tests.test_tryton import POOL, DB_NAME, USER, CONTEXT
from trytond.transaction import Transaction


class AccountFinancialStatementTestCase(unittest.TestCase):
    '''
    Test Account Financial Statement module.
    '''

    def setUp(self):
        trytond.tests.test_tryton.install_module('account_financial_statement')
        self.account = POOL.get('account.account')
        self.company = POOL.get('company.company')
        self.user = POOL.get('res.user')
        self.party = POOL.get('party.party')
        self.party_address = POOL.get('party.address')
        self.fiscalyear = POOL.get('account.fiscalyear')
        self.move = POOL.get('account.move')
        self.line = POOL.get('account.move.line')
        self.journal = POOL.get('account.journal')
        self.period = POOL.get('account.period')
        self.taxcode = POOL.get('account.tax.code')
        self.template = POOL.get('account.financial.statement.template')
        self.template_line = POOL.get(
            'account.financial.statement.template.line')
        self.report = POOL.get('account.financial.statement.report')
        self.report_line = POOL.get('account.financial.statement.report.line')

    def test0005views(self):
        '''
        Test views.
        '''
        test_view('account_financial_statement')

    def test0006depends(self):
        '''
        Test depends.
        '''
        test_depends()

    def create_moves(self):
        fiscalyear, = self.fiscalyear.search([])
        period = fiscalyear.periods[0]
        last_period = fiscalyear.periods[-1]
        journal_revenue, = self.journal.search([
                ('code', '=', 'REV'),
                ])
        journal_expense, = self.journal.search([
                ('code', '=', 'EXP'),
                ])
        revenue, = self.account.search([
                ('kind', '=', 'revenue'),
                ])
        self.account.write([revenue], {'code': '7'})
        receivable, = self.account.search([
                ('kind', '=', 'receivable'),
                ])
        self.account.write([receivable], {'code': '43'})
        expense, = self.account.search([
                ('kind', '=', 'expense'),
                ])
        self.account.write([expense], {'code': '6'})
        payable, = self.account.search([
                ('kind', '=', 'payable'),
                ])
        self.account.write([payable], {'code': '41'})
        chart, = self.account.search([
                ('parent', '=', None),
                ], limit=1)
        self.account.create([{
                    'name': 'View',
                    'code': '1',
                    'kind': 'view',
                    'parent': chart.id,
                    }])
        #Create some parties
        customer1, customer2, supplier1, supplier2 = self.party.create([{
                        'name': 'customer1',
                    }, {
                        'name': 'customer2',
                    }, {
                        'name': 'supplier1',
                    }, {
                        'name': 'supplier2',
                    }])
        self.party_address.create([{
                        'active': True,
                        'party': customer1.id,
                    }, {
                        'active': True,
                        'party': supplier1.id,
                    }])
        # Create some moves
        vlist = [
            {
                'period': period.id,
                'journal': journal_revenue.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(100),
                                }, {
                                'party': customer1.id,
                                'account': receivable.id,
                                'debit': Decimal(100),
                                }]),
                    ],
                },
            {
                'period': period.id,
                'journal': journal_revenue.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(200),
                                }, {
                                'party': customer2.id,
                                'account': receivable.id,
                                'debit': Decimal(200),
                                }]),
                    ],
                },
            {
                'period': period.id,
                'journal': journal_expense.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(30),
                                }, {
                                'party': supplier1.id,
                                'account': payable.id,
                                'credit': Decimal(30),
                                }]),
                    ],
                },
            {
                'period': period.id,
                'journal': journal_expense.id,
                'date': period.start_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(50),
                                }, {
                                'party': supplier2.id,
                                'account': payable.id,
                                'credit': Decimal(50),
                                }]),
                    ],
                },
            {
                'period': last_period.id,
                'journal': journal_expense.id,
                'date': last_period.end_date,
                'lines': [
                    ('create', [{
                                'account': expense.id,
                                'debit': Decimal(50),
                                }, {
                                'account': payable.id,
                                'credit': Decimal(50),
                                }]),
                    ],
                },
            {
                'period': last_period.id,
                'journal': journal_revenue.id,
                'date': last_period.end_date,
                'lines': [
                    ('create', [{
                                'account': revenue.id,
                                'credit': Decimal(300),
                                }, {
                                'account': receivable.id,
                                'debit': Decimal(300),
                                }]),
                    ],
                },
            ]
        moves = self.move.create(vlist)
        self.move.post(moves)

    def test0010_report(self):
        with Transaction().start(DB_NAME, USER, context=CONTEXT):
            self.create_moves()
            template, = self.template.create([{
                        'name': 'Template',
                        'mode': 'credit-debit',
                        'lines': [('create', [{
                                        'code': '0',
                                        'name': 'Results',
                                        }, {
                                        'code': '1',
                                        'name': 'Fixed',
                                        'current_value': '12.00',
                                        'previous_value': '10.00',
                                        }, {
                                        'code': '2',
                                        'name': 'Sum',
                                        'current_value': '0+1',
                                        'previous_value': '0+1',
                                        }]
                                )],
                        }])
            results = template.lines[0]
            #This must be created manually otherwise template is not set.
            self.template_line.create([{
                            'code': '01',
                            'name': 'Expense',
                            'current_value': '6',
                            'previous_value': '6',
                            'parent': results.id,
                            'template': template.id,
                            }, {
                            'code': '02',
                            'name': 'Revenue',
                            'current_value': '7',
                            'previous_value': '7',
                            'parent': results.id,
                            'template': template.id,
                            }])
            fiscalyear, = self.fiscalyear.search([])
            period = fiscalyear.periods[0]

            report, = self.report.create([{
                        'name': 'Test report',
                        'template': template.id,
                        'current_fiscalyear': fiscalyear,
                        }])
            self.assertEqual(report.state, 'draft')
            self.report.calculate([report])
            self.assertEqual(report.state, 'calculated')
            self.assertEqual(len(report.lines), 5)

            results = {
                '0': Decimal('470.0'),
                '1': Decimal('12.0'),
                '2': Decimal('482.0'),
                '01': Decimal('-130.0'),
                '02': Decimal('600.0'),
                }
            for line in report.lines:
                self.assertEqual(results[line.code], line.current_value)
                self.assertEqual(Decimal('0.0'), line.previous_value)
            self.report.draft([report])
            template.mode = 'debit-credit'
            template.save()
            self.report.calculate([report])
            for line in report.lines:
                if line.code == '1':
                    self.assertEqual(results[line.code], line.current_value)
                elif line.code == '2':
                    self.assertEqual(Decimal('-458.0'), line.current_value)
                else:
                    self.assertEqual(results[line.code].copy_negate(),
                        line.current_value)
            template.mode = 'credit-debit'
            template.save()
            self.report.draft([report])
            report.previous_fiscalyear = fiscalyear
            report.save()
            self.report.calculate([report])
            for line in report.lines:
                self.assertEqual(results[line.code], line.current_value)
                if line.code == '1':
                    self.assertEqual(Decimal('10.0'), line.previous_value)
                elif line.code == '2':
                    self.assertEqual(Decimal('480.0'), line.previous_value)
                else:
                    self.assertEqual(results[line.code], line.previous_value)
            self.report.draft([report])
            report.current_periods = [period]
            report.previous_periods = [period]
            report.save()
            results = {
                '0': (Decimal('220.0'), Decimal('250.0')),
                '1': (Decimal('12.0'), Decimal('10.0')),
                '2': (Decimal('232.0'), Decimal('260.0')),
                '01': (Decimal('-800.0'), Decimal('-50.0')),
                '02': (Decimal('300.0'), Decimal('300.0')),
                }
            for line in report.lines:
                current, previous = results[line.code]
                self.assertEqual(current, line.current_value)
                self.assertEqual(previous, line.previous_value)


def suite():
    suite = trytond.tests.test_tryton.suite()
    from trytond.modules.account.tests import test_account
    for test in test_account.suite():
        #Skip doctest
        class_name = test.__class__.__name__
        if test not in suite and class_name != 'DocFileCase':
            suite.addTest(test)
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountFinancialStatementTestCase))
    return suite

if __name__ == '__main__':
    unittest.TextTestRunner(verbosity=2).run(suite())
