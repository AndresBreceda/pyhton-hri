"""Generate the demo files in samples/. All data is fictional."""

from pathlib import Path

HEADER = "employee_id,first_name,last_name,email,status,hire_date,termination_date,manager_id,site,department"

CLEAN = [
    "1001,Ana,López,ana.lopez@acme-demo.com,Active,2019-03-01,,,Cincinnati HQ,Executive",
    "1002,José,Muñoz,jose.munoz@acme-demo.com,Active,2020-06-15,,1001,Cincinnati HQ,EHS",
    "1003,Emily,Carter,emily.carter@acme-demo.com,Active,2021-01-10,,1002,Louisville Plant,EHS",
    "1004,Michael,Brown,michael.brown@acme-demo.com,Active,2022-09-05,,1002,Louisville Plant,Operations",
    "1005,Sofía,Hernández,sofia.hernandez@acme-demo.com,Active,2023-02-20,,1001,Aguascalientes,IT",
    "1006,David,Kim,david.kim@acme-demo.com,Terminated,2018-11-12,2026-10-31,1004,Louisville Plant,Operations",
    "1007,Laura,Nguyen,laura.nguyen@acme-demo.com,Active,2024-04-01,,1005,Aguascalientes,IT",
    "1008,Carlos,Ramírez,carlos.ramirez@acme-demo.com,Active,2025-07-14,,1004,Louisville Plant,Operations",
]

WITH_ERRORS = [
    "1001,Ana,López,ana.lopez@acme-demo.com,Active,2019-03-01,,,Cincinnati HQ,Executive",
    "1002,José,Muñoz,jose.munoz@acme-demo.com,Active,2020-06-15,,1001,Cincinnati HQ,EHS",
    # duplicate employee_id
    "1002,Emily,Carter,emily.carter@acme-demo.com,Active,2021-01-10,,1002,Louisville Plant,EHS",
    # invalid email + manager that does not exist
    "1004,Michael,Brown,michael.brown@acme-demo,Active,2022-09-05,,9999,Louisville Plant,Operations",
    # US date format + missing site
    "1005,Sofía,Hernández,sofia.hernandez@acme-demo.com,Active,02/20/2023,,1001,,IT",
    # terminated without termination date
    "1006,David,Kim,david.kim@acme-demo.com,Terminated,2018-11-12,,1004,Louisville Plant,Operations",
    # invalid status + duplicate email
    "1007,Laura,Nguyen,ana.lopez@acme-demo.com,On Leave,2024-04-01,,1005,Aguascalientes,IT",
    # termination before hire
    "1008,Carlos,Ramírez,carlos.ramirez@acme-demo.com,Terminated,2025-07-14,2024-01-01,1004,Louisville Plant,Operations",
    # unquoted comma inside a value -> column count
    "1009,Grace,Lee,grace.lee@acme-demo.com,Active,2025-01-06,,1001,Louisville Plant,Health, Safety",
]


def write(path: Path, lines: list[str], encoding: str = "utf-8", header: str = HEADER) -> None:
    path.write_bytes(("\n".join([header, *lines]) + "\n").encode(encoding))


def main() -> None:
    out = Path(__file__).parent / "samples"
    out.mkdir(exist_ok=True)

    write(out / "employees_clean.csv", CLEAN)
    write(out / "employees_with_errors.csv", WITH_ERRORS)
    # Same clean data exported as ANSI/Latin-1 instead of UTF-8.
    write(out / "employees_latin1.csv", CLEAN, encoding="cp1252")
    # Accents already corrupted upstream ("JosÃ©"): UTF-8 read as Latin-1, then saved as UTF-8 again.
    mojibake = [line.encode("utf-8").decode("cp1252") for line in CLEAN]
    write(out / "employees_mojibake.csv", mojibake)
    # The customer changed their export: 'site' column renamed to 'location'.
    write(out / "employees_changed_header.csv", CLEAN, header=HEADER.replace(",site,", ",location,"))
    # Truncated export: most active employees missing compared to the clean file.
    write(out / "employees_truncated.csv", CLEAN[:2])
    print(f"Sample files written to {out}")


if __name__ == "__main__":
    main()
