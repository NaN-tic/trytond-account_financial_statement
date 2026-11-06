from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

from trytond.modules.html_report.engine import HTMLReportMixin
from trytond.report import Report as TrytonReport
from trytond.model import ModelView, fields
from trytond.pool import Pool
from trytond.pyson import Eval
from trytond.wizard import Button, StateReport, StateView, Wizard
from trytond.transaction import Transaction
from trytond.modules.xgettext import _

from trytond.modules.html_report.tools import save_virtual_workbook

from ..report import Report
from .pdf import FinancialStatementPDF

class PrintStart(ModelView):
    'Print Financial Statement'
    __name__ = 'account.financial.statement.print.start'

    include_details = fields.Boolean('Include Account Details')
    output_format = fields.Selection([
        ('pdf', 'PDF'), ('xlsx', 'Excel')], 'Output Format', required=True)
    has_account_code_digits = fields.Boolean('Account Code Digits Available')
    digits = fields.Integer('Digits', domain=[
        'OR', ('digits', '=', None), ('digits', '>=', 0)],
        states={'invisible': (~Eval('include_details')
            | ~Eval('has_account_code_digits'))},
        help='Group accounts by this number of digits. Zero shows all digits.')

    @staticmethod
    def default_output_format():
        return 'pdf'


class PrintFinancialStatement(Wizard):
    'Print Financial Statement'
    __name__ = 'account.financial.statement.print'

    _pdf_report_action = (
        'account_financial_statement', 'html_report_financial_statement')

    start = StateView('account.financial.statement.print.start',
        'account_financial_statement.print_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Print', 'print_', 'tryton-print', default=True),
            ])
    print_ = StateReport('account.financial.statement.report')

    def default_start(self, fields):
        pool = Pool()
        Configuration = pool.get('account.configuration')
        Statement = pool.get('account.financial.statement.report')
        available = hasattr(Configuration, 'default_account_code_digits')
        defaults = {'has_account_code_digits': available}
        if available:
            statement = Statement(Transaction().context['active_id'])
            with Transaction().set_context(company=statement.company.id):
                defaults['digits'] = Configuration(1).default_account_code_digits
        return defaults

    def do_print_(self, action):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        ActionReport = pool.get('ir.action.report')
        if self.start.output_format == 'xlsx':
            module = 'account_financial_statement'
            fs_id = 'report_xlsx_financial_statement'
        else:
            module, fs_id = self._pdf_report_action
        report = ActionReport(ModelData.get_id(module, fs_id))
        action = report.action.get_action_value()
        available = hasattr(Pool().get('account.configuration'),
            'default_account_code_digits')
        return action, {
            'ids': Transaction().context.get('active_ids', []),
            'model': 'account.financial.statement.report',
            'include_details': self.start.include_details,
            'digits': (self.start.digits
                if self.start.include_details and available else None),
            }


class FinancialStatementBase(HTMLReportMixin, TrytonReport):
    _landscape_threshold = 5
    side_margin = 0.5

    @staticmethod
    def _raw(record):
        return getattr(record, 'raw', record)

    @classmethod
    def _record_id(cls, record):
        return cls._raw(record).id

    @classmethod
    def _display_value(cls, record, field, fallback=None):
        raw_record = cls._raw(record)
        rendered = getattr(record, 'render', None)
        if rendered is not None and hasattr(rendered, field):
            return getattr(rendered, field)
        if hasattr(raw_record, field):
            return getattr(raw_record, field)
        if fallback and hasattr(raw_record, fallback):
            return getattr(raw_record, fallback)
        return ''

    @classmethod
    def _comparison_periods(cls, record):
        return Report._ordered_periods(cls._raw(record))

    @classmethod
    def _period_label(cls, period):
        return cls._display_value(period.fiscalyear, 'name', fallback='rec_name')

    @classmethod
    def _period_header_label(cls, index, period):
        return '%s %s' % (
            _('Period'),
            index,
            )

    @classmethod
    def _period_range(cls, period):
        period_raw = cls._raw(period)
        if period_raw.start_period and period_raw.end_period:
            return '%s - %s' % (
                cls._display_value(period.start_period, 'rec_name', fallback='name'),
                cls._display_value(period.end_period, 'rec_name', fallback='name'),
                )
        return '%s (%s)' % (
            cls._display_value(period.fiscalyear, 'rec_name', fallback='name'),
            _('Full fiscal year'),
            )

    @classmethod
    def _format_amount(cls, value, currency):
        if value in (None, ''):
            return ''
        return cls.format_currency(value, None, currency, symbol=False)

    @classmethod
    def _line_key(cls, line):
        raw_line = cls._raw(line)
        if raw_line.template_line:
            return ('template', cls._record_id(raw_line.template_line))
        return ('code', raw_line.code)

    @classmethod
    def _period_line_lookup(cls, period):
        return {cls._line_key(line): line for line in period.lines}

    @classmethod
    def _structural_lines(cls, record):
        periods = cls._comparison_periods(record)
        if not periods:
            return []
        return list(periods[0].lines)

    @classmethod
    def _line_column_value(cls, line, column):
        period_line = column['lookup'].get(cls._line_key(line))
        if not period_line:
            return ''
        currency = cls._raw(period_line.currency) if period_line.currency else None
        return cls._format_amount(cls._raw(period_line).value, currency)

    @classmethod
    def _detail_rows(cls, line, record, columns, digits=None):
        by_account = {}
        for column in columns:
            period_line = column['lookup'].get(cls._line_key(line))
            if not period_line:
                continue
            for value in period_line.line_accounts:
                amount = cls._raw(value).balance or Decimal(0)
                account = cls._raw(value.account)
                code = account.code or ''
                key = code[:digits] if digits else account.id
                name_account = account
                if digits:
                    while (name_account.parent
                            and len(name_account.code or '') > digits):
                        name_account = name_account.parent
                entry = by_account.setdefault(key, {
                    'label': '%s - %s' % (
                        code[:digits] if digits else code, name_account.name),
                    'values': {},
                    })
                entry['values'][column['id']] = (
                    entry['values'].get(column['id'], Decimal(0)) + amount)
        rows = [entry for entry in by_account.values()
            if any(entry['values'].values())]
        rows.sort(key=lambda item: item['label'])
        return rows

    @classmethod
    def _table_columns(cls, record):
        return [{
                'id': cls._record_id(period),
                'label': cls._period_range(period),
                'period': period,
                'lookup': cls._period_line_lookup(period),
                }
            for period in cls._comparison_periods(record)]

    @classmethod
    def _summary_lines(cls, record):
        return [line for line in cls._structural_lines(record)
            if cls._raw(line).visible]

    @classmethod
    def _line_numeric_value(cls, line, column):
        period_line = column['lookup'].get(cls._line_key(line))
        if not period_line:
            return None
        return cls._raw(period_line).value

class FinancialStatementExport(FinancialStatementBase):
    __name__ = 'account.financial.statement.export'
    _number_format = '#,##0.00'

    @classmethod
    def execute(cls, ids, data):
        if not ids:
            return
        action, model = cls.get_action(data)
        cls.check_access(action, model, ids)
        records = cls._get_records(ids, model, data)
        workbook = Workbook()
        workbook.remove(workbook.active)
        for record in records:
            cls._add_sheet(workbook, record, data)
        name = records[0].rec_name if len(records) == 1 else action.name
        return ('xlsx', save_virtual_workbook(workbook), False, name)

    @classmethod
    def _sheet_title(cls, record):
        name = cls._display_value(record, 'name', fallback='rec_name') or 'Report'
        return name.replace('/', '_').replace(':', '_')[:31]

    @classmethod
    def _add_sheet(cls, workbook, record, data=None):
        data = data or {}
        sheet = workbook.create_sheet(cls._sheet_title(record))
        columns = cls._table_columns(record)
        headers = [_('Name')] + [
            cls._period_range(column['period'])
            or column['label']
            for column in columns]
        title = cls._display_value(record, 'name', fallback='rec_name') or 'Report'
        border_side = Side(style='thin')

        sheet.append([title])
        if len(headers) > 1:
            sheet.merge_cells(start_row=1, start_column=1,
                end_row=1, end_column=len(headers))
        for column_index in range(1, len(headers) + 1):
            cell = sheet.cell(1, column_index)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
            cell.border = Border(
                top=border_side,
                bottom=border_side,
                left=border_side if column_index == 1 else None,
                right=border_side if column_index == len(headers) else None,
                )

        sheet.append(headers)
        for cell in sheet[2]:
            cell.font = Font(bold=True)
            cell.border = Border(
                top=border_side,
                bottom=border_side,
                left=border_side,
                right=border_side,
                )

        for line in cls._summary_lines(record):
            row = [cls._display_value(line, 'name', fallback='rec_name')]
            row.extend(cls._line_numeric_value(line, column) for column in columns)
            sheet.append(row)
            row_index = sheet.max_row
            for column_index in range(2, len(headers) + 1):
                cell = sheet.cell(row_index, column_index)
                if cell.value is not None:
                    cell.number_format = cls._number_format

            if data.get('include_details'):
                for detail in cls._detail_rows(
                        line, record, columns, data.get('digits')):
                    sheet.append([detail['label']] + [
                        detail['values'].get(column['id'], Decimal(0))
                        for column in columns])
                    for cell in sheet[sheet.max_row]:
                        cell.font = Font(color='A2A2A2')
                        if cell.column > 1:
                            cell.number_format = cls._number_format

        widths = {1: 42}
        for index in range(2, len(headers) + 1):
            widths[index] = 18
        for index, width in widths.items():
            sheet.column_dimensions[get_column_letter(index)].width = width

class FinancialStatementReport(FinancialStatementBase):
    'Financial Statement Report'
    __name__ = 'account.financial.statement.report'

    _include_details = False

    @classmethod
    def execute(cls, ids, data):
        if not ids:
            return
        action, model = cls.get_action(data)
        cls.check_access(action, model, ids)
        records = cls._get_records(ids, model, data)
        margin = action.html_side_margin
        margin = (cls.side_margin if margin is None else margin) * 10
        pdf = FinancialStatementPDF(margin)
        for record in records:
            columns = cls._table_columns(record)
            orientation = ('L' if len(columns) > cls._landscape_threshold
                else 'P')
            identifier = record.company.party.tax_identifier
            pdf.heading = '%s - %s' % (record.company.rec_name, record.rec_name)
            pdf.tax_identifier = 'NIF: %s' % (identifier.code if identifier else '-')
            pdf.columns = [_('Concept')] + [column['label'] for column in columns]
            pdf.add_page(orientation=orientation)
            lines = cls._summary_lines(record)
            for index, line in enumerate(lines):
                pdf.row([cls._display_value(line, 'name', fallback='rec_name')]
                    + [cls._line_column_value(line, column) for column in columns],
                    bold=not line.parent)
                if data.get('include_details', cls._include_details):
                    for detail in cls._detail_rows(
                            line, record, columns, data.get('digits')):
                        pdf.row([detail['label']] + [cls._format_amount(
                            detail['values'].get(column['id'], Decimal(0)),
                            cls._raw(line.currency)) for column in columns],
                            detail=True)
                if line.page_break and index < len(lines) - 1:
                    pdf.add_page(orientation=orientation)
        content = bytes(pdf.output())
        if action.html_copies and action.html_copies > 1:
            content = cls.merge_pdfs([content] * action.html_copies)
        name = records[0].rec_name if len(records) == 1 else action.name
        try:
            Printer = Pool().get('printer')
        except KeyError:
            Printer = None
        if Printer:
            return Printer.send_report('pdf', content, name, action)
        return 'pdf', content, cls.get_direct_print(action), name


class FinancialStatementDetailReport(FinancialStatementReport):
    'Financial Statement Detail Report'
    __name__ = 'account.financial.statement.detail.report'
    _include_details = True
