import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from io import BytesIO

from openpyxl import load_workbook
from pypdf import PdfReader
from proteus import Model, Wizard
from trytond import backend
from trytond.modules.account.tests.tools import (
    create_chart, create_fiscalyear, get_accounts)
from trytond.modules.company.tests.tools import create_company, get_company
from trytond.pool import Pool
from trytond.tests.test_tryton import drop_db
from trytond.tests.tools import activate_modules
from trytond.transaction import Transaction


class TestFinancialStatementAccountSelection(unittest.TestCase):

    def setUp(self):
        drop_db()
        super().setUp()

    def tearDown(self):
        drop_db()
        super().tearDown()

    def test(self):
        config = activate_modules(['account_financial_statement', 'account_code_digits'])
        create_company(config=config)
        company = get_company(config=config)
        create_chart(company=company, config=config)
        Configuration = Model.get('account.configuration', config=config)
        configuration = Configuration(1)
        configuration.force_digits = False
        configuration.default_account_code_digits = 3
        configuration.save()
        accounts = get_accounts(company=company, config=config)
        revenue = accounts['revenue']
        revenue.code = '900'
        revenue.save()
        Account = Model.get('account.account', config=config)
        child = Account(parent=revenue, name='Different prefix', code='OTHER')
        child.end_date = date(2022, 12, 31)
        child.save()
        overlapping = Account(parent=revenue, name='Overlapping', code='901')
        overlapping.save()

        fiscalyears = []
        for year in (2022, 2023):
            fiscalyear = create_fiscalyear(company=company,
                today=(date(year, 1, 1), date(year, 12, 31)), config=config)
            fiscalyear.save()
            fiscalyear.click('create_period')
            fiscalyears.append(fiscalyear)

        Party = Model.get('party.party', config=config)
        party = Party(name='Customer')
        party.save()
        Journal = Model.get('account.journal', config=config)
        Move = Model.get('account.move', config=config)
        move = Move()
        move.journal, = Journal.find([('code', '=', 'REV')], limit=1)
        move.period = fiscalyears[0].periods[0]
        move.date = move.period.start_date
        for account, amount in [(revenue, 10), (child, 30), (overlapping, 20)]:
            line = move.lines.new()
            line.account = account
            line.credit = Decimal(amount)
        line = move.lines.new()
        line.account = accounts['receivable']
        line.party = party
        line.debit = Decimal(60)
        move.save()
        move.click('post')

        Template = Model.get('account.financial.statement.template', config=config)
        template = Template(name='Account selection', mode='credit-debit')
        line = template.lines.new()
        line.name = 'Revenue'
        line.code = 'R'
        line.current_value = 'balance(9)'
        template.save()
        Report = Model.get('account.financial.statement.report', config=config)
        report = Report(name='Selection', template=template)
        for fiscalyear in fiscalyears:
            period = report.comparison_periods.new()
            period.fiscalyear = fiscalyear
        report.save()
        report.click('calculate')

        wizard = Wizard('account.financial.statement.print', [report])
        self.assertTrue(wizard.form.has_account_code_digits)
        self.assertEqual(wizard.form.digits, 3)
        wizard.form.include_details = True
        wizard.form.output_format = 'xlsx'
        wizard.form.digits = 2
        wizard.execute('print_')
        extension, content, _, _ = wizard.actions[0]
        self.assertEqual(extension, 'xlsx')
        sheet = load_workbook(BytesIO(content)).active
        grouped, = [row for row in sheet.iter_rows(values_only=True)
            if row[0] and row[0].startswith('90 - ')]
        self.assertEqual(grouped[1:], (-30, 0))
        wizard = Wizard('account.financial.statement.print', [report])
        wizard.form.include_details = True
        wizard.form.digits = 2
        wizard.execute('print_')
        self.assertEqual(wizard.actions[0][0], 'pdf')
        reader = PdfReader(BytesIO(wizard.actions[0][1]))
        text = '\n'.join(page.extract_text() for page in reader.pages)
        self.assertIn('90 - ', text)
        self.assertIn('-30.00', text)
        self.assertNotIn('900 - ', text)

        receivable_code = accounts['receivable'].code
        pool = Pool(config.database_name)
        AccountModel = pool.get('account.account')
        ReportModel = pool.get('account.financial.statement.report')
        with Transaction().start(config.database_name, config.user,
                context=config.context):
            record = ReportModel(report.id)
            for period in record.comparison_periods:
                line, = period.lines
                expected = (Decimal(60)
                    if period.fiscalyear.id == fiscalyears[0].id else 0)
                self.assertEqual(line.value, expected)
                with Transaction().set_context(
                        fiscalyear=period.fiscalyear.id,
                        periods=[p.id for p in period.get_periods()], cumulate=False):
                    cache = {}
                    for code in ['9', '90', '900', '901', '9_', 'OTHER', 'missing']:
                        roots = AccountModel.search([
                                ('company', '=', company.id),
                                ('code', 'like', code + '%'),
                                ('type', '!=', None),
                                ])
                        expected_ids = set()
                        if roots:
                            expected_ids = {a.id for a in AccountModel.search([
                                    ('company', '=', company.id),
                                    ('parent', 'child_of', [a.id for a in roots]),
                                    ])}
                        self.assertEqual(set(line._get_accounts_by_code(code, cache)),
                            expected_ids)
                    self.assertEqual(child.id in line._get_accounts_by_code('9', cache),
                        period.fiscalyear.id == fiscalyears[0].id)
                    # The aggregation also works with generic prepared plans.
                    if backend.name == 'postgresql':
                        cursor = Transaction().connection.cursor()
                        cursor.execute(
                            "SET LOCAL plan_cache_mode = force_generic_plan")
                    # A direct helper call must work even outside the template.
                    cache = {}
                    self.assertEqual(line._get_account_values(
                            '901', 'balance', cache=cache)[0],
                        Decimal(20) if expected else 0)
                    self.assertEqual(line._get_account_values(
                            receivable_code, 'balance', cache=cache)[0],
                        Decimal(-60) if expected else 0)
                    if backend.name == 'postgresql':
                        cursor.execute("SHOW plan_cache_mode")
                        self.assertEqual(cursor.fetchone()[0], 'force_generic_plan')
                    # In the normal calculation the complete account selection
                    # needs just one ORM search, not one per prefix/descendant.
                    with patch.object(AccountModel, 'search',
                            wraps=AccountModel.search) as search:
                        cache = {}
                        for code in ['9', '90', '900', '901', '9_']:
                            line._get_accounts_by_code(code, cache)
                    self.assertEqual(search.call_count, 1)

        # Dynamic account arguments fall back to the full active chart;
        # cumulation must still use the accounting API's previous-year rules.
        report.click('draft')
        template.lines[0].current_value = 'balance(concept("0") // 1)'
        constant = template.lines.new()
        constant.name = 'Prefix'
        constant.code = '0'
        constant.current_value = '9'
        template.cumulate = True
        template.save()
        report.click('calculate')
        with Transaction().start(config.database_name, config.user,
                context=config.context):
            record = ReportModel(report.id)
            for period in record.comparison_periods:
                line, = [line for line in period.lines if line.code == 'R']
                expected = (Decimal(60)
                    if period.fiscalyear.id == fiscalyears[0].id else Decimal(30))
                self.assertEqual(line.value, expected)
