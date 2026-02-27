from trytond.pool import PoolMeta
from trytond.modules.html_report.dominate_report import DominateReport
from dominate.util import raw
from dominate.tags import header as header_tag, table, thead, tbody, tr, td, th


class FinancialStatementBase(DominateReport):

    @classmethod
    def header(cls, action, data, records):
        record, = records
        header_node = header_tag(id='header')
        with header_node:
            with table(style='width:100%;'):
                with tr():
                    with td():
                        raw('<h2><i>%s</i></h2>' % record.company.render.rec_name)
                        raw('<h3>NIF: %s</h3>' % (
                            record.company.party.tax_identifier
                            and record.company.party.tax_identifier.render.code
                            or '-'))
                    with td():
                        raw('<h1>%s</h1>' % record.render.rec_name)
                with tr():
                    label_current = cls.label(
                        'account.financial.statement.report',
                        'current_fiscalyear')
                    current_line = '%s %s: %s / %s' % (
                        label_current,
                        record.current_fiscalyear.render.name,
                        record.render.current_periods_start_date
                            if record.raw.current_periods_start_date else '',
                        record.render.current_periods_end_date
                            if record.raw.current_periods_end_date else '')
                    td(current_line, colspan='2')
                if (record.raw.previous_fiscalyear
                        and record.raw.previous_periods_start_date
                        and record.raw.previous_periods_start_date):
                    label_previous = cls.label(
                        'account.financial.statement.report',
                        'previous_fiscalyear')
                    previous_line = '%s %s: %s / %s' % (
                        label_previous,
                        record.previous_fiscalyear.render.name,
                        record.render.previous_periods_start_date
                            if record.raw.previous_periods_start_date else '',
                        record.render.previous_periods_end_date
                            if record.raw.previous_periods_end_date else '')
                    td(previous_line, colspan='2')
        return header_node

    @classmethod
    def title(cls, action, data, records):
        record, = records
        return record.render.rec_name

    @classmethod
    def _build_table(cls, record, include_details):
        with table(style='page-break-inside: auto;') as table_node:
            with thead(style='border-bottom: 1px solid black; border-top: 1px solid black'):
                with tr(style='page-break-inside:avoid;'):
                    th('Concept', nowrap=True)
                    th('%s %s' % (
                        cls.label(
                            'account.financial.statement.report',
                            'current_fiscalyear'),
                        record.current_fiscalyear.render.name),
                        nowrap=True)
                    if record.raw.previous_fiscalyear:
                        th('%s %s' % (
                            cls.label(
                                'account.financial.statement.report',
                                'previous_fiscalyear'),
                            record.previous_fiscalyear.render.name),
                            nowrap=True)
            with tbody():
                for line in record.lines:
                    if not line.raw.visible:
                        continue
                    line_style = 'page-break-inside:avoid;'
                    if line.raw.page_break:
                        line_style += ' page-break-after:always;'
                    with tr(style=line_style):
                        if not line.raw.parent:
                            th(line.render.name)
                        else:
                            td(line.render.name)
                        td(line.render.current_value, style='text-align: right')
                        if record.raw.previous_fiscalyear:
                            td(line.render.previous_value, style='text-align: right')
                    if include_details:
                        previous_by_code = {}
                        for previous in line.previous_line_accounts:
                            previous_by_code[previous.account.raw.code] = previous
                        for current in line.current_line_accounts:
                            previous = previous_by_code.get(current.account.raw.code)
                            current_value = ((current.raw.debit or 0)
                                - (current.raw.credit or 0))
                            previous_value = None
                            if previous:
                                previous_value = ((previous.raw.debit or 0)
                                    - (previous.raw.credit or 0))
                            if (current_value != 0
                                    or (record.raw.previous_fiscalyear
                                        and previous_value is not None
                                        and previous_value != 0)):
                                detail_style = (
                                    'page-break-inside:avoid; color: #A2A2A2;')
                                if line.raw.page_break:
                                    detail_style += ' page-break-after:always;'
                                with tr(style=detail_style):
                                    td('%s - %s' % (
                                        current.account.render.code,
                                        current.account.render.name))
                                    td(current_value, style='text-align: right')
                                    if record.raw.previous_fiscalyear:
                                        td(previous_value if previous else '',
                                            style='text-align: right')
                        if record.raw.previous_fiscalyear:
                            for previous in line.previous_line_accounts:
                                current = None
                                for current_line in line.current_line_accounts:
                                    if (current_line.account.raw.code
                                            == previous.account.raw.code):
                                        current = current_line
                                        break
                                previous_value = ((previous.raw.debit or 0)
                                    - (previous.raw.credit or 0))
                                if (not current and previous_value != 0):
                                    detail_style = (
                                        'page-break-inside:avoid; color: #A2A2A2;')
                                    if line.raw.page_break:
                                        detail_style += ' page-break-after:always;'
                                    with tr(style=detail_style):
                                        td('%s - %s' % (
                                            previous.account.render.code,
                                            previous.account.render.name))
                                        td('')
                                        td(previous_value, style='text-align: right')
        return table_node


class FinancialStatementReport(FinancialStatementBase, metaclass=PoolMeta):
    'Financial Statement Report'
    __name__ = 'account.financial.statement.report'

    @classmethod
    def body(cls, action, data, records):
        record, = records
        return cls._build_table(record, include_details=False)


class FinancialStatementDetailReport(FinancialStatementBase, metaclass=PoolMeta):
    'Financial Statement Detail Report'
    __name__ = 'account.financial.statement.detail.report'

    @classmethod
    def body(cls, action, data, records):
        record, = records
        return cls._build_table(record, include_details=True)
