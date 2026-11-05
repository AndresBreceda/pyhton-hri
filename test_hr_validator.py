import tempfile
import unittest
from pathlib import Path

from hr_validator import BLOCKER, ERROR, WARNING, validate

HEADER = "employee_id,first_name,last_name,email,status,hire_date,termination_date,manager_id,site,department"
GOOD = "1001,Ana,López,ana@demo.com,Active,2020-01-01,,,HQ,IT"


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, *lines, name="f.csv", encoding="utf-8", raw=None):
        path = self.dir / name
        path.write_bytes(raw if raw is not None else ("\n".join(lines) + "\n").encode(encoding))
        return path

    def codes(self, report, severity=None):
        return {i.code for i in report.issues if severity is None or i.severity == severity}

    def test_clean_file_is_ok(self):
        report = validate(self.file(HEADER, GOOD))
        self.assertEqual(report.exit_code, 0)
        self.assertEqual(report.issues, [])

    def test_empty_file_is_blocker(self):
        report = validate(self.file(raw=b""))
        self.assertIn("EMPTY_FILE", self.codes(report, BLOCKER))
        self.assertEqual(report.exit_code, 2)

    def test_missing_column_is_blocker(self):
        report = validate(self.file(HEADER.replace(",site,", ",location,"), GOOD))
        self.assertIn("MISSING_COLUMNS", self.codes(report, BLOCKER))

    def test_duplicates_and_invalid_values(self):
        report = validate(
            self.file(
                HEADER,
                GOOD,
                "1001,Bob,Ray,ana@demo.com,Leave,2020-01-01,,,HQ,IT",
                "1003,Cy,Doe,not-an-email,Active,01/02/2020,,,HQ,IT",
            )
        )
        errors = self.codes(report, ERROR)
        for code in ("DUPLICATE_ID", "DUPLICATE_EMAIL", "INVALID_STATUS", "INVALID_EMAIL", "INVALID_DATE"):
            self.assertIn(code, errors)
        self.assertEqual(report.exit_code, 1)

    def test_manager_not_found_and_date_order(self):
        report = validate(self.file(HEADER, "1001,Ana,López,ana@demo.com,Terminated,2020-01-01,2019-01-01,777,HQ,IT"))
        self.assertIn("DATE_ORDER", self.codes(report, ERROR))
        self.assertIn("MANAGER_NOT_FOUND", self.codes(report, WARNING))

    def test_column_count_mismatch(self):
        report = validate(self.file(HEADER, GOOD, "1002,Bo,Li,bo@demo.com,Active,2020-01-01,,,HQ,Health, Safety"))
        self.assertIn("COLUMN_COUNT", self.codes(report, ERROR))
        self.assertEqual(report.total_rows, 2)

    def test_latin1_file_is_read_with_warning(self):
        report = validate(self.file(HEADER, GOOD, encoding="cp1252"))
        self.assertIn("NOT_UTF8", self.codes(report, WARNING))
        self.assertEqual(report.exit_code, 0)

    def test_bom_and_mojibake(self):
        bom = validate(self.file(raw=("﻿" + HEADER + "\n" + GOOD + "\n").encode("utf-8")))
        self.assertIn("UTF8_BOM", self.codes(bom, WARNING))
        moji = validate(self.file(HEADER, GOOD.encode("utf-8").decode("cp1252"), name="m.csv"))
        self.assertIn("CORRUPTED_TEXT", self.codes(moji, WARNING))

    def test_semicolon_delimiter(self):
        report = validate(self.file(HEADER.replace(",", ";"), GOOD.replace(",", ";")))
        self.assertEqual(report.delimiter, ";")
        self.assertEqual(report.exit_code, 0)

    def test_mass_deactivation_safeguard(self):
        rows = [f"{1000 + n},N{n},L{n},u{n}@demo.com,Active,2020-01-01,,,HQ,IT" for n in range(10)]
        previous = self.file(HEADER, *rows, name="prev.csv")
        blocked = validate(self.file(HEADER, *rows[:5], name="cur.csv"), previous, threshold=0.10)
        self.assertIn("MASS_DEACTIVATION", self.codes(blocked, BLOCKER))
        fine = validate(self.file(HEADER, *rows[:9], name="cur2.csv"), previous, threshold=0.10)
        self.assertIn("DEACTIVATIONS", self.codes(fine, WARNING))
        self.assertEqual(fine.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
