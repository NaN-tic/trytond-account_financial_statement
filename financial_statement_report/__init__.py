from trytond.pool import Pool
from . import financial_statement


def register(module):
    Pool.register(
        financial_statement.FinancialStatementReport,
        module=module, type_='report')
