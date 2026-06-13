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
from trytond.modules.currency.fields import Monetary
from trytond.pool import Pool
from trytond.pyson import Bool, Eval, PYSONEncoder
from trytond.tools import decistmt
from trytond.transaction import Transaction
from trytond.wizard import (
    Button,
    StateAction,
    StateTransition,
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
    current_fiscalyear = fields.Many2One('account.fiscalyear', 'Fiscal year 1',
        states=_STATES, domain=[
            ('company', '=', Eval('company', -1)),
            ])
    current_periods = fields.Many2Many(
        'account_financial_statement-account_period_current', 'report',
        'period', 'Fiscal year 1 periods', states=_STATES, domain=[
            ('fiscalyear', '=', Eval('current_fiscalyear')),
            ])
    current_periods_list = fields.Function(fields.Char('Current Periods List'),
        'get_periods')
    current_periods_start_date = fields.Function(
        fields.Char('Current Periods Dates'), 'get_dates')
    current_periods_end_date = fields.Function(
        fields.Char('Current Periods Dates'), 'get_dates')
    previous_fiscalyear = fields.Many2One('account.fiscalyear',
        'Fiscal year 2', states=_STATES, domain=[
            ('company', '=', Eval('company', -1)),
            ])
    previous_periods = fields.Many2Many(
        'account_financial_statement-account_period_previous', 'report',
        'period', 'Fiscal year 2 periods', states=_STATES, domain=[
            ('fiscalyear', '=', Eval('previous_fiscalyear')),
            ])
    previous_periods_list = fields.Function(
        fields.Char('Previous Periods List'), 'get_periods')
    previous_periods_start_date = fields.Function(
        fields.Char('Previous Periods Dates'), 'get_dates')
    previous_periods_end_date = fields.Function(
        fields.Char('Previous Periods Dates'), 'get_dates')
    comparison_fiscalyears = fields.Function(
        fields.Char('Fiscal Years'), 'get_comparison_fiscalyears')
    comparison_periods = fields.One2Many(
        'account.financial.statement.report.period', 'report',
        'Comparison Periods', states=_STATES,
        order=[('sequence', 'ASC'), ('id', 'ASC')])
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
                    'icon': 'tryton-forward',
                    },
                'draft': {
                    'invisible': Eval('state') != 'calculated',
                    'icon': 'tryton-back',
                    },
                })

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
            if len(report.comparison_periods) > 20:
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
        default.setdefault('lines', None)
        default.setdefault('calculation_date', None)
        return super(Report, cls).copy(reports, default=default)

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
    def get_comparison_fiscalyears(cls, reports, name):
        values = {}
        for report in reports:
            periods = sorted(report.comparison_periods,
                key=lambda p: (
                    p.fiscalyear.start_date if p.fiscalyear else datetime.min.date(),
                    p.fiscalyear.end_date if p.fiscalyear else datetime.min.date(),
                    p.fiscalyear.rec_name if p.fiscalyear else '',
                    p.id or 0))
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
    def _legacy_period_values(cls, periods):
        periods = sorted([period for period in periods if period.type == 'standard'],
            key=lambda p: (p.start_date, p.end_date, p.id))
        values = {}
        if periods:
            values['start_period'] = periods[0].id
            values['end_period'] = periods[-1].id
        return values

    @classmethod
    def ensure_comparison_periods(cls, report):
        periods = cls._ordered_periods(report)
        if periods:
            return periods

        ReportPeriod = Pool().get('account.financial.statement.report.period')
        to_create = []
        if report.current_fiscalyear:
            values = {
                'report': report.id,
                'fiscalyear': report.current_fiscalyear.id,
                'sequence': 0,
                }
            values.update(cls._legacy_period_values(report.current_periods))
            to_create.append(values)
        if report.previous_fiscalyear:
            values = {
                'report': report.id,
                'fiscalyear': report.previous_fiscalyear.id,
                'sequence': 1,
                }
            values.update(cls._legacy_period_values(report.previous_periods))
            to_create.append(values)
        if to_create:
            ReportPeriod.create(to_create)
            report = cls(report.id)
        return cls._ordered_periods(report)

    @classmethod
    def _get_date_period_data(cls, report):
        periods = cls._ordered_periods(report)
        return {
            'current_periods': (
                periods[0].get_periods() if len(periods) >= 1 else [],
                periods[0].fiscalyear if len(periods) >= 1 else None,
                ),
            'previous_periods': (
                periods[1].get_periods() if len(periods) >= 2 else [],
                periods[1].fiscalyear if len(periods) >= 2 else None,
                ),
            }

    @classmethod
    def get_dates(cls, reports, names):
        result = {}
        for report in reports:
            period_data = cls._get_date_period_data(report)
            if 'current_periods_start_date' in names:
                periods, fiscalyear = period_data['current_periods']
                if periods:
                    start = min(p.start_date for p in periods)
                elif fiscalyear:
                    start = fiscalyear.start_date
                else:
                    start = None
                result.setdefault('current_periods_start_date',
                    {})[report.id] = (datetime.combine(start,
                        datetime.min.time()) if start else None)
            if 'current_periods_end_date' in names:
                periods, fiscalyear = period_data['current_periods']
                if periods:
                    end = max(p.end_date for p in periods)
                elif fiscalyear:
                    end = fiscalyear.end_date
                else:
                    end = None
                result.setdefault('current_periods_end_date',
                    {})[report.id] = (datetime.combine(end,
                        datetime.min.time()) if end else None)
            if 'previous_periods_start_date' in names:
                periods, fiscalyear = period_data['previous_periods']
                if periods:
                    start = min(p.start_date for p in periods)
                elif fiscalyear:
                    start = fiscalyear.start_date
                else:
                    start = None
                result.setdefault('previous_periods_start_date',
                    {})[report.id] = (datetime.combine(start,
                        datetime.min.time()) if start else None)
            if 'previous_periods_end_date' in names:
                periods, fiscalyear = period_data['previous_periods']
                if periods:
                    end = max(p.end_date for p in periods)
                elif fiscalyear:
                    end = fiscalyear.end_date
                else:
                    end = None
                result.setdefault('previous_periods_end_date',
                    {})[report.id] = (datetime.combine(end,
                        datetime.min.time()) if end else None)
        return result

    @classmethod
    @ModelView.button
    @Workflow.transition('calculated')
    def calculate(cls, reports):
        pool = Pool()
        ReportLinePeriod = pool.get('account.financial.statement.report.line.period')
        TemplateLine = pool.get('account.financial.statement.template.line')

        for report in reports:
            periods = cls.ensure_comparison_periods(report)
            if not periods:
                raise UserError(
                    gettext(
                        'account_financial_statement.'
                        'msg_financial_statement_missing_periods'))

            existing_lines = ReportLinePeriod.search([
                    ('report_period', 'in', [period.id for period in periods]),
                    ], order=[])
            if existing_lines:
                ReportLinePeriod.delete(existing_lines)

            report.calculation_date = datetime.now()
            report.save()

            template_lines = TemplateLine.search([
                    ('template', '=', report.template),
                    ('parent', '=', None),
                    ])
            for index, report_period in enumerate(periods):
                formula_field = 'current_value' if index == 0 else 'previous_value'
                for template_line in template_lines:
                    ReportLinePeriod.create_from_template(report_period,
                        template_line, formula_field)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, reports):
        pool = Pool()
        ReportLinePeriod = pool.get('account.financial.statement.report.line.period')

        for report in reports:
            periods = cls.ensure_comparison_periods(report)
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
            return '%s: %s - %s' % (self.fiscalyear.rec_name,
                self.start_period.rec_name, self.end_period.rec_name)
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
        if not used:
            for line in self.record.lines:
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


class ReportCurrentPeriods(ModelSQL):
    'Financial Statement Report - Current Periods'
    __name__ = 'account_financial_statement-account_period_current'
    _table = 'account_financial_statement_current_period_rel'
    report = fields.Many2One('account.financial.statement.report',
        'Account Report', ondelete='CASCADE', required=True)
    period = fields.Many2One('account.period', 'Period',
        ondelete='CASCADE', required=True)


class ReportPreviousPeriods(ModelSQL):
    'Financial Statement Report - Previous Periods'
    __name__ = 'account_financial_statement-account_period_previous'
    _table = 'account_financial_statement_previous_period_rel'
    report = fields.Many2One('account.financial.statement.report',
        'Account Report', ondelete='CASCADE', required=True)
    period = fields.Many2One('account.period', 'Period',
        ondelete='CASCADE', required=True)


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

    name = fields.Char('Name', required=True, states=_states)
    report = fields.Many2One('account.financial.statement.report', 'Report',
        required=True, ondelete='CASCADE',
        states={
            'readonly': _states['readonly'] & Bool(Eval('report')),
            })
    code = fields.Char('Code', required=True, states=_states)
    notes = fields.Text('Notes')
    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')
    current_value = Monetary('Current Value',
        digits='currency', currency='currency')
    previous_value = Monetary('Previous value',
        digits='currency', currency='currency')
    calculation_date = fields.DateTime('Calculation date', readonly=True)
    template_line = fields.Many2One('account.financial.statement.template.line',
        'Line template', ondelete='SET NULL')
    parent = fields.Many2One('account.financial.statement.report.line',
        'Parent', ondelete='CASCADE',
        domain=[
            ('report', '=', Eval('report')),
            ],
        states=_states)
    children = fields.One2Many('account.financial.statement.report.line',
        'parent', 'Children',
        domain=[
            ('report', '=', Eval('report')),
            ],
        states=_states)
    visible = fields.Boolean('Visible')
    sequence = fields.Char('Sequence', states=_states)
    css_class = fields.Selection(CSS_CLASSES, 'CSS Class', states=_states)
    line_accounts = fields.One2Many(
        'account.financial.statement.report.line.account',
        'report_line', 'Line Accounts', states=_states)
    current_line_accounts = fields.Function(fields.Many2Many(
            'account.financial.statement.report.line.account', None, None,
            'Current Detail', states=_states), 'get_line_accounts')
    previous_line_accounts = fields.Function(fields.Many2Many(
            'account.financial.statement.report.line.account', None, None,
            'Previous Detail', states=_states), 'get_line_accounts')
    report_state = fields.Function(fields.Selection(STATES, 'Report State'),
        'on_change_with_report_state')
    page_break = fields.Boolean('Page Break')

    @fields.depends('report', '_parent_report.company')
    def on_change_with_currency(self, name=None):
        if self.report and self.report.company:
            return self.report.company.currency.id

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
        super().__setup__()
        cls.__access__.add('report')
        cls._order.insert(0, ('sequence', 'ASC'))
        cls._order.insert(1, ('code', 'ASC'))
        t = cls.__table__()
        cls._sql_constraints += [
            ('report_code_uniq', Unique(t, t.report, t.code),
                'account_financial_statement.msg_code_unique_per_report'),
            ]
        cls._buttons.update({
                'open_details': {},
                })

    @fields.depends('_parent_report.id', 'report')
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
            lines = self.search([
                    ('report', '=', self.report.id),
                    ('code', '=', concept),
                    ])
            for child in lines:
                if child.calculation_date != child.report.calculation_date:
                    child.refresh_values()
                result += getattr(child, value) * sign
        return result

    def percent(self, value, *concepts):
        result = 0
        if len(concepts) != 2:
            return result
        divisior = self.search([
                ('report', '=', self.report.id),
                ('code', '=', concepts[0]),
                ])
        dividend = self.search([
                ('report', '=', self.report.id),
                ('code', '=', concepts[1]),
                ])
        if divisior and dividend:
            divisior[0].refresh_values()
            dividend[0].refresh_values()
            if getattr(divisior[0], value) == 0:
                return result
            result = getattr(divisior[0], value) / getattr(dividend[0], value)
        return result

    def refresh_values(self):
        for child in self.children:
            child.refresh_values()
        for fyear in ('current', 'previous'):
            value = 0
            getvalue = '%s_value' % (fyear)
            template_value = getattr(self.template_line, getvalue)
            if template_value and len(template_value):
                template_value = template_value.split(';')[0]
            getfiscalyear = '%s_fiscalyear' % (fyear)
            if not getattr(self.report, getfiscalyear):
                value = 0
            elif not template_value or not len(template_value):
                for child in self.children:
                    if child.calculation_date != child.report.calculation_date:
                        child.refresh_values()
                    value += getattr(child, getvalue)
            else:
                getperiods = '%s_periods' % (fyear)
                ctx = {
                    'fiscalyear': getattr(self.report, getfiscalyear).id,
                    'periods': [p.id for p in getattr(self.report, getperiods)],
                    'period': fyear,
                    'cumulate': self.template_line.template.cumulate,
                    }
                with Transaction().set_context(ctx):
                    functions = {
                        'balance': self.balance,
                        'invert': self.invert,
                        'debit': self.debit,
                        'credit': self.credit,
                        'concept': partial(self.concept, getvalue),
                        'Decimal': Decimal,
                        'percent': partial(self.percent, getvalue),
                        }
                    try:
                        value = simple_eval(decistmt(template_value),
                            functions=functions)
                    except Exception as e:
                        raise UserError(gettext('account_financial_statement.'
                                'msg_wrong_expression',
                                expression=template_value,
                                template=self.template_line.name,
                                traceback=e,
                            ))
                    if isinstance(value, Decimal):
                        value = value.quantize(
                            Decimal(10) ** -self.currency.digits)
            if self.template_line.negate:
                value = -value
            setattr(self, getvalue, value)
        self.calculation_date = self.report.calculation_date
        self.save()

    def _get_account_values(self, code, mode, invert=False):
        context = Transaction().context
        pool = Pool()
        Account = pool.get('account.account')

        company = self.report.company
        balance_mode = self.template_line.template.mode
        res = Decimal(0)
        vlist = []
        for account_code in re.findall(r'(-?\w*\(?[0-9a-zA-Z_\.]*\)?)', code):
            if len(account_code) > 0:
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
                    elif balance_mode == 'credit-debit-reversed':
                        if not invert:
                            sign = Decimal('-1.0') * sign

                accounts = Account.search([
                        ('company', '=', company),
                        ('code', 'like', account_code + '%'),
                        ('type', '!=', None),
                        ])
                if accounts:
                    accounts = Account.search([
                            ('parent', 'child_of', [a.id for a in accounts]),
                            ('company', '=', company)
                            ])
                    credit_debit = self._get_credit_debit(accounts)
                    for account in credit_debit['credit']:
                        balance = (credit_debit['debit'][account]
                            - credit_debit['credit'][account])
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
                        vlist.append(value)
        return res, vlist

    def _get_account_(self, code, mode, invert=False):
        pool = Pool()
        ReportLineAccount = pool.get(
            'account.financial.statement.report.line.account')
        res, vlist = self._get_account_values(code, mode, invert=invert)
        ReportLineAccount.create(vlist)
        return res

    def _get_credit_debit(self, accounts):
        pool = Pool()
        Account = pool.get('account.account')
        return Account.get_credit_debit(accounts, ['debit', 'credit'])

    @classmethod
    @ModelView.button_action('account_financial_statement.act_open_detail')
    def open_details(cls, lines):
        pass


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

    @classmethod
    def __register__(cls, module_name):
        super().__register__(module_name)
        table = cls.__table_handler__(module_name)
        for name, kind in [
                ('name', 'VARCHAR'),
                ('code', 'VARCHAR'),
                ('notes', 'TEXT'),
                ('template_line', 'INTEGER'),
                ('parent', 'INTEGER'),
                ('visible', 'BOOLEAN'),
                ('sequence', 'VARCHAR'),
                ('css_class', 'VARCHAR'),
                ('page_break', 'BOOLEAN'),
                ]:
            if not table.column_exist(name):
                table.add_column(name, kind)

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
    def create_from_template(cls, report_period, template_line, formula_field,
            parent=None, cache=None):
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
            cls.create_from_template(report_period, child, formula_field,
                parent=line, cache=cache)
        line.refresh_value(formula_field, cache)
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
                    ('report_period', '=', self.report_period.id),
                    ('code', '=', concept),
                    ])
            for line in lines:
                result += line.refresh_value(None, cache=cache) * sign
        return result

    def _percent_value(self, cache, *concepts):
        if len(concepts) != 2:
            return Decimal(0)
        divisor_lines = self.search([
                ('report_period', '=', self.report_period.id),
                ('code', '=', str(concepts[0])),
                ], limit=1)
        dividend_lines = self.search([
                ('report_period', '=', self.report_period.id),
                ('code', '=', str(concepts[1])),
                ], limit=1)
        if not divisor_lines or not dividend_lines:
            return Decimal(0)
        divisor_value = divisor_lines[0].refresh_value(None, cache=cache)
        if divisor_value == 0:
            return Decimal(0)
        dividend_value = dividend_lines[0].refresh_value(None, cache=cache)
        return divisor_value / dividend_value

    def refresh_value(self, formula_field=None, cache=None):
        if cache is None:
            cache = {}
        cache_key = self.id
        if cache_key in cache:
            return cache[cache_key]

        if formula_field is None:
            formula_field = 'current_value'
            periods = Report._ordered_periods(self.report_period.report)
            if periods:
                first_period = periods[0]
                if self.report_period.id != first_period.id:
                    formula_field = 'previous_value'

        value = Decimal(0)
        template_value = getattr(self.template_line, formula_field)
        if template_value:
            template_value = template_value.split(';', 1)[0]

        if not self.report_period.fiscalyear:
            value = Decimal(0)
        elif not template_value:
            value = sum(child.refresh_value(formula_field, cache=cache)
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
                    'report_line': self.id,
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


class ReportLineAccount(ModelSQL, ModelView):
    'Financial Statement Report Account'
    __name__ = 'account.financial.statement.report.line.account'
    _table = 'account_financial_statement_rep_lin_acco'
    report_line = fields.Many2One('account.financial.statement.report.line',
        'Report Line', ondelete='CASCADE', required=True)
    company = fields.Function(fields.Many2One('company.company', 'Company'),
        'on_change_with_company')
    account = fields.Many2One('account.account', 'Account', required=True, domain=[
            ('company', '=', Eval('company', -1)),
            ])
    currency = fields.Function(fields.Many2One('currency.currency', 'Currency'),
        'on_change_with_currency')
    credit = Monetary('Credit', digits='currency', currency='currency')
    debit = Monetary('Debit', digits='currency', currency='currency')
    balance = fields.Function(Monetary('Balance',
        digits='currency', currency='currency'), 'get_balance')
    fiscal_year = fields.Selection([
            ('current', 'Current'),
            ('previous', 'Previous'),
        ], 'Fiscal Year')

    @fields.depends('report_line', '_parent_report_line.id')
    def on_change_with_company(self, name=None):
        if (self.report_line and self.report_line.report
                and self.report_line.report.company):
            return self.report_line.report.company.id

    @classmethod
    def __setup__(cls):
        super().__setup__()
        cls.__access__.add('report_line')

    @fields.depends('report_line', '_parent_report_line.currency')
    def on_change_with_currency(self, name=None):
        if self.report_line and self.report_line.currency:
            return self.report_line.currency.id

    def get_balance(self, name):
        if None in (self.debit, self.credit):
            return
        if self.report_line.report.template.mode[0:5] == 'debit':
            return self.debit - self.credit
        else:
            return self.credit - self.debit


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
            Button('Open', 'select', 'tryton-forward', default=True),
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
    current_value = fields.Text('First fiscal year formula',
        help=_VALUE_FORMULA_HELP)
    previous_value = fields.Text('Remaining fiscal years formula',
        help=_VALUE_FORMULA_HELP)
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
                field_name = '{},{}'.format(self.__name__, value)
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
            page_break=self.page_break,
            )

    def create_report_line(self, report, template2line=None, parent=None):
        if template2line is None:
            template2line = {}

        if self.id not in template2line:
            line = self._get_line()
            line.parent = parent
            line.report = report
            line.save()
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
