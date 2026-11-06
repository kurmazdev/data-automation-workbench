# Data Automation Workbench

A Python and React application for cleaning CSV and Excel datasets using explicit, reviewable rules. Original values remain available throughout processing, and every record receives an accepted or rejected outcome with an audit trail.

## Features

- Import UTF-8 CSV and the first worksheet of XLSX files.
- Map columns and configure trimming, whitespace normalization, case conversion, required fields, dates, decimals, email validation, and duplicate handling.
- Compare original and cleaned values, search results, and inspect rejection reasons.
- Reopen saved runs from SQLite; processing changes create a separate run.
- Export a workbook containing Summary, Accepted, Rejected, and Audit sheets.

## Technologies

Python 3.11+, FastAPI, Pydantic, SQLite, openpyxl, React 19, TypeScript, and esbuild. Tests use unittest, Playwright, and axe-core.

## Installation

Requires Python 3.11 or newer and Node.js 20.19 or newer (Node 22 recommended). Use a compatible interpreter for `python3` below. Run from the project root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn workbench.main:create_app --factory --app-dir backend --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. The backend serves the compiled frontend. API documentation is at `/docs`.

For frontend development, keep the backend running and use `npm --prefix frontend run dev`. Open http://127.0.0.1:5173; API requests are proxied to the backend.

## Usage

1. Select **Use sample data** or upload a CSV/XLSX file.
2. Review the source columns, map fields, and configure validation rules.
3. Process the dataset and inspect changes and rejected records.
4. Export the workbook or adjust rules and create another run.

The bundled customer sample is fictional. Its preset produces 17 records: 8 accepted and 9 rejected. Changed records are a subset of accepted records.

## Data and security

- Identifiers and decimal values retain textual precision. Date order and numeric grouping are never inferred.
- Each source record has an outcome; original columns remain in both export record sheets.
- Duplicate comparisons use exact normalized strings. Invalid records do not reserve a duplicate key.
- Source XLSX formulas and error cells reject their record, including unmapped cells. Exported strings are literal Excel text.
- Input files, worksheet dimensions, and row/cell counts are bounded. SQL statements are parameterized.
- Local Host/Origin checks block foreign-host access and cross-site uploads. Responses disable caching, framing, and MIME sniffing.
- Runtime state defaults to `data/workbench.sqlite3`; `WORKBENCH_DB` can select another path. Runtime uploads and results must not be committed.

This is a single-user local application. Bind it to loopback. It has no account system or production hosting configuration.

## Verification

```sh
PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -v
npm --prefix frontend run build
npm --prefix frontend run format:check
npm --prefix frontend exec -- playwright install chromium
npm --prefix frontend run test:e2e
PYTHONPATH=backend .venv/bin/python scripts/verify_sample.py
.venv/bin/python scripts/smoke_api.py --base-url http://127.0.0.1:8000
```

The browser suite starts an isolated backend on port 8011 with a temporary database. The sample and HTTP verification scripts create sample runs; use a disposable `WORKBENCH_DB` when running them against a separate verification server.

## Structure

- `backend/workbench/`: ingestion, configuration, processing, storage, export, and API.
- `backend/tests/`: data invariants, malformed files, export safety, and HTTP workflows.
- `frontend/src/`: mapping, rules, results, and record comparison.
- `frontend/tests/`: desktop/mobile workflows, keyboard behavior, and accessibility checks.
- `samples/`: fictional CSV/XLSX fixtures and the sample rules preset.
- `scripts/`: fixture generation and repeatable workflow checks.

Dependencies are installed from their registries and retain their respective licenses. No third-party dependency source is vendored in this repository.
