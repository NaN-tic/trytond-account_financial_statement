# This file is part of account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.model import ModelView, ModelSQL, Workflow, fields, Unique
from trytond.wizard import Wizard, StateView, StateAction, StateTransition, \
    Button
from trytond.transaction import Transaction
from trytond.pyson import Eval, PYSONEncoder, Bool
from trytond.pool import Pool
from trytond import backend
from trytond.modules.jasper_reports.jasper import JasperReport
from trytond.tools import decistmt
from trytond.exceptions import UserError
from trytond.i18n import gettext

import re
from datetime import datetime
from decimal import Decimal
from simpleeval import simple_eval
from functools import partial
from ast import parse

__all__ = [
    'Report', 'ReportJasper', 'ReportCurrentPeriods',
    'ReportPreviousPeriods', 'ReportLine', 'ReportLineAccount',
    'Template', 'TemplateLine', 'ReportLineDetailStart', 'ReportLineDetail',
    ]

CSS_CLASSES = [
    ('default', 'Default'),
    ('l1', 'Level 1'),
    ('l2', 'Level 2'),
    ('l3', 'Level 3'),
    ('l4', 'Level 4'),
    ('l5', 'Level 5')
    ]

_STATES = {
    'readonly': Eval('state') == 'calculated',
    }

_DEPENDS = ['state']

_VALUE_FORMULA_HELP = ('Value calculation formula: Depending on this formula '
    'the final value is calculated as follows:\n'
    '- Empy template value: sum of (this concept) children values.\n'
    '- Number with decimal point ("10.2"): that value (constant).\n'
    '- A matematic formula with following helpers:\n'
    '  * balance() with comma-separated account numbers. Sum of the accounts '
    '(the sign of the depends on the mode).\n'
    '  * invert() with comma-separated account numbers. Sum of the account '
    '(the sign is inverted if reversed modes are used).\n'
    '  * credit() with comma-separeted account numbers. Sum of the credit '
    'accounts.\n'
    '  * debit() with comma-separeted account numbers. Sum of the debit of '
    'accounts.\n'
    '  * concept() with comma-separated concept codes in quotes of the report '
    'itself (column Code). Sum of the concept values.\n'
    'Examples:\n'
    'balance(430, 431) + invert(437)\n'
    'balance(5305, 5315) + invert(5325, 5335) + debit(551, 5525)\n'
    'balance(5103) + credit(5523)\n'
    'concept("11000", "12000")\n'
    'balance(7) - 1.25 * balance(6)\n'
    'concept("101") / 2'
    )

STATES = [
    ('draft', 'Draft'),
    ('calculated', 'Calculated'),
    ]


class Report(Workflow, ModelSQL, ModelView):
    'Financial Statement Report'
    __name__ = 'account.financial.statement.report'

    name = fields.Char('Name', required=True, select=True)
    state = fields.Selection(STATES, 'State', readonly=True)
    template = fields.Many2One('account.financial.statement.template',
        'Template', ondelete='SET NULL', required=True, select=True,
        states=_STATES, depends=_DEPENDS)
    calculation_date = fields.DateTime('Calculation date', readonly=True)
    company = fields.Many2One('company.company', 'Company', ondelete='CASCADE',
        readonly=True, required=True)
    current_fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal year 1',
        select=True, required=True, states=_STATES, depends=_DEPENDS)
    current_periods = fields.Many2Many(
        'account_financial_statement-account_period_current', 'report',
        'period', 'Fiscal year 1 periods', states=_STATES, domain=[
            ('fiscalyear', '=', Eval('current_fiscalyear')),
            ], depends=_DEPENDS + ['current_fiscalyear'])
    current_periods_list = fields.Function(fields.Char('Current Periods List'),
        'get_periods')
    current_periods_start_date = fields.Function(
        fields.Char('Current Periods Dates'), 'get_dates')
    current_periods_end_date = fields.Function(
        fields.Char('Current Periods Dates'), 'get_dates')
    previous_fiscalyear = fields.Many2One('account.fiscalyear',
        'Fiscal year 2', select=True, states=_STATES, depends=_DEPENDS)
    previous_periods = fields.Many2Many(
        'account_financial_statement-account_period_previous', 'report',
        'period', 'Fiscal year 2 periods', states=_STATES, domain=[
            ('fiscalyear', '=', Eval('previous_fiscalyear')),
            ], depends=_DEPENDS + ['previous_fiscalyear'])
    previous_periods_list = fields.Function(
        fields.Char('Previous Periods List'), 'get_periods')
    previous_periods_start_date = fields.Function(
        fields.Char('Previous Periods Dates'), 'get_dates')
    previous_periods_end_date = fields.Function(
        fields.Char('Previous Periods Dates'), 'get_dates')
    lines = fields.One2Many('account.financial.statement.report.line',
        'report', 'Lines', readonly=True)

    @classmethod
    def __setup__(cls):
        super(Report, cls).__setup__()
        cls._order.insert(0, ('name', 'ASC'))
        cls._transition_state = 'state'
        cls._transitions |= set((
                ('draft', 'calculated'),
                ('calculated', 'draft'),
                ))
        cls._buttons.update({
                'calculate': {
                    'invisible': Eval('state') != 'draft',
                    },
                'draft': {
                    'invisible': Eval('state') != 'calculated',
                    },
                })

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def get_periods(cls, reports, names):
        result = {}
        for report in reports:
            if 'current_periods_list' in names:
                result.setdefault('current_periods_list',
                    {})[report.id] = ", ".join([p.rec_name
                        for p in report.current_periods])
            if 'previous_periods_list' in names:
                result.setdefault('previous_periods_list',
                    {})[report.id] = ", ".join([p.rec_name
                        for p in report.previous_periods])
        return result

    @classmethod
    def get_dates(cls, reports, names):
        result = {}
        for report in reports:
            if 'current_periods_start_date' in names:
                if report.current_periods:
                    start = min(p.start_date for p in report.current_periods)
                else:
                    start = report.current_fiscalyear.start_date
                result.setdefault('current_periods_start_date',
                    {})[report.id] = datetime.combine(start,
                        datetime.min.time())
            if 'current_periods_end_date' in names:
                if report.current_periods:
                    end = max(p.end_date for p in report.current_periods)
                else:
                    end = report.current_fiscalyear.end_date
                result.setdefault('current_periods_end_date',
                    {})[report.id] = datetime.combine(end,
                        datetime.min.time())
            if 'previous_periods_start_date' in names:
                if report.previous_periods:
                    start = min(p.start_date for p in report.previous_periods)
                else:
                    start = report.previous_fiscalyear.start_date
                result.setdefault('previous_periods_start_date',
                    {})[report.id] = datetime.combine(start,
                        datetime.min.time())
            if 'previous_periods_end_date' in names:
                if report.previous_periods:
                    end = max(p.end_date for p in report.previous_periods)
                else:
                    end = report.previous_fiscalyear.end_date
                result.setdefault('previous_periods_end_date',
                    {})[report.id] = datetime.combine(end,
                        datetime.min.time())
        return result

    @classmethod
    @ModelView.button
    @Workflow.transition('calculated')
    def calculate(cls, reports):
        Line = Pool().get('account.financial.statement.report.line')
        TemplateLine = Pool().get('account.financial.statement.template.line')
        for report in reports:
            Line.delete(report.lines)
            template_lines = TemplateLine.search([
                    ('template', '=', report.template),
                    ('parent', '=', None),
                    ])
            for template_line in template_lines:
                template_line.create_report_line(report)
            lines = Line.search([
                    ('report', '=', report.id),
                    ('parent', '=', None),
                    ])
            for line in lines:
                line.refresh_values()
        cls.write(reports, {
                'calculation_date': datetime.now(),
                })

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, reports):
        pool = Pool()
        Line = pool.get('account.financial.statement.report.line')
        lines = []
        for report in reports:
            lines += report.lines
        Line.delete(lines)
        cls.write(reports, {
                'calculation_date': None,
                'lines': None,
                })

    @classmethod
    def copy(cls, reports, default=None):
        if default is None:
            default = {}
        default = default.copy()
        if 'lines' not in default:
            default['lines'] = None
        if 'calculation_date' not in default:
            default['calculation_date'] = None
        return super(Report, cls).copy(reports, default=default)


class ReportJasper(JasperReport):
    'Financial Statement Report'
    __name__ = 'account.financial.statement.report'


class ReportCurrentPeriods(ModelSQL):
    'Financial Statement Report - Current Periods'
    __name__ = 'account_financial_statement-account_period_current'
    _table = 'account_financial_statement_current_period_rel'
    report = fields.Many2One('account.financial.statement.report',
        'Account Report', ondelete='CASCADE', select=True, required=True)
    period = fields.Many2One('account.period', 'Period',
        ondelete='CASCADE', select=True, required=True)


class ReportPreviousPeriods(ModelSQL):
    'Financial Statement Report - Previous Periods'
    __name__ = 'account_financial_statement-account_period_previous'
    _table = 'account_financial_statement_previous_period_rel'
    report = fields.Many2One('account.financial.statement.report',
        'Account Report', ondelete='CASCADE', select=True, required=True)
    period = fields.Many2One('account.period', 'Period',
        ondelete='CASCADE', select=True, required=True)


class ReportLine(ModelSQL, ModelView):
    """
    Financial Statement Report Line
    One line of detail of the report representing an accounting concept with
    its values.
    The accounting concepts follow a parent-children hierarchy.
    Its values (current and previous) are calculated based on the 'value'
    formula of the linked template line.
    """
    __name__ = 'account.financial.statement.report.line'
    _states = {
        'readonly': Eval('report_state') != 'draft',
        }
    _depends = ['report_state']

    name = fields.Char('Name', required=True, select=True, states=_states,
        depends=_depends)
    report = fields.Many2One('account.financial.statement.report', 'Report',
        required=True, ondelete='CASCADE',
        states={
            'readonly': _states['readonly'] & Bool(Eval('report')),
            },
        depends=_depends + ['report'])
    # Concept official code (as specified by normalized models,
    # will be used when printing)
    code = fields.Char('Code', required=True, select=True, states=_states,
        depends=_depends)
    notes = fields.Text('Notes')
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'get_currency_digits')
    current_value = fields.Numeric('Current Value',
        digits=(16, Eval('currency_digits', 2)), depends=['currency_digits'])
    previous_value = fields.Numeric('Previous value',
        digits=(16, Eval('currency_digits', 2)), depends=['currency_digits'])
    calculation_date = fields.DateTime('Calculation date', readonly=True)
    template_line = fields.Many2One('account.financial.statement.template.line',
        'Line template', ondelete='SET NULL')
    parent = fields.Many2One('account.financial.statement.report.line',
        'Parent', ondelete='CASCADE',
        domain=[
            ('report', '=', Eval('report')),
            ],
        states=_states, depends=_depends + ['report'])
    children = fields.One2Many('account.financial.statement.report.line',
        'parent', 'Children',
        domain=[
            ('report', '=', Eval('report')),
            ],
        states=_states, depends=_depends + ['report'])
    visible = fields.Boolean('Visible')

    # Order sequence, it's also used for grouping into sections,
    # that's why it is a char
    sequence = fields.Char('Sequence', states=_states, depends=_depends)
    css_class = fields.Selection(CSS_CLASSES, 'CSS Class', states=_states,
        depends=_depends)
    line_accounts = fields.One2Many(
        'account.financial.statement.report.line.account',
        'report_line', 'Line Accounts', states=_states, depends=_depends)
    current_line_accounts = fields.Function(fields.One2Many(
            'account.financial.statement.report.line.account', 'report_line',
            'Current Detail', states=_states, depends=_depends),
        'get_line_accounts')
    previous_line_accounts = fields.Function(fields.One2Many(
            'account.financial.statement.report.line.account', 'report_line',
            'Previous Detail', states=_states, depends=_depends),
        'get_line_accounts')
    report_state = fields.Function(fields.Selection(STATES, 'Report State'),
        'on_change_with_report_state')
    del _states, _depends

    def get_currency_digits(self, name):
        if self.report:
            return self.report.company.currency.digits
        return 2

    @classmethod
    def get_line_accounts(cls, report_lines, names):
        result = {}
        for report_line in report_lines:
            if 'current_line_accounts' in names:
                result.setdefault('current_line_accounts',
                    {})[report_line.id] = [x.id
                        for x in report_line.line_accounts
                        if x.fiscal_year == 'current']
            if 'previous_line_accounts' in names:
                result.setdefault('previous_line_accounts',
                    {})[report_line.id] = [x.id
                        for x in report_line.line_accounts
                        if x.fiscal_year == 'previous']
        return result

    @classmethod
    def __setup__(cls):
        super(ReportLine, cls).__setup__()
        t = cls.__table__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._order.insert(1, ('code', 'ASC'))
        cls._sql_constraints += [
            ('report_code_uniq', Unique(t, t.report, t.code),
                'account_financial_statement.msg_code_unique_per_report'),
            ]
        cls._buttons.update({
                'open_details': {},
                })

    @fields.depends('report')
    def on_change_with_report_state(self, name=None):
        if self.report:
            return self.report.state

    @staticmethod
    def default_css_class():
        return 'default'

    @staticmethod
    def default_visible():
        return True

    def get_rec_name(self, name):
        if self.code:
            return '[%s] %s' % (self.code, self.name)
        return self.name

    @classmethod
    def search_rec_name(cls, name, clause):
        ids = [x.id for x in cls.search([('code',) + tuple(clause[1:])],
                order=[])]
        if ids:
            ids += [x.id for x in cls.search([('name',) + tuple(clause[1:])],
                    order=[])]
            return [('id', 'in', ids)]
        return [('name',) + tuple(clause[1:])]

    def balance(self, *account_codes):
        result = 0
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='balance')
        return result

    def invert(self, *account_codes):
        result = 0
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='balance',
                invert=True)
        return result

    def debit(self, *account_codes):
        result = 0
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='debit')
        return result

    def credit(self, *account_codes):
        result = 0
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='credit')
        return result

    def concept(self, value, *concepts):
        result = 0
        for concept in concepts:
            # Check the sign of the code (substraction)
            try:
                int_concept = int(concept)
            except ValueError:
                int_concept = 0
            if int_concept < 0:
                sign = -Decimal('1.0')
                concept = abs(concept)
            else:
                sign = Decimal('1.0')
            concept = str(concept)
            # Search for the line (perfect match)
            lines = self.search([
                    ('report', '=', self.report.id),
                    ('code', '=', concept),
                    ])
            for child in lines:
                if child.calculation_date != child.report.calculation_date:
                    # Tell the child to refresh its values
                    child.refresh_values()
                result += getattr(child, value) * sign
        return result

    def refresh_values(self):
        """
        Recalculates the values of this report line using the
        linked line template values formulas:

        Depending on this formula the final value is calculated as follows:
        - Empy template value: sum of (this concept) children values.
        - Evaluate python expression using simpleeval with self.invert(),
        self.debit(), self.credit(), self.concept() helpers.
        """
        for child in self.children:
            child.refresh_values()
        for fyear in ('current', 'previous'):
            value = 0
            getvalue = '%s_value' % (fyear)
            template_value = getattr(self.template_line, getvalue)

            # Remove characters after a ";" (we use ; for comments)
            if template_value and len(template_value):
                template_value = template_value.split(';')[0]

            getfiscalyear = '%s_fiscalyear' % (fyear)
            if not getattr(self.report, getfiscalyear):
                value = 0
            else:
                if not template_value or not len(template_value):
                    # Empy template value => sum of the children, of this
                    # concept, values.
                    for child in self.children:
                        if (child.calculation_date
                                != child.report.calculation_date):
                            # Tell the child to refresh its values
                            child.refresh_values()
                        value += getattr(child, getvalue)

                else:

                    # We will use the context to filter the accounts by
                    # fiscalyear and periods.
                    getperiods = '%s_periods' % (fyear)
                    ctx = {
                        'fiscalyear': getattr(self.report, getfiscalyear).id,
                        'periods': [p.id for p in getattr(self.report,
                                getperiods)],
                        'period': fyear,
                        'cumulate': self.template_line.template.cumulate,
                        }
                    with Transaction().set_context(ctx):
                        functions = {'balance': self.balance,
                            'invert': self.invert,
                            'debit': self.debit,
                            'credit': self.credit,
                            'concept': partial(self.concept, getvalue),
                            'Decimal': Decimal}
                        value = simple_eval(decistmt(template_value),
                            functions=functions)
                        if isinstance(value, Decimal):
                            value = value.quantize(
                                Decimal(10) ** -self.currency_digits)

            # Negate the value if needed
            if self.template_line.negate:
                value = -value
            setattr(self, getvalue, value)
        self.calculation_date = self.report.calculation_date
        self.save()

    def _get_account_(self, code, mode, invert=False):
        """
        It returns the (debit, credit, *) tuple for a account with the
        given code, or the sum of those values for a set of accounts
        when the code is in the form "400,300,(323)"

        Also the user may specify to use only the debit or credit of the
        account instead of the balance using the mode parameter.
        """
        context = Transaction().context
        pool = Pool()
        Account = pool.get('account.account')
        ReportLineAccount = pool.get(
            'account.financial.statement.report.line.account')
        balance_mode = self.template_line.template.mode
        res = Decimal('0.0')
        vlist = []
        for account_code in re.findall(r'(-?\w*\(?[0-9a-zA-Z_]*\)?)', code):
            # Check if the code is valid (findall might return empty strings)
            if len(account_code) > 0:
                # Check the sign of the code (substraction)
                if account_code.startswith('-'):
                    sign = Decimal('-1.0')
                    account_code = account_code[1:]  # Strip the sign
                else:
                    sign = Decimal('1.0')

                if balance_mode == 'credit-debit' and mode != 'balance':
                    sign = Decimal('-1.0') * sign
                else:
                    # Calculate the , as given by mode
                    if balance_mode == 'debit-credit-reversed':
                        # We use debit-credit as default ,
                        # but for accounts in brackets we use credit-debit
                        if invert:
                            sign = Decimal('-1.0') * sign
                    elif balance_mode == 'credit-debit':
                        # We use credit-debit as the ,
                        sign = Decimal('-1.0') * sign
                    elif balance_mode == 'credit-debit-reversed':
                        # We use credit-debit as default ,
                        # but for accounts in brackets we use debit-credit
                        if not invert:
                            sign = Decimal('-1.0') * sign

                # Search for the account (perfect match)
                accounts = Account.search([
                        ('code', '=', account_code),
                        ])
                if not accounts:
                    # We didn't find the account, search for a subaccount
                    # ending with '0'
                    accounts = Account.search([
                            ('code', 'like', '%s%%0' % account_code),
                            ])
                if accounts:
                    accounts = Account.search([
                            ('parent', 'child_of', [a.id for a in accounts]),
                            ])
                    credit_debit = self._get_credit_debit(accounts)
                    for account in credit_debit['credit']:
                        balance = credit_debit['debit'][account] - \
                                credit_debit['credit'][account]
                        value = {
                            'report_line': self,
                            'fiscal_year': context.get('period'),
                            'account': account,
                            }
                        if mode == 'debit' and balance > 0.0 or \
                                mode == 'credit' and balance < 0.0 or \
                                mode == 'balance':
                            res += balance * sign
                            value['credit'] = credit_debit['credit'][account]
                            value['debit'] = credit_debit['debit'][account]
                        if value.get('credit') or value.get('debit'):
                            vlist.append(value)
        ReportLineAccount.create(vlist)
        return res

    def _get_credit_debit(self, accounts):
        'Returns the credit debit values for this accounts'
        pool = Pool()
        Account = pool.get('account.account')
        return Account.get_credit_debit(accounts, ['debit', 'credit'])

    @classmethod
    @ModelView.button_action('account_financial_statement.act_open_detail')
    def open_details(cls, lines):
        pass


class ReportLineAccount(ModelSQL, ModelView):
    'Financial Statement Report Account'
    __name__ = 'account.financial.statement.report.line.account'
    _table = 'account_financial_statement_rep_lin_acco'
    report_line = fields.Many2One('account.financial.statement.report.line',
        'Report Line', ondelete='CASCADE')
    account = fields.Many2One('account.account', 'Account', required=True)
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'get_currency_digits')
    credit = fields.Numeric('Credit', digits=(16, Eval('currency_digits', 2)),
        depends=['currency_digits'])
    debit = fields.Numeric('Debit', digits=(16, Eval('currency_digits', 2)),
        depends=['currency_digits'])
    balance = fields.Function(fields.Numeric('Balance',
            digits=(16, Eval('currency_digits', 2)),
            depends=['currency_digits']), 'get_balance')
    fiscal_year = fields.Selection([
            ('current', 'Current'),
            ('previous', 'Previous'),
            ], 'Fiscal Year')

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')

        # Migration from 3.6: rename table
        old_table = 'account_financial_statement_report_line_account'
        new_table = 'account_financial_statement_rep_lin_acco'
        if TableHandler.table_exist(old_table):
            TableHandler.table_rename(old_table, new_table)

        super(ReportLineAccount, cls).__register__(module_name)

        super(ReportLineAccount, cls).__register__(module_name)

    def get_currency_digits(self, name):
        return self.account.currency_digits

    def get_balance(self, name):
        if self.report_line.report.template.mode[0:5] == 'debit':
            return self.debit - self.credit
        else:
            return self.credit - self.debit


class ReportLineDetailStart(ModelView):
    'Financial Statement Report Account Line Detail Start'
    __name__ = 'account.financial.statement.report.line.detail.start'

    detail = fields.Selection([
            ('account', 'Account'),
            ('move', 'Move'),
            ], 'Detail Level', required=True)
    fiscalyear = fields.Selection([
            ('current', 'Current'),
            ('previous', 'Previous'),
            ], 'Fiscal Year', required=True)

    @staticmethod
    def default_detail():
        return 'account'

    @staticmethod
    def default_fiscalyear():
        return 'current'


class ReportLineDetail(Wizard):
    'Financial Statement Report Account Line Detail'
    __name__ = 'account.financial.statement.report.line.detail'

    start = StateView('account.financial.statement.report.line.detail.start',
        'account_financial_statement.report_line_detail_start_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Open', 'select', 'tryton-go-next', default=True),
            ])
    select = StateTransition()
    account = StateAction(
        'account_financial_statement.act_report_line_account')
    move = StateAction('account.act_move_line_form')

    def transition_select(self):
        return self.start.detail

    def do_account(self, action):
        pool = Pool()
        Line = pool.get('account.financial.statement.report.line')
        lines = Line.search([
                ('parent', 'child_of', Transaction().context['active_id']),
                ])
        action['pyson_domain'] = PYSONEncoder().encode([
                ('report_line', 'in', [l.id for l in lines]),
                ('fiscal_year', '=', self.start.fiscalyear),
                ])
        return action, {}

    def do_move(self, action):
        pool = Pool()
        Line = pool.get('account.financial.statement.report.line')
        LineAccount = pool.get(
            'account.financial.statement.report.line.account')

        line = Line(Transaction().context['active_id'])
        report = line.report

        lines = Line.search([
                ('parent', 'child_of', line.id),
                ])
        accounts = list(set(l.account.id for l in LineAccount.search([
                        ('report_line', 'in', lines)
                        ])))

        periods = []
        if self.start.fiscalyear == 'current':
            periods = [p.id for p in report.current_periods]
            fiscalyear = report.current_fiscalyear
        else:
            periods = [p.id for p in report.previous_periods]
            fiscalyear = report.previous_fiscalyear

        domain = [
            ('account', 'in', accounts),
            ('period.fiscalyear', '=', fiscalyear.id),
            ]

        if periods:
            domain.append(('period', 'in', periods))

        action['pyson_domain'] = PYSONEncoder().encode(domain)
        return action, {}


class Template(ModelSQL, ModelView):
    """
    Financial Statement Template
    It stores the header fields of an account report template,
    and the linked lines of detail with the formulas to calculate
    the accounting concepts of the report.
    """
    __name__ = "account.financial.statement.template"

    name = fields.Char('Name', required=True, select=True, translate=True)
    type = fields.Selection([
            ('system', 'System'),
            ('user', 'User')
            ], 'Type', readonly=True, help='System reports cannot be modified')
    report_xml = fields.Many2One('ir.action.report', 'Report design',
        domain=[('model', '=', 'account.financial.statement.report')],
        ondelete='SET NULL')
    lines = fields.One2Many('account.financial.statement.template.line',
        'template', 'Lines')
    description = fields.Text('Description')
    mode = fields.Selection([
            ('debit-credit', 'Debit-Credit'),
            ('debit-credit-reversed', 'Debit-Credit, reversed with invert()'),
            ('credit-debit', 'Credit-Debit'),
            ('credit-debit-reversed', 'Credit-Debit, reversed with invert()')
            ], 'Mode')
    cumulate = fields.Boolean('Cumulate Balances')

    @staticmethod
    def default_type():
        return 'user'

    @staticmethod
    def default_mode():
        return 'debit-credit'

    @staticmethod
    def default_cumulate():
        return False

    @classmethod
    def copy(cls, templates, default=None):
        Line = Pool().get('account.financial.statement.template.line')

        if default is None:
            default = {}
        default = default.copy()
        if 'lines' not in default:
            default['lines'] = None
        new_templates = []
        for template in templates:
            default['name'] = template.name + '*'
            new_template, = super(Template, cls).copy([template],
                default=default)
            root_lines = [x for x in template.lines if not x.parent]
            Line.copy(root_lines, default={
                    'template': new_template.id,
                    'children': None,
                    })
            new_templates.append(new_template)
        return new_templates


class TemplateLine(ModelSQL, ModelView):
    """
    Financial Statement Template Line
    One line of detail of the  report representing an accounting
    concept with the formulas to calculate its values.
    The accounting concepts follow a parent-children hierarchy.
    """
    __name__ = 'account.financial.statement.template.line'

    template = fields.Many2One('account.financial.statement.template',
        'Template', ondelete='CASCADE')
    # Order sequence, it's also used for grouping into sections,
    # that's why it is a char
    sequence = fields.Char('Sequence',
        help='Lines will be sorted/grouped by this field')
    css_class = fields.Selection(CSS_CLASSES, 'CSS Class',
        help='Style-sheet class')

    # Concept official code (as specified by normalized models,
    # will be used when printing)
    code = fields.Char('Code', required=True, select=True,
        help='Concept code, may be used in formulas to reference this line')
    # Concept official name (will be used when printing)
    name = fields.Char('Name', required=True, select=True, translate=True,
        help='Concept name/description')
    current_value = fields.Text('Fiscal year 1 formula',
        help=_VALUE_FORMULA_HELP)
    previous_value = fields.Text('Fiscal year 2 formula',
        help=_VALUE_FORMULA_HELP)
    negate = fields.Boolean('Negate',
        help='Negate the value (change the sign of the )')
    parent = fields.Many2One('account.financial.statement.template.line',
        'Parent', ondelete='CASCADE')
    children = fields.One2Many('account.financial.statement.template.line',
        'parent', 'Children')
    visible = fields.Boolean('Visible')

    @classmethod
    def __setup__(cls):
        super(TemplateLine, cls).__setup__()
        t = cls.__table__()
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._order.insert(1, ('code', 'ASC'))
        cls._sql_constraints += [
            ('report_code_uniq', Unique(t, t.template, t.code),
                'account_financial_statement.msg_code_unique_per_template'),
            ]

    @classmethod
    def validate(cls, records):
        super(TemplateLine, cls).validate(records)
        for record in records:
            record.check_syntax()

    def check_syntax(self):
        pool = Pool()
        Translation = pool.get('ir.translation')
        language = Transaction().language

        for value in ['current_value', 'previous_value']:
            try:
                parse((getattr(self, value) or '').split(';')[0])
            except SyntaxError:
                field_name = '{},{}'.format(self.__name__,value)
                field_string = Translation.get_source(field_name, 'field',
                    language)
                raise UserError(gettext('account_financial_statement.'
                        'msg_code_unique_per_template',
                    field=field_string, line=self.code))

    @staticmethod
    def default_negate():
        return False

    @staticmethod
    def default_css_class():
        return 'default'

    @staticmethod
    def default_visible():
        return True

    def get_rec_name(self, name):
        if self.code:
            return '[%s] %s' % (self.code, self.name)
        return self.name

    @classmethod
    def search_rec_name(cls, name, clause):
        ids = list(map(int, cls.search([('code',) + tuple(clause[1:])], order=[])))
        if ids:
            ids += list(map(int, cls.search([('name',) + tuple(clause[1:])],
                    order=[])))
            return [('id', 'in', ids)]
        return [('name',) + tuple(clause[1:])]

    def _get_line(self):
        pool = Pool()
        ReportLine = pool.get('account.financial.statement.report.line')
        return ReportLine(
            code=self.code,
            name=self.name,
            template_line=self,
            parent=None,
            current_value=None,
            previous_value=None,
            visible=self.visible,
            sequence=self.sequence,
            css_class=self.css_class,
            )

    def create_report_line(self, report, template2line=None, parent=None):
        '''
        Create recursively report lines based on template lines.
        template2line is a dictionary with template id as key and line id
        as value, used to convert template id into line. The dictionary is
        filled with new lines
        Returns the instance of the line created
        '''
        pool = Pool()
        Line = pool.get('account.financial.statement.report.line')
        Lang = pool.get('ir.lang')
        Config = pool.get('ir.configuration')

        if template2line is None:
            template2line = {}

        if self.id not in template2line:
            line = self._get_line()
            line.parent = parent
            line.report = report
            line.save()

            prev_lang = self._context.get('language') or Config.get_language()
            prev_data = {}
            for field_name, field in self._fields.items():
                if getattr(field, 'translate', False):
                    prev_data[field_name] = getattr(self, field_name)
            for lang in Lang.get_translatable_languages():
                if lang == prev_lang:
                    continue
                with Transaction().set_context(language=lang):
                    template = self.__class__(self.id)
                    data = {}
                    for field_name, field in self._fields.items():
                        if (getattr(field, 'translate', False)
                                and (getattr(template, field_name) !=
                                    prev_data[field_name])):
                            data[field_name] = getattr(template, field_name)
                    if data:
                        Line.write([line], data)
            template2line[self.id] = line.id
        for child in self.children:
            child.create_report_line(report, template2line=template2line,
                parent=line)
        return line

    @classmethod
    def copy(cls, records, default=None):
        if default is None:
            default = {}
        new_lines = []
        for record in records:
            new_line, = super(TemplateLine, cls).copy([record], default)
            new_lines.append(new_line)
            new_default = default.copy()
            new_default['parent'] = new_line.id
            cls.copy(record.children, default=new_default)
        return new_lines
