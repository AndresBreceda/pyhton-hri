# HR File Validator

A small Python tool that checks an **employee data file** (the kind an HRIS such as Workday or ADP delivers over SFTP every night) **before** it is loaded into a target platform, and produces a report a support analyst can send back to the customer.

I built it to understand the everyday problems behind file-based HR integrations: a file that would wipe out half the users, accents that arrive corrupted, a customer who quietly changed their export, or duplicate IDs that break user matching and SSO logins.

## What it checks

| Level | Check | Why it matters |
|---|---|---|
| **BLOCKER** (do not load) | Empty file / header without rows | An empty full file could deactivate every employee |
| | Required columns missing | The customer changed their export (e.g. `site` → `location`) |
| | Mass deactivation vs. the previous file (`--previous`, default threshold 10%) | A truncated export would deactivate real users |
| **ERROR** (row rejected) | Empty required fields | Users can't be created without them |
| | Duplicate `employee_id` or `email` | Breaks user matching and SSO (NameID is usually the email) |
| | Invalid email format | SSO login matching fails |
| | Status not `Active` / `Terminated` | Unknown values can't be mapped |
| | Dates not `YYYY-MM-DD`, termination before hire | `02/20/2023` is ambiguous (US vs. MX format) |
| | Wrong number of columns | Unquoted delimiter inside a value |
| **WARNING** | File not UTF-8, UTF-8 BOM, corrupted text (`JosÃ©`) | Encoding issues corrupt names |
| | Non-comma delimiter, unexpected columns | Export configuration drifted |
| | Manager not in file, self-manager | Org hierarchy will be incomplete |
| | Terminated without termination date, active with one | Inconsistent lifecycle data |

## Usage

Requires Python 3.10+ and nothing else (standard library only).

```bash
python make_samples.py                                   # generate the demo files
python hr_validator.py samples/employees_with_errors.csv
python hr_validator.py samples/employees_truncated.csv --previous samples/employees_clean.csv
python hr_validator.py samples/employees_with_errors.csv --errors-csv errors.csv --report-json report.json
python -m unittest -v                                    # run the tests
```

Exit codes work like a pipeline gate: `0` = OK to load, `1` = load with rejected rows, `2` = do not load.

## Demo files (fictional data)

| File | Scenario |
|---|---|
| `employees_clean.csv` | Everything correct |
| `employees_with_errors.csv` | Duplicates, invalid email, US date, missing site, invalid status, bad dates, broken row |
| `employees_latin1.csv` | Exported as ANSI/Latin-1 instead of UTF-8 |
| `employees_mojibake.csv` | Accents already corrupted upstream (`JosÃ©`) |
| `employees_changed_header.csv` | Customer renamed a column |
| `employees_truncated.csv` | Truncated export: run with `--previous employees_clean.csv` |

## Example output

```
HR File Validation Report: samples/employees_truncated.csv
======================================================================
Encoding: utf-8 | Delimiter: ','
Rows: 2 | Active: 2 | Rows rejected: 0
Blockers: 1 | Errors: 0 | Warnings: 0
RESULT: DO NOT LOAD
----------------------------------------------------------------------
BLOCKER  file      MASS_DEACTIVATION: 5 of 7 previously active employees (71%) would be deactivated, above the 10% safeguard. Confirm with the customer before loading.
```

## Possible next steps

- Configurable mapping spec per customer (column names, allowed values) in a JSON file
- Pick up files from an SFTP folder (`paramiko`) and archive them after validation
- Compare file vs. target database with SQL to reconcile counts

Built with the help of Claude Code.
