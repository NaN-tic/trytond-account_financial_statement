# This file is part of the account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains the full
# copyright notices and license terms.
import datetime
from decimal import Decimal
import unittest
from trytond.pool import Pool
import trytond.tests.test_tryton
from trytond.tests.test_tryton import ModuleTestCase, with_transaction

from trytond.modules.company.tests import create_company, set_company
from trytond.modules.account.tests import create_chart, get_fiscalyear


class AccountFinancialStatementTestCase(ModuleTestCase):
    'Test Account Financial Statement module'
    module = 'account_financial_statement'

    def create_moves(self, fiscalyear=None):
        pool = Pool()
        Party = pool.get('party.party')
        PartyAddress = pool.get('party.address')
        FiscalYear = pool.get('account.fiscalyear')
        Journal = pool.get('account.journal')
        Account = pool.get('account.account')
        Move = pool.get('account.move')
        if fiscalyear:
            company = fiscalyear.company
        else:
            company = create_company()
        with set_company(company):
            if not fiscalyear:
                fiscalyear = get_fiscalyear(company)
                fiscalyear.save()
                FiscalYear.create_period([fiscalyear])
                period = fiscalyear.periods[0]
            roots = Account.search([('parent', '=', None)])
            if not roots:
                create_chart(company)
            period = fiscalyear.periods[0]
            last_period = fiscalyear.periods[-1]
            journal_revenue, = Journal.search([
                    ('code', '=', 'REV'),
                    ])
            journal_expense, = Journal.search([
                    ('code', '=', 'EXP'),
                    ])
            revenue, = Account.search([
                    ('type.revenue', '=', True),
                    ])
            Account.write([revenue], {'code': '7'})
            receivable, = Account.search([
                    ('type.receivable', '=', True),
                    ])
            Account.write([receivable], {'code': '43'})
            expense, = Account.search([
                    ('type.expense', '=', True),
                    ])
            Account.write([expense], {'code': '6'})
            payable, = Account.search([
                    ('type.payable', '=', True),
                    ])
            Account.write([payable], {'code': '41'})
            chart, = Account.search([
                    ('parent', '=', None),
                    ], limit=1)
            Account.create([{
                        'name': 'View',
                        'code': '1',
                        'parent': chart.id,
                        }])
            # Create some parties
            if Party.search([('name', '=', 'customer1')]):
                customer1, = Party.search([('name', '=', 'customer1')])
                customer2, = Party.search([('name', '=', 'customer2')])
                supplier1, = Party.search([('name', '=', 'supplier1')])
                supplier2, = Party.search([('name', '=', 'supplier2')])
            else:
                customer1, customer2, supplier1, supplier2 = Party.create([{
                                'name': 'customer1',
                            }, {
                                'name': 'customer2',
                            }, {
                                'name': 'supplier1',
                            }, {
                                'name': 'supplier2',
                            }])
                PartyAddress.create([{
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
                                    'party': supplier2.id,
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
                                    'party': customer2.id,
                                    'account': receivable.id,
                                    'debit': Decimal(300),
                                    }]),
                        ],
                    },
                ]
            moves = Move.create(vlist)
            Move.post(moves)
            return company, fiscalyear

    @with_transaction()
    def test0010_report(self):
        pool = Pool()
        Template = pool.get('account.financial.statement.template')
        TemplateLine = pool.get('account.financial.statement.template.line')
        Report = pool.get('account.financial.statement.report')

        company, fiscalyear = self.create_moves()
        template, = Template.create([{
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
                                    'current_value': 'concept(0,1)',
                                    'previous_value': 'concept(0,1)',
                                    }]
                            )],
                    }])
        results = template.lines[0]
        # This must be created manually otherwise template is not set.
        TemplateLine.create([{
                        'code': '01',
                        'name': 'Expense',
                        'current_value': 'balance(6)',
                        'previous_value': 'balance(6)',
                        'parent': results.id,
                        'template': template.id,
                        }, {
                        'code': '02',
                        'name': 'Revenue',
                        'current_value': 'balance(7)',
                        'previous_value': 'balance(7)',
                        'parent': results.id,
                        'template': template.id,
                        }])
        period = fiscalyear.periods[0]

        with set_company(company):
            report = Report()
            report.name = 'Test Report'
            report.template = template.id
            report.current_fiscalyear = fiscalyear
            report.current_periods= [x.id for x in fiscalyear.periods]
            report.save()
            self.assertEqual(report.state, 'draft')
            Report.calculate([report])
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
            Report.draft([report])
            template.mode = 'debit-credit'
            template.save()
            Report.calculate([report])
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
            Report.draft([report])
            report.previous_fiscalyear = fiscalyear
            report.previous_periods = [x.id for x in fiscalyear.periods]
            report.save()
            Report.calculate([report])
            for line in report.lines:
                self.assertEqual(results[line.code], line.current_value)
                if line.code == '1':
                    self.assertEqual(Decimal('10.0'), line.previous_value)
                elif line.code == '2':
                    self.assertEqual(Decimal('480.0'), line.previous_value)
                else:
                    self.assertEqual(results[line.code], line.previous_value)
            Report.draft([report])
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

    @with_transaction()
    def test0020_fiscalyear_not_closed(self):
        pool = Pool()
        FiscalYear = pool.get('account.fiscalyear')
        Template = pool.get('account.financial.statement.template')
        TemplateLine = pool.get('account.financial.statement.template.line')
        Report = pool.get('account.financial.statement.report')
        company = create_company()
        with set_company(company):
            fiscalyear = get_fiscalyear(company)
            fiscalyear.save()
            FiscalYear.create_period([fiscalyear])
            next_fiscalyear = get_fiscalyear(company,
                today=fiscalyear.end_date + datetime.timedelta(1))
            next_fiscalyear.save()
            FiscalYear.create_period([next_fiscalyear])
            self.create_moves(fiscalyear)
            self.create_moves(next_fiscalyear)
        template_balance, template_income = Template.create([{
                    'name': 'Template Balance Report',
                    'mode': 'credit-debit',
                    'cumulate': True,
                    'lines': [('create', [{
                                    'code': '0',
                                    'name': 'Results',
                                    }]
                            )],
                    }, {
                    'name': 'Template Income Report',
                    'mode': 'credit-debit',
                    'cumulate': False,
                    'lines': [('create', [{
                                    'code': '0',
                                    'name': 'Results',
                                    }]
                            )],
                    }])

        results_line = template_balance.lines[0]
        # This must be created manually otherwise template is not set.
        TemplateLine.create([{
                        'code': '01',
                        'name': 'Expense',
                        'current_value': 'balance(6)',
                        'previous_value': 'balance(6)',
                        'parent': results_line.id,
                        'template': template_balance.id,
                        }, {
                        'code': '02',
                        'name': 'Revenue',
                        'current_value': 'balance(7)',
                        'previous_value': 'balance(7)',
                        'parent': results_line.id,
                        'template': template_balance.id,
                        }, {
                        'code': '03',
                        'name': 'Payable',
                        'current_value': 'balance(41)',
                        'previous_value': 'balance(41)',
                        'parent': results_line.id,
                        'template': template_balance.id,
                        }, {
                        'code': '04',
                        'name': 'Receivable',
                        'current_value': 'balance(43)',
                        'previous_value': 'balance(43)',
                        'parent': results_line.id,
                        'template': template_balance.id,
                        }])

        results_line = template_income.lines[0]
        # This must be created manually otherwise template is not set.
        TemplateLine.create([{
                        'code': '01',
                        'name': 'Expense',
                        'current_value': 'balance(6)',
                        'previous_value': 'balance(6)',
                        'parent': results_line.id,
                        'template': template_income.id,
                        }, {
                        'code': '02',
                        'name': 'Revenue',
                        'current_value': 'balance(7)',
                        'previous_value': 'balance(7)',
                        'parent': results_line.id,
                        'template': template_income.id,
                        }])

        with set_company(company):
            report_balance = Report()
            report_balance.name = 'Test Report'
            report_balance.template = template_balance.id
            report_balance.current_fiscalyear = next_fiscalyear
            report_balance.previous_fiscalyear = fiscalyear
            report_balance.current_periods= [x.id for x in next_fiscalyear.periods]
            report_balance.previous_periods= [x.id for x in fiscalyear.periods]
            report_balance.save()

            self.assertEqual(report_balance.state, 'draft')
            Report.calculate([report_balance])
            self.assertEqual(report_balance.state, 'calculated')
            self.assertEqual(len(report_balance.lines), 5)

            results_balance = {
                '0': (Decimal('0.0'), Decimal('0.0')),
                '01': (Decimal('-260.0'), Decimal('-130.0')),
                '02': (Decimal('1200.0'), Decimal('600.0')),
                '03': (Decimal('260.0'), Decimal('130.0')),
                '04': (Decimal('-1200.0'), Decimal('-600.0')),
                }
            for line in report_balance.lines:
                current, previous = results_balance[line.code]
                self.assertEqual(current, line.current_value)
                self.assertEqual(previous, line.previous_value)

            report_income=Report()
            report_income.name='Test report'
            report_income.template=template_income.id
            report_income.current_fiscalyear=next_fiscalyear
            report_income.previous_fiscalyear=fiscalyear
            report_income.current_periods = [x.id for x in next_fiscalyear.periods]
            report_income.previous_periods = [x.id for x in fiscalyear.periods]
            report_income.save()
            self.assertEqual(report_income.state, 'draft')
            Report.calculate([report_income])
            self.assertEqual(report_income.state, 'calculated')
            self.assertEqual(len(report_income.lines), 3)

            results_income = {
                '0': (Decimal('470.0'), Decimal('470.0')),
                '01': (Decimal('-130.0'), Decimal('-130.0')),
                '02': (Decimal('600.0'), Decimal('600.0')),
                }
            for line in report_income.lines:
                current, previous = results_income[line.code]
                self.assertEqual(current, line.current_value)
                self.assertEqual(previous, line.previous_value)


def suite():
    suite = trytond.tests.test_tryton.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        AccountFinancialStatementTestCase))
    return suite
