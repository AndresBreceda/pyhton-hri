"""HR File Validator.

Pre-load checks for an employee data file (the kind an HRIS such as Workday
or ADP delivers over SFTP every night). The goal is to catch problems
*before* the file is loaded into the target platform, and to produce a
report that a support analyst can send back to the customer.

Usage:
    python hr_validator.py FILE [--previous FILE] [--threshold 0.10]
                                [--report-json PATH] [--errors-csv PATH]

Exit codes:
    0  file is OK (warnings allowed)
    1  row-level errors: some rows would be rejected
    2  blocker: the file must not be loaded at all
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

REQUIRED_COLUMNS = [
    "employee_id",
    "first_name",
    "last_name",
    "email",
    "status",
    "hire_date",
    "termination_date",
    "manager_id",
    "site",
    "department",
]
REQUIRED_VALUES = ["employee_id", "first_name", "last_name", "email", "status", "hire_date", "site"]
ALLOWED_STATUS = {"active", "terminated"}
DATE_FORMAT = "%Y-%m-%d"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Typical UTF-8 bytes decoded as Latin-1/Windows-1252: "JosÃ©", "MuÃ±oz".
MOJIBAKE_RE = re.compile(r"Ã[\x80-\xbf¡-¿]|Â[\xa0-\xbf]")

BLOCKER = "BLOCKER"
ERROR = "ERROR"
WARNING = "WARNING"


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    row: int | None = None  # file line number (header = line 1)
    employee_id: str | None = None


@dataclass
class Report:
    file: str
    encoding: str = "unknown"
    delimiter: str = ","
    total_rows: int = 0
    active_rows: int = 0
    issues: list[Issue] = field(default_factory=list)

    def add(self, severity, code, message, row=None, employee_id=None):
        self.issues.append(Issue(severity, code, message, row, employee_id))

    def count(self, severity: str) -> int:
        return sum(1 for i in self.issues if i.severity == severity)

    @property
    def rejected_rows(self) -> int:
        return len({i.row for i in self.issues if i.severity == ERROR and i.row})

    @property
    def exit_code(self) -> int:
        if self.count(BLOCKER):
            return 2
        if self.count(ERROR):
            return 1
        return 0


# ---------------------------------------------------------------- reading


def read_text(path: Path, report: Report) -> str:
    """Decode the file, recording encoding problems instead of crashing."""
    raw = path.read_bytes()
    if not raw.strip():
        report.add(BLOCKER, "EMPTY_FILE", "File is empty. Loading it could deactivate every employee.")
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        report.encoding = "utf-8 (with BOM)"
        report.add(WARNING, "UTF8_BOM", "File starts with a UTF-8 BOM; it was stripped before parsing.")
        text = raw[3:].decode("utf-8")
    else:
        try:
            text = raw.decode("utf-8")
            report.encoding = "utf-8"
        except UnicodeDecodeError:
            report.encoding = "not utf-8 (read as cp1252)"
            report.add(
                WARNING,
                "NOT_UTF8",
                "File is not valid UTF-8 (probably exported as ANSI/Latin-1). It was read as "
                "Windows-1252 so accents are preserved, but ask the customer to export it as UTF-8.",
            )
            text = raw.decode("cp1252", errors="replace")
    return text


def detect_delimiter(text: str, report: Report) -> str:
    first_line = text.splitlines()[0] if text else ""
    try:
        delimiter = csv.Sniffer().sniff(first_line, delimiters=",;|\t").delimiter
    except csv.Error:
        delimiter = ","
    report.delimiter = delimiter
    if delimiter != ",":
        report.add(WARNING, "DELIMITER", f"Delimiter is {delimiter!r}, expected ','. Parsed anyway.")
    return delimiter


def parse_date(value: str) -> date | None:
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None


# ---------------------------------------------------------------- checks


def check_header(header: list[str], report: Report) -> bool:
    normalized = [h.strip().lower() for h in header]
    missing = [c for c in REQUIRED_COLUMNS if c not in normalized]
    unexpected = [h for h in normalized if h not in REQUIRED_COLUMNS]
    if missing:
        report.add(
            BLOCKER,
            "MISSING_COLUMNS",
            f"Header is missing required columns: {', '.join(missing)}. "
            "The customer may have changed their export.",
        )
    if unexpected:
        report.add(WARNING, "UNEXPECTED_COLUMNS", f"Unexpected columns will be ignored: {', '.join(unexpected)}.")
    return not missing


def check_rows(rows: list[tuple[int, dict]], report: Report) -> None:
    ids_seen: dict[str, int] = {}
    emails_seen: dict[str, int] = {}
    all_ids = {r["employee_id"].strip() for _, r in rows if r.get("employee_id", "").strip()}

    for line, row in rows:
        emp = row.get("employee_id", "").strip() or None

        def add(severity, code, message):
            report.add(severity, code, message, row=line, employee_id=emp)

        for col in REQUIRED_VALUES:
            if not (row.get(col) or "").strip():
                add(ERROR, "MISSING_VALUE", f"Required field '{col}' is empty.")

        if emp:
            if emp in ids_seen:
                add(ERROR, "DUPLICATE_ID", f"employee_id {emp} already appears on line {ids_seen[emp]}.")
            else:
                ids_seen[emp] = line

        email = (row.get("email") or "").strip().lower()
        if email:
            if not EMAIL_RE.match(email):
                add(ERROR, "INVALID_EMAIL", f"Email '{email}' is not valid. SSO login matching may fail.")
            elif email in emails_seen:
                add(ERROR, "DUPLICATE_EMAIL", f"Email {email} already used on line {emails_seen[email]}.")
            else:
                emails_seen[email] = line

        status = (row.get("status") or "").strip().lower()
        if status and status not in ALLOWED_STATUS:
            add(ERROR, "INVALID_STATUS", f"Status '{row['status']}' not in {sorted(ALLOWED_STATUS)}.")
        if status == "active":
            report.active_rows += 1

        hire_raw = (row.get("hire_date") or "").strip()
        term_raw = (row.get("termination_date") or "").strip()
        hire = parse_date(hire_raw) if hire_raw else None
        term = parse_date(term_raw) if term_raw else None
        if hire_raw and hire is None:
            add(ERROR, "INVALID_DATE", f"hire_date '{hire_raw}' is not in YYYY-MM-DD format.")
        if term_raw and term is None:
            add(ERROR, "INVALID_DATE", f"termination_date '{term_raw}' is not in YYYY-MM-DD format.")
        if hire and term and term < hire:
            add(ERROR, "DATE_ORDER", "termination_date is before hire_date.")
        if status == "terminated" and not term_raw:
            add(WARNING, "MISSING_TERM_DATE", "Employee is terminated but has no termination_date.")
        if status == "active" and term_raw:
            add(WARNING, "ACTIVE_WITH_TERM_DATE", "Employee is active but has a termination_date.")

        manager = (row.get("manager_id") or "").strip()
        if manager:
            if manager == emp:
                add(WARNING, "SELF_MANAGER", "Employee is listed as their own manager.")
            elif manager not in all_ids:
                add(WARNING, "MANAGER_NOT_FOUND", f"manager_id {manager} does not exist in this file.")

        for col in ("first_name", "last_name"):
            if MOJIBAKE_RE.search(row.get(col) or ""):
                add(WARNING, "CORRUPTED_TEXT", f"{col} '{row[col]}' looks corrupted (encoding issue).")


def check_mass_deactivation(current: list[dict], previous_path: Path, threshold: float, report: Report) -> None:
    """Safeguard: compare with the previous file before deactivating many users."""
    prev_report = Report(file=str(previous_path))
    prev_text = read_text(previous_path, prev_report)
    if not prev_text:
        return
    delimiter = detect_delimiter(prev_text, prev_report)
    prev_rows = list(csv.DictReader(io.StringIO(prev_text), delimiter=delimiter))
    prev_active = {
        (r.get("employee_id") or "").strip()
        for r in prev_rows
        if (r.get("status") or "").strip().lower() == "active"
    }
    now_active = {
        (r.get("employee_id") or "").strip()
        for r in current
        if (r.get("status") or "").strip().lower() == "active"
    }
    if not prev_active:
        return
    lost = prev_active - now_active
    ratio = len(lost) / len(prev_active)
    if ratio > threshold:
        report.add(
            BLOCKER,
            "MASS_DEACTIVATION",
            f"{len(lost)} of {len(prev_active)} previously active employees ({ratio:.0%}) would be "
            f"deactivated, above the {threshold:.0%} safeguard. Confirm with the customer before loading.",
        )
    elif lost:
        report.add(WARNING, "DEACTIVATIONS", f"{len(lost)} employees will be deactivated ({ratio:.0%}).")


# ---------------------------------------------------------------- main flow


def validate(path: Path, previous: Path | None = None, threshold: float = 0.10) -> Report:
    report = Report(file=str(path))
    text = read_text(path, report)
    if not text:
        return report

    delimiter = detect_delimiter(text, report)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        report.add(BLOCKER, "EMPTY_FILE", "File has no header row.")
        return report

    if not check_header(header, report):
        return report

    keys = [h.strip().lower() for h in header]
    rows: list[tuple[int, dict]] = []
    data_lines = 0
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue  # skip blank lines
        data_lines += 1
        if len(values) != len(keys):
            report.add(
                ERROR,
                "COLUMN_COUNT",
                f"Row has {len(values)} values but the header has {len(keys)} "
                "(unquoted delimiter inside a value?).",
                row=line_no,
            )
            continue
        rows.append((line_no, dict(zip(keys, values))))

    report.total_rows = data_lines
    if not rows:
        report.add(BLOCKER, "NO_DATA_ROWS", "File has a header but no employee rows.")
        return report

    check_rows(rows, report)
    if previous:
        check_mass_deactivation([r for _, r in rows], previous, threshold, report)
    return report


def print_report(report: Report) -> None:
    status = {0: "OK TO LOAD", 1: "LOAD WITH REJECTED ROWS", 2: "DO NOT LOAD"}[report.exit_code]
    print(f"\nHR File Validation Report: {report.file}")
    print("=" * 70)
    print(f"Encoding: {report.encoding} | Delimiter: {report.delimiter!r}")
    print(
        f"Rows: {report.total_rows} | Active: {report.active_rows} | "
        f"Rows rejected: {report.rejected_rows}"
    )
    print(
        f"Blockers: {report.count(BLOCKER)} | Errors: {report.count(ERROR)} | "
        f"Warnings: {report.count(WARNING)}"
    )
    print(f"RESULT: {status}")
    print("-" * 70)
    for issue in sorted(report.issues, key=lambda i: ({BLOCKER: 0, ERROR: 1, WARNING: 2}[i.severity], i.row or 0)):
        where = f"line {issue.row}" if issue.row else "file"
        who = f" [{issue.employee_id}]" if issue.employee_id else ""
        print(f"{issue.severity:<8} {where:<9}{who} {issue.code}: {issue.message}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an HR employee file before loading it.")
    parser.add_argument("file", type=Path, help="employee CSV file to validate")
    parser.add_argument("--previous", type=Path, help="previous day's file, for the mass-deactivation safeguard")
    parser.add_argument("--threshold", type=float, default=0.10, help="max share of deactivations (default 0.10)")
    parser.add_argument("--report-json", type=Path, help="write the full report as JSON")
    parser.add_argument("--errors-csv", type=Path, help="write the issues as CSV (to send to the customer)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # show corrupted names exactly as they are

    if not args.file.exists():
        print(f"File not found: {args.file}", file=sys.stderr)
        return 2

    report = validate(args.file, args.previous, args.threshold)
    print_report(report)

    if args.report_json:
        data = asdict(report) | {"exit_code": report.exit_code, "rejected_rows": report.rejected_rows}
        args.report_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.errors_csv:
        with args.errors_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["severity", "line", "employee_id", "code", "message"])
            for i in report.issues:
                writer.writerow([i.severity, i.row or "", i.employee_id or "", i.code, i.message])
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
