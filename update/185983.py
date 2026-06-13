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
LegacyLine = pool.get("account.financial.statement.report.line")
NewLine = pool.get("account.financial.statement.report.line.period")
NewDetail = pool.get("account.financial.statement.report.line.account.period")


def ordered_periods(report):
    return sorted(
        report.comparison_periods,
        key=lambda period: (
            period.sequence if period.sequence is not None else 0,
            period.id or 0,
        ),
    )


def period_values(legacy_periods):
    periods = sorted(
        [period for period in legacy_periods if period.type == "standard"],
        key=lambda p: (p.start_date, p.end_date, p.id),
    )
    values = {}
    if periods:
        values["start_period"] = periods[0].id
        values["end_period"] = periods[-1].id
    return values


def ensure_comparison_periods(report):
    periods = ordered_periods(report)
    if periods:
        return periods

    to_create = []
    if report.current_fiscalyear:
        values = {
            "report": report.id,
            "fiscalyear": report.current_fiscalyear.id,
            "sequence": 0,
        }
        values.update(period_values(report.current_periods))
        to_create.append(values)
    if report.previous_fiscalyear:
        values = {
            "report": report.id,
            "fiscalyear": report.previous_fiscalyear.id,
            "sequence": 1,
        }
        values.update(period_values(report.previous_periods))
        to_create.append(values)
    if to_create:
        ReportPeriod.create(to_create)
    return ordered_periods(Report(report.id))


def delete_existing_lines(report):
    lines = NewLine.search(
        [("report_period.report", "=", report.id)],
        order=[],
    )
    if lines:
        NewLine.delete(lines)


def target_periods(report):
    periods = ordered_periods(report)
    return {
        "current": periods[0] if len(periods) >= 1 else None,
        "previous": periods[1] if len(periods) >= 2 else None,
    }


def value_for_period(legacy_line, fiscal_year):
    if fiscal_year == "current":
        return legacy_line.current_value
    return legacy_line.previous_value


def create_new_lines(report, periods_by_year):
    legacy_lines = LegacyLine.search(
        [("report", "=", report.id)],
        order=[("sequence", "ASC"), ("code", "ASC"), ("id", "ASC")],
    )
    mapping = {}
    for legacy_line in legacy_lines:
        for fiscal_year in ("current", "previous"):
            report_period = periods_by_year.get(fiscal_year)
            if not report_period:
                continue
            line = NewLine(
                report_period=report_period,
                name=legacy_line.name,
                code=legacy_line.code,
                notes=legacy_line.notes,
                value=value_for_period(legacy_line, fiscal_year),
                template_line=legacy_line.template_line,
                visible=legacy_line.visible,
                sequence=legacy_line.sequence,
                css_class=legacy_line.css_class,
                page_break=legacy_line.page_break,
            )
            line.save()
            mapping[(fiscal_year, legacy_line.id)] = line
    return legacy_lines, mapping


def attach_parents(legacy_lines, mapping):
    to_save = []
    for legacy_line in legacy_lines:
        if not legacy_line.parent:
            continue
        for fiscal_year in ("current", "previous"):
            line = mapping.get((fiscal_year, legacy_line.id))
            parent = mapping.get((fiscal_year, legacy_line.parent.id))
            if not line or not parent:
                continue
            line.parent = parent
            to_save.append(line)
    if to_save:
        NewLine.save(to_save)


def copy_details(legacy_lines, mapping):
    to_create = []
    for legacy_line in legacy_lines:
        for detail in legacy_line.line_accounts:
            line = mapping.get((detail.fiscal_year, legacy_line.id))
            if not line:
                continue
            to_create.append(
                {
                    "report_line": line.id,
                    "account": detail.account.id,
                    "credit": detail.credit,
                    "debit": detail.debit,
                }
            )
    if to_create:
        NewDetail.create(to_create)


def migrate_report(report):
    periods = ensure_comparison_periods(report)
    if len(periods) > 2:
        return "skipped_more_than_two_periods"
    if not periods:
        return "skipped_no_target_periods"

    legacy_lines = LegacyLine.search([("report", "=", report.id)], order=[], limit=1)
    if not legacy_lines:
        return "migrated_periods_only"

    existing_lines = NewLine.search(
        [("report_period.report", "=", report.id)],
        order=[],
        limit=1,
    )
    if existing_lines and not REPLACE_EXISTING:
        return "skipped_existing_target_lines"
    if existing_lines:
        delete_existing_lines(report)

    fresh_report = Report(report.id)
    periods_by_year = target_periods(fresh_report)
    legacy_lines, mapping = create_new_lines(fresh_report, periods_by_year)
    attach_parents(legacy_lines, mapping)
    copy_details(legacy_lines, mapping)
    return "migrated"


domain = []
if REPORT_IDS:
    domain.append(("id", "in", REPORT_IDS))
reports = Report.search(domain, order=[("id", "ASC")])

results = {
    "migrated": 0,
    "migrated_periods_only": 0,
    "skipped_no_legacy_lines": 0,
    "skipped_more_than_two_periods": 0,
    "skipped_no_target_periods": 0,
    "skipped_existing_target_lines": 0,
}

for report in reports:
    outcome = migrate_report(report)
    results.setdefault(outcome, 0)
    results[outcome] += 1
    print("%s: %s" % (report.rec_name, outcome))
    if not DRY_RUN and COMMIT_EACH_REPORT and outcome == "migrated":
        transaction.commit()

print("Summary:")
for key in sorted(results):
    print("  %s: %s" % (key, results[key]))

if not DRY_RUN:
    transaction.commit()
