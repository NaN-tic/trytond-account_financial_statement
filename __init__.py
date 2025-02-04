# This file is part of account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from . import report
from . import financial_statement_report


def register():
    Pool.register(
        report.Template,
        report.TemplateLine,
        report.Report,
        report.ReportLine,
        report.ReportLineAccount,
        report.ReportLineDetailStart,
        report.ReportCurrentPeriods,
        report.ReportPreviousPeriods,
        report.ViewAccountsStart,
        module='account_financial_statement', type_='model')
    Pool.register(
        report.ReportLineDetail,
        module='account_financial_statement', type_='wizard')

    financial_statement_report.register('account_financial_statement')
