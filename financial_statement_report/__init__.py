from trytond.pool import Pool
from . import financial_statement


def register(module):
    Pool.register(
        financial_statement.PrintStart,
        module=module, type_='model')
    Pool.register(
        financial_statement.PrintFinancialStatement,
        module=module, type_='wizard')
    Pool.register(
        financial_statement.FinancialStatementExport,
        financial_statement.FinancialStatementReport,
        module=module, type_='report')
