# This file is part of account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import re
from ast import parse
from datetime import datetime
from decimal import Decimal
from functools import partial

from simpleeval import simple_eval

from trytond.exceptions import UserError
from trytond.i18n import gettext
from trytond.model import ModelSQL, ModelView, Unique, Workflow, fields
from trytond.model.exceptions import ValidationError
from trytond.model import DeactivableMixin
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.tools import decistmt
from trytond.transaction import Transaction
from trytond.wizard import (
    Button,
    StateView,
    Wizard,
)

CSS_CLASSES = [
    ('default', 'Default'),
    ('l1', 'Level 1'),
    ('l2', 'Level 2'),
    ('l3', 'Level 3'),
    ('l4', 'Level 4'),
    ('l5', 'Level 5'),
    ]

_STATES = {
    'readonly': Eval('state') == 'calculated',
    }

_VALUE_FORMULA_HELP = ('Value calculation formula: Depending on this formula '
    'the final value is calculated as follows:\n'
    '- Empy template value: sum of (this concept) children values.\n'
    '- Number with decimal point ("10.2"): that value (constant).\n'
    '- A matematic formula with following helpers:\n'
    '  * balance() with comma-separated account numbers. Sum of the accounts '
    '(the sign of the depends on the mode).\n'
    '  * invert() with comma-separated account numbers. Sum of the account '
    '(the sign is inverted if reversed modes are used).\n'
    '  * credit() with comma-separeted account numbers. Sum of the credit of '
    'the account if the total amount is negative. Zero otherwise.\n'
    '  * debit() with comma-separeted account numbers. Sum of the debit of '
    'the account if the total amount is positive. Zero otherwise.\n'
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

    name = fields.Char('Name', required=True)
    state = fields.Selection(STATES, 'State', readonly=True)
    template = fields.Many2One('account.financial.statement.template',
        'Template', ondelete='SET NULL', required=True, states=_STATES)
    calculation_date = fields.DateTime('Calculation date', readonly=True)
    company = fields.Many2One('company.company', 'Company', ondelete='CASCADE',
        readonly=True, required=True)
    comparison_fiscalyears = fields.Function(
        fields.Char('Fiscal Years'), 'get_comparison_fiscalyears')
    comparison_periods = fields.One2Many(
        'account.financial.statement.report.period', 'report',
        'Comparison Periods', states=_STATES,
        order=[('sequence', 'ASC'), ('id', 'ASC')])

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
                    'icon': 'tryton-forward',
                    },
                'draft': {
                    'invisible': Eval('state') != 'calculated',
                    'icon': 'tryton-back',
                    },
                })

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        table = cls.__table_handler__(module_name)
        for column in ['current_fiscalyear', 'previous_fiscalyear']:
            if table.column_exist(column):
                table.not_null_action(column, action='remove')

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_state():
        return 'draft'

    @classmethod
    def validate(cls, reports):
        super().validate(reports)
        for report in reports:
            if len(report.comparison_periods) > 10:
                raise ValidationError(
                    gettext(
                        'account_financial_statement.'
                        'msg_financial_statement_max_periods'))

    @classmethod
    def copy(cls, reports, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('comparison_periods')
        default.setdefault('calculation_date', None)
        return super(Report, cls).copy(reports, default=default)

    @classmethod
    def get_comparison_fiscalyears(cls, reports, name):
        values = {}
        for report in reports:
            periods = sorted(report.comparison_periods,
                key=lambda p: (
                    p.fiscalyear.start_date,
                    p.fiscalyear.end_date,
                    p.id))
            names = [p.fiscalyear.rec_name for p in periods if p.fiscalyear]
            if len(names) > 5:
                values[report.id] = '%s ... %s' % (names[0], names[-1])
            else:
                values[report.id] = ' / '.join(names)
        return values

    @classmethod
    def _ordered_periods(cls, report):
        return sorted(report.comparison_periods,
            key=lambda p: ((p.sequence if p.sequence is not None else 0),
                p.id or 0))

    @classmethod
    @ModelView.button
    @Workflow.transition('calculated')
    def calculate(cls, reports):
        pool = Pool()
        ReportLinePeriod = pool.get('account.financial.statement.report.line.period')
        TemplateLine = pool.get('account.financial.statement.template.line')

        for report in reports:
            periods = cls._ordered_periods(report)
            if not periods:
                raise UserError(
                    gettext(
                        'account_financial_statement.'
                        'msg_financial_statement_missing_periods'))

            existing_lines = ReportLinePeriod.search([
                    ('report_period', 'in', periods),
                    ], order=[])
            if existing_lines:
                ReportLinePeriod.delete(existing_lines)

            report.calculation_date = datetime.now()
            report.save()

            template_lines = TemplateLine.search([
                    ('template', '=', report.template),
                    ('parent', '=', None),
                    ])
            for report_period in periods:
                for template_line in template_lines:
                    ReportLinePeriod.create_from_template(report_period,
                        template_line)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, reports):
        pool = Pool()
        ReportLinePeriod = pool.get('account.financial.statement.report.line.period')

        for report in reports:
            periods = cls._ordered_periods(report)
            existing_lines = ReportLinePeriod.search([
                    ('report_period', 'in', [period.id for period in periods]),
                    ], order=[])
            if existing_lines:
                ReportLinePeriod.delete(existing_lines)
            report.calculation_date = None
            report.save()


class ReportPeriod(ModelSQL, ModelView):
    'Financial Statement Report Period'
    __name__ = 'account.financial.statement.report.period'

    sequence = fields.Integer('Sequence')
    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company')
    report = fields.Many2One('account.financial.statement.report', 'Report',
        required=True, ondelete='CASCADE')
    fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal Year',
        required=True,
        domain=[('company', '=', Eval('_parent_report', {}).get('company', -1))],
        states={'readonly': Eval('_parent_report.state') != 'draft'},
        depends=['report'])
    start_period = fields.Many2One('account.period', 'Start Period',
        domain=[('fiscalyear', '=', Eval('fiscalyear', -1))],
        states={'readonly': Eval('_parent_report.state') != 'draft'},
        depends=['fiscalyear', 'report'])
    end_period = fields.Many2One('account.period', 'End Period',
        domain=[('fiscalyear', '=', Eval('fiscalyear', -1))],
        states={'readonly': Eval('_parent_report.state') != 'draft'},
        depends=['fiscalyear', 'report'])
    lines = fields.One2Many('account.financial.statement.report.line.period',
        'report_period', 'Lines', readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls._order = [('sequence', 'ASC NULLS FIRST'), ('id', 'ASC')] + cls._order
        cls.__access__.add('report')

    @classmethod
    def validate(cls, periods):
        super().validate(periods)
        for period in periods:
            if bool(period.start_period) != bool(period.end_period):
                raise ValidationError(
                    gettext(
                        'account_financial_statement.'
                        'msg_financial_statement_period_pair'))
            if (period.start_period and period.end_period
                    and period.start_period.start_date
                    > period.end_period.end_date):
                raise ValidationError(
                    gettext(
                        'account_financial_statement.'
                        'msg_financial_statement_period_order'))

    @fields.depends('report', '_parent_report.company')
    def on_change_with_company(self, name=None):
        if self.report and self.report.company:
            return self.report.company.id

    def get_periods(self):
        pool = Pool()
        Period = pool.get('account.period')
        domain = [('fiscalyear', '=', self.fiscalyear)]
        if (not (self.start_period and self.end_period)
                or self.end_period.type != 'adjustment'):
            domain.append(('type', '=', 'standard'))
        periods = Period.search(domain, order=[('start_date', 'ASC'), ('id', 'ASC')])
        if self.start_period and self.end_period:
            periods = [p for p in periods
                if self.start_period.start_date <= p.start_date
                and p.end_date <= self.end_period.end_date]
        return periods

    def get_rec_name(self, name):
        if self.start_period and self.end_period:
            return '%s - %s' % (self.start_period.rec_name, self.end_period.rec_name)
        return self.fiscalyear.rec_name

class ViewAccountsStart(ModelView):
    'View Used And Unused Accounts Start'
    __name__ = 'account.financial.statement.report.accounts.start'
    used_accounts = fields.Many2Many('account.account', None, None,
            'Used Accounts')
    unused_accounts = fields.Many2Many('account.account', None, None,
            'Unused Accounts')


class ViewAccounts(Wizard):
    'View Used And Unused Accounts'
    __name__ = 'account.financial.statement.report.accounts'

    start = StateView('account.financial.statement.report.accounts.start',
        'account_financial_statement.view_accounts_start_form', [
            Button('Close', 'end', 'tryton-close')
        ])

    def default_start(self, fields):
        pool = Pool()
        Account = pool.get('account.account')

        used = []
        for report_period in self.record.comparison_periods:
            for line in report_period.lines:
                for account in line.line_accounts:
                    used.append(account.account)

        all_accounts = Account.search([
                ('company', '=', self.record.company),
                ('parent', '!=', None),
                ('type', '!=', None),
                ])
        unused = list(set(all_accounts) - set(used))
        unused = [x.id for x in sorted(unused, key=lambda x: x.code)]
        used = [x.id for x in sorted(set(used), key=lambda x: x.code)]
        return {
            'used_accounts': used,
            'unused_accounts': unused,
            }


class ReportLinePeriod(ModelSQL, ModelView):
    'Financial Statement Report Line Period'
    __name__ = 'account.financial.statement.report.line.period'

    report_period = fields.Many2One(
        'account.financial.statement.report.period', 'Comparison Period',
        required=True, ondelete='CASCADE', readonly=True)
    name = fields.Char('Name', required=True, readonly=True)
    code = fields.Char('Code', required=True, readonly=True)
    notes = fields.Text('Notes', readonly=True)
    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company')
    currency = fields.Function(
        fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')
    value = Monetary('Value', digits='currency', currency='currency',
        readonly=True)
    template_line = fields.Many2One('account.financial.statement.template.line',
        'Line template', ondelete='SET NULL', readonly=True)
    parent = fields.Many2One('account.financial.statement.report.line.period',
        'Parent', ondelete='CASCADE',
        domain=[('report_period', '=', Eval('report_period'))],
        depends=['report_period'], readonly=True)
    children = fields.One2Many('account.financial.statement.report.line.period',
        'parent', 'Children',
        domain=[('report_period', '=', Eval('report_period'))],
        depends=['report_period'], readonly=True)
    visible = fields.Boolean('Visible', readonly=True)
    sequence = fields.Char('Sequence', readonly=True)
    css_class = fields.Selection(CSS_CLASSES, 'CSS Class', readonly=True)
    page_break = fields.Boolean('Page Break', readonly=True)
    line_accounts = fields.One2Many(
        'account.financial.statement.report.line.account.period',
        'report_line', 'Line Accounts', readonly=True)

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('report_period')
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._order.insert(1, ('code', 'ASC'))
        t = cls.__table__()
        cls._sql_constraints += [
            ('report_period_code_uniq', Unique(t, t.report_period, t.code),
                'account_financial_statement.msg_code_unique_per_report'),
            ]

    @staticmethod
    def default_css_class():
        return 'default'

    @staticmethod
    def default_visible():
        return True

    @fields.depends('report_period', '_parent_report_period.company')
    def on_change_with_company(self, name=None):
        if self.report_period and self.report_period.report.company:
            return self.report_period.report.company.id

    @fields.depends('report_period', '_parent_report_period.company')
    def on_change_with_currency(self, name=None):
        if self.report_period and self.report_period.company:
            return self.report_period.company.currency.id

    def get_rec_name(self, name):
        if self.code:
            return '[%s] %s' % (self.code, self.name)
        return self.name

    @classmethod
    def create_from_template(cls, report_period, template_line, parent=None,
            cache=None):
        if cache is None:
            cache = {}
        line = cls(
            report_period=report_period,
            name=template_line.name,
            code=template_line.code,
            template_line=template_line,
            parent=parent,
            visible=template_line.visible,
            sequence=template_line.sequence,
            css_class=template_line.css_class,
            page_break=template_line.page_break,
            )
        line.save()
        for child in template_line.children:
            cls.create_from_template(report_period, child, parent=line,
                cache=cache)
        line.refresh_value(cache=cache)
        return line

    def balance(self, *account_codes):
        result = Decimal(0)
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='balance')
        return result

    def invert(self, *account_codes):
        result = Decimal(0)
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='balance',
                invert=True)
        return result

    def debit(self, *account_codes):
        result = Decimal(0)
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='debit')
        return result

    def credit(self, *account_codes):
        result = Decimal(0)
        for account_code in account_codes:
            result += self._get_account_(str(account_code), mode='credit')
        return result

    def _concept_value(self, cache, *concepts):
        result = Decimal(0)
        for concept in concepts:
            try:
                int_concept = int(concept)
            except (TypeError, ValueError):
                int_concept = 0
            if int_concept < 0:
                sign = Decimal('-1.0')
                concept = abs(int_concept)
            else:
                sign = Decimal('1.0')
            concept = str(concept)
            lines = self.search([
                    ('report_period', '=', self.report_period),
                    ('code', '=', concept),
                    ])
            for line in lines:
                result += line.refresh_value(cache=cache) * sign
        return result

    def _percent_value(self, cache, *concepts):
        if len(concepts) != 2:
            return Decimal(0)
        divisor_lines = self.search([
                ('report_period', '=', self.report_period),
                ('code', '=', str(concepts[0])),
                ], limit=1)
        dividend_lines = self.search([
                ('report_period', '=', self.report_period),
                ('code', '=', str(concepts[1])),
                ], limit=1)
        if not divisor_lines or not dividend_lines:
            return Decimal(0)
        divisor_value = divisor_lines[0].refresh_value(cache=cache)
        if divisor_value == 0:
            return Decimal(0)
        dividend_value = dividend_lines[0].refresh_value(cache=cache)
        return divisor_value / dividend_value

    def refresh_value(self, cache=None):
        if cache is None:
            cache = {}
        cache_key = self.id
        if cache_key in cache:
            return cache[cache_key]

        value = Decimal(0)
        template_value = self.template_line.current_value
        if template_value:
            template_value = template_value.split(';', 1)[0]

        if not self.report_period.fiscalyear:
            value = Decimal(0)
        elif not template_value:
            value = sum(child.refresh_value(cache=cache)
                for child in self.children)
        else:
            ctx = {
                'fiscalyear': self.report_period.fiscalyear.id,
                'periods': [p.id for p in self.report_period.get_periods()],
                'cumulate': self.template_line.template.cumulate,
                }
            with Transaction().set_context(ctx):
                functions = {
                    'balance': self.balance,
                    'invert': self.invert,
                    'debit': self.debit,
                    'credit': self.credit,
                    'concept': partial(self._concept_value, cache),
                    'percent': partial(self._percent_value, cache),
                    'Decimal': Decimal,
                    }
                try:
                    value = simple_eval(decistmt(template_value),
                        functions=functions)
                except Exception as exc:
                    raise UserError(
                        gettext(
                            'account_financial_statement.msg_wrong_expression',
                            expression=template_value,
                            template=self.template_line.name,
                            traceback=exc,
                            )) from exc
                if isinstance(value, Decimal):
                    value = value.quantize(
                        Decimal(10) ** -self.currency.digits)

        if self.template_line.negate:
            value = -value
        self.value = value
        self.save()
        cache[cache_key] = value
        return value

    def _get_account_values(self, code, mode, invert=False):
        pool = Pool()
        Account = pool.get('account.account')

        company = self.report_period.report.company
        balance_mode = self.template_line.template.mode
        result = Decimal(0)
        values = []
        for account_code in re.findall(r'(-?\w*\(?[0-9a-zA-Z_\.]*\)?)', code):
            if not account_code:
                continue
            if account_code.startswith('-'):
                sign = Decimal('-1.0')
                account_code = account_code[1:]
            else:
                sign = Decimal('1.0')

            if balance_mode == 'credit-debit' and mode != 'balance':
                sign = Decimal('-1.0') * sign
            else:
                if balance_mode == 'debit-credit-reversed':
                    if invert:
                        sign = Decimal('-1.0') * sign
                elif balance_mode == 'credit-debit':
                    sign = Decimal('-1.0') * sign
                elif balance_mode == 'credit-debit-reversed' and not invert:
                    sign = Decimal('-1.0') * sign

            accounts = Account.search([
                    ('company', '=', company),
                    ('code', 'like', account_code + '%'),
                    ('type', '!=', None),
                    ])
            if not accounts:
                continue
            accounts = Account.search([
                    ('parent', 'child_of', [a.id for a in accounts]),
                    ('company', '=', company)
                    ])
            credit_debit = self._get_credit_debit(accounts)
            for account in credit_debit['credit']:
                balance = (credit_debit['debit'][account]
                    - credit_debit['credit'][account])
                value = {'account': account}
                if ((mode == 'debit' and balance > 0.0)
                        or (mode == 'credit' and balance < 0.0)
                        or mode == 'balance'):
                    result += balance * sign
                    value['credit'] = credit_debit['credit'][account]
                    value['debit'] = credit_debit['debit'][account]
                values.append(value)
        return result, values

    def _get_account_(self, code, mode, invert=False):
        pool = Pool()
        LineAccount = pool.get(
            'account.financial.statement.report.line.account.period')
        result, values = self._get_account_values(code, mode, invert=invert)
        detail_lines = []
        for value in values:
            if 'credit' not in value:
                continue
            detail_lines.append({
                    'report_line': self,
                    'account': value['account'],
                    'credit': value['credit'],
                    'debit': value['debit'],
                    })
        if detail_lines:
            LineAccount.create(detail_lines)
        return result

    def _get_credit_debit(self, accounts):
        pool = Pool()
        Account = pool.get('account.account')
        return Account.get_credit_debit(accounts, ['debit', 'credit'])


class ReportLineAccountPeriod(ModelSQL, ModelView):
    'Financial Statement Report Account Period'
    __name__ = 'account.financial.statement.report.line.account.period'

    report_line = fields.Many2One(
        'account.financial.statement.report.line.period', 'Report Line',
        required=True, ondelete='CASCADE', readonly=True)
    company = fields.Function(
        fields.Many2One('company.company', 'Company'),
        'on_change_with_company')
    account = fields.Many2One(
        'account.account', 'Account', required=True,
        domain=[('company', '=', Eval('company', -1))],
        depends=['company'], readonly=True)
    currency = fields.Function(
        fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')
    credit = Monetary('Credit', digits='currency', currency='currency',
        readonly=True)
    debit = Monetary('Debit', digits='currency', currency='currency',
        readonly=True)
    balance = fields.Function(
        Monetary('Balance', digits='currency', currency='currency'),
        'get_balance')

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('report_line')

    @fields.depends('report_line', '_parent_report_line.company')
    def on_change_with_company(self, name=None):
        if self.report_line and self.report_line.company:
            return self.report_line.company.id

    @fields.depends('report_line', '_parent_report_line.currency')
    def on_change_with_currency(self, name=None):
        if self.report_line and self.report_line.currency:
            return self.report_line.currency.id

    def get_balance(self, name):
        if None in (self.debit, self.credit):
            return None
        return self.debit - self.credit


class Template(DeactivableMixin, ModelSQL, ModelView):
    """
    Financial Statement Template
    It stores the header fields of an account report template,
    and the linked lines of detail with the formulas to calculate
    the accounting concepts of the report.
    """
    __name__ = 'account.financial.statement.template'

    name = fields.Char('Name', required=True, translate=True)
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
    One line of detail of the report representing an accounting
    concept with the formulas to calculate its values.
    The accounting concepts follow a parent-children hierarchy.
    """
    __name__ = 'account.financial.statement.template.line'

    template = fields.Many2One('account.financial.statement.template',
        'Template', ondelete='CASCADE')
    sequence = fields.Char('Sequence',
        help='Lines will be sorted/grouped by this field')
    css_class = fields.Selection(CSS_CLASSES, 'CSS Class',
        help='Style-sheet class')
    code = fields.Char('Code', required=True,
        help='Concept code, may be used in formulas to reference this line')
    name = fields.Char('Name', required=True, translate=True,
        help='Concept name/description')
    current_value = fields.Text('Formula', help=_VALUE_FORMULA_HELP)
    negate = fields.Boolean('Negate',
        help='Negate the value (change the sign of the )')
    parent = fields.Many2One('account.financial.statement.template.line',
        'Parent', ondelete='CASCADE', domain=[
            ('template', '=', Eval('template', -1)),
        ])
    children = fields.One2Many('account.financial.statement.template.line',
        'parent', 'Children')
    visible = fields.Boolean('Visible')
    page_break = fields.Boolean('Page Break')

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
    def __register__(cls, module_name):
        super().__register__(module_name)
        table = cls.__table_handler__(module_name)
        if table.column_exist('previous_value'):
            table.drop_column('previous_value')

    @classmethod
    def validate(cls, records):
        super(TemplateLine, cls).validate(records)
        for record in records:
            record.check_syntax()

    def check_syntax(self):
        pool = Pool()
        Translation = pool.get('ir.translation')
        language = Transaction().language

        try:
            parse((self.current_value or '').split(';')[0])
        except SyntaxError:
            field_name = '{},current_value'.format(self.__name__)
            field_string = Translation.get_source(field_name, 'field',
                language)
            raise ValidationError(gettext('account_financial_statement.'
                    'msg_invalid_syntax',
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
