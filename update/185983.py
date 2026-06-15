from sql import Literal, Table
from sql.aggregate import Max


if "pool" not in globals():
    # Prevent pyflakes warnings when the script is not executed by Tryton.
    pool = None
    transaction = None


REPORT_IDS = None
REPLACE_EXISTING = False
COMMIT_EACH_REPORT = False
DRY_RUN = False


Report = pool.get("account.financial.statement.report")
ReportPeriod = pool.get("account.financial.statement.report.period")
NewLine = pool.get("account.financial.statement.report.line.period")
NewDetail = pool.get("account.financial.statement.report.line.account.period")

report = Report.__table__()
report_handler = Report.__table_handler__()
report_period = ReportPeriod.__table__()
new_line = NewLine.__table__()
new_detail = NewDetail.__table__()

current_period_rel = Table("account_financial_statement_current_period_rel")
previous_period_rel = Table("account_financial_statement_previous_period_rel")
legacy_line = Table("account_financial_statement_report_line")
legacy_detail = Table("account_financial_statement_rep_lin_acco")
period = Table("account_period")

cursor = transaction.connection.cursor()
database = transaction.database
table_exist = type(report_handler).table_exist
_next_ids = {}
_manual_tables = set()


def next_id(sql_table):
    table_name = sql_table._name
    current = database.nextid(transaction.connection, table_name)
    if current is not None:
        return current
    if table_name not in _next_ids:
        _manual_tables.add(table_name)
        cursor.execute(*sql_table.select(Max(sql_table.id)))
        row = cursor.fetchone()
        _next_ids[table_name] = (row[0] or 0) + 1
    value = _next_ids[table_name]
    _next_ids[table_name] += 1
    return value


def sync_next_id(sql_table, values):
    if values and sql_table._name in _manual_tables:
        database.setnextid(
            transaction.connection, sql_table._name,
            max(value[0] for value in values) + 1)


def ordered_period_rows(report_id):
    cursor.execute(*report_period.select(
            report_period.id,
            report_period.sequence,
            where=report_period.report == report_id,
            order_by=[
                report_period.sequence.asc.nulls_first,
                report_period.id.asc,
                ]))
    return cursor.fetchall()


def legacy_period_bounds(report_id, fiscalyear_id, relation):
    query = relation.join(period, condition=relation.period == period.id).select(
        period.id,
        period.start_date,
        period.end_date,
        where=(relation.report == report_id)
        & (period.fiscalyear == fiscalyear_id)
        & (period.type == "standard"),
        order_by=[period.start_date.asc, period.end_date.asc, period.id.asc])
    cursor.execute(*query)
    periods = cursor.fetchall()
    if periods:
        return periods[0][0], periods[-1][0]
    return None, None


def ensure_comparison_periods(report_row):
    periods = ordered_period_rows(report_row[0])
    if periods:
        return periods

    to_create = []
    if (report_handler.column_exist("current_fiscalyear")
            and table_exist(current_period_rel._name) and report_row[1]):
        start_period, end_period = legacy_period_bounds(
            report_row[0], report_row[1], current_period_rel)
        values = [
            next_id(report_period),
            report_row[0],
            report_row[1],
            0,
            start_period,
            end_period,
            ]
        to_create.append(values)
    if (report_handler.column_exist("previous_fiscalyear")
            and table_exist(previous_period_rel._name) and report_row[2]):
        start_period, end_period = legacy_period_bounds(
            report_row[0], report_row[2], previous_period_rel)
        values = [
            next_id(report_period),
            report_row[0],
            report_row[2],
            1,
            start_period,
            end_period,
            ]
        to_create.append(values)
    if to_create:
        cursor.execute(*report_period.insert(
                columns=[
                    report_period.id,
                    report_period.report,
                    report_period.fiscalyear,
                    report_period.sequence,
                    report_period.start_period,
                    report_period.end_period,
                    ],
                values=to_create))
        sync_next_id(report_period, to_create)
    return ordered_period_rows(report_row[0])


def delete_existing_lines(report_id):
    line_ids = new_line.join(
        report_period, condition=new_line.report_period == report_period.id
        ).select(new_line.id, where=report_period.report == report_id)
    cursor.execute(*new_detail.delete(
            where=new_detail.report_line.in_(line_ids)))
    cursor.execute(*new_line.delete(
            where=new_line.report_period.in_(
                report_period.select(
                    report_period.id,
                    where=report_period.report == report_id))))


def periods_by_year(report_id):
    periods = ordered_period_rows(report_id)
    return {
        "current": periods[0][0] if len(periods) >= 1 else None,
        "previous": periods[1][0] if len(periods) >= 2 else None,
    }


def legacy_line_rows(report_id):
    cursor.execute(*legacy_line.select(
            legacy_line.id,
            legacy_line.name,
            legacy_line.code,
            legacy_line.notes,
            legacy_line.current_value,
            legacy_line.previous_value,
            legacy_line.template_line,
            legacy_line.parent,
            legacy_line.visible,
            legacy_line.sequence,
            legacy_line.css_class,
            legacy_line.page_break,
            where=legacy_line.report == report_id,
            order_by=[
                legacy_line.sequence.asc,
                legacy_line.code.asc,
                legacy_line.id.asc,
                ]))
    return cursor.fetchall()


def create_new_lines(report_id, target_periods):
    rows = legacy_line_rows(report_id)
    mapping = {}
    values = []
    for row in rows:
        for fiscal_year, period_id, value in [
                ("current", target_periods.get("current"), row[4]),
                ("previous", target_periods.get("previous"), row[5])]:
            if not period_id:
                continue
            line_id = next_id(new_line)
            values.append([
                    line_id,
                    period_id,
                    row[1],
                    row[2],
                    row[3],
                    value,
                    row[6],
                    None,
                    row[8],
                    row[9],
                    row[10],
                    row[11],
                    ])
            mapping[(fiscal_year, row[0])] = line_id
    if values:
        cursor.execute(*new_line.insert(
                columns=[
                    new_line.id,
                    new_line.report_period,
                    new_line.name,
                    new_line.code,
                    new_line.notes,
                    new_line.value,
                    new_line.template_line,
                    new_line.parent,
                    new_line.visible,
                    new_line.sequence,
                    new_line.css_class,
                    new_line.page_break,
                    ],
                values=values))
        sync_next_id(new_line, values)
    return rows, mapping


def attach_parents(legacy_rows, mapping):
    for row in legacy_rows:
        if not row[7]:
            continue
        for fiscal_year in ("current", "previous"):
            line_id = mapping.get((fiscal_year, row[0]))
            parent_id = mapping.get((fiscal_year, row[7]))
            if not line_id or not parent_id:
                continue
            cursor.execute(*new_line.update(
                    columns=[new_line.parent],
                    values=[parent_id],
                    where=new_line.id == line_id))


def copy_details(legacy_rows, mapping):
    values = []
    legacy_ids = [row[0] for row in legacy_rows]
    if not legacy_ids:
        return
    cursor.execute(*legacy_detail.select(
            legacy_detail.report_line,
            legacy_detail.account,
            legacy_detail.credit,
            legacy_detail.debit,
            legacy_detail.fiscal_year,
            where=legacy_detail.report_line.in_(legacy_ids)))
    for report_line_id, account_id, credit, debit, fiscal_year in cursor.fetchall():
        line_id = mapping.get((fiscal_year, report_line_id))
        if not line_id:
            continue
        values.append([
                next_id(new_detail),
                line_id,
                account_id,
                credit,
                debit,
                ])
    if values:
        cursor.execute(*new_detail.insert(
                columns=[
                    new_detail.id,
                    new_detail.report_line,
                    new_detail.account,
                    new_detail.credit,
                    new_detail.debit,
                    ],
                values=values))
        sync_next_id(new_detail, values)


def migrate_report(report_row):
    periods = ensure_comparison_periods(report_row)
    if len(periods) > 2:
        return "skipped_more_than_two_periods"
    if not periods:
        return "skipped_no_target_periods"
    if not table_exist(legacy_line._name):
        return "migrated_periods_only"

    cursor.execute(*legacy_line.select(
            legacy_line.id,
            where=legacy_line.report == report_row[0],
            limit=1))
    if not cursor.fetchone():
        return "migrated_periods_only"

    cursor.execute(*new_line.join(
            report_period, condition=new_line.report_period == report_period.id
            ).select(
                new_line.id,
                where=report_period.report == report_row[0],
                limit=1))
    if cursor.fetchone() and not REPLACE_EXISTING:
        return "skipped_existing_target_lines"
    if REPLACE_EXISTING:
        delete_existing_lines(report_row[0])

    target_period_ids = periods_by_year(report_row[0])
    legacy_rows, mapping = create_new_lines(report_row[0], target_period_ids)
    attach_parents(legacy_rows, mapping)
    if table_exist(legacy_detail._name):
        copy_details(legacy_rows, mapping)
    return "migrated"


report_columns = [report.id]
if report_handler.column_exist("current_fiscalyear"):
    report_columns.append(report.current_fiscalyear)
else:
    report_columns.append(Literal(None))
if report_handler.column_exist("previous_fiscalyear"):
    report_columns.append(report.previous_fiscalyear)
else:
    report_columns.append(Literal(None))

where = None
if REPORT_IDS:
    where = report.id.in_(REPORT_IDS)
cursor.execute(*report.select(
        *report_columns,
        where=where,
        order_by=[report.id.asc]))
reports = cursor.fetchall()

results = {
    "migrated": 0,
    "migrated_periods_only": 0,
    "skipped_no_legacy_lines": 0,
    "skipped_more_than_two_periods": 0,
    "skipped_no_target_periods": 0,
    "skipped_existing_target_lines": 0,
}

for report_row in reports:
    outcome = migrate_report(report_row)
    results.setdefault(outcome, 0)
    results[outcome] += 1
    cursor.execute(*report.select(
            report.name,
            where=report.id == report_row[0]))
    print("%s: %s" % (cursor.fetchone()[0], outcome))
    if not DRY_RUN and COMMIT_EACH_REPORT and outcome == "migrated":
        transaction.commit()

print("Summary:")
for key in sorted(results):
    print("  %s: %s" % (key, results[key]))

if not DRY_RUN:
    transaction.commit()
