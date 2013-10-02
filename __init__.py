# This file is part of account_financial_statement module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from trytond.pool import Pool
from .report import *


def register():
    Pool.register(
        Template,
        TemplateLine,
        Report,
        ReportLine,
        ReportLineAccount,
        ReportCurrentPeriods,
        ReportPreviousPeriods,
        module='account_financial_statement', type_='model')
