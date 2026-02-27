from trytond.pool import Pool
from . import financial_statement


def register(module):
    Pool.register(
        financial_statement.FinancialStatementReport,
        financial_statement.FinancialStatementDetailReport,
        module=module, type_='report')
