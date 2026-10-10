# MDRRMC accident monitoring system

Flask dashboard for Echague accident records, FP-Growth patterns, maps and suggested actions.

## Local startup

Use the project's Python environment and start Oracle/XEPDB1 first:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Sign in at `/login` using the configured account. Credentials and the session secret belong in the ignored `.env` file. Never commit that file. The database settings are `ORACLE_HOST=localhost`, `ORACLE_PORT=1521`, `ORACLE_SERVICE=XEPDB1`, `ORACLE_USER=rescue`, `ORACLE_TABLE=MDRRMC_RECORDS` and `DATA_BACKEND=oracle`. Set `ORACLE_PASSWORD` privately. This installation uses Oracle as the primary store; an outage never triggers a CSV fallback.

Use one app worker. Preview files waiting for column mapping and login rate limits are in process memory. Once saved to the review queue, drafts survive restarts and signing out. Pending files that have not yet been saved to Oracle expire after 30 minutes and must be uploaded again.

## Oracle setup and initial migration

On an empty installation, with the configured schema allowed to create tables:

```powershell
.\.venv\Scripts\python.exe scripts/migrate_review_database.py
```

This creates only `MDRRMC_RECORDS`, `MDRRMC_BATCHES`, `MDRRMC_DRAFTS`, `MDRRMC_HISTORY` and `MDRRMC_STATE`. It leaves the older `CCDRMC_CRASH_RECORDS` table and all unrelated tables untouched. The 2,795 supplied CSV rows were migrated as historical approved records, preserving separate casualty rows and the source CSV. Repeating the migration with unchanged historical data inserts nothing; changed historical data is rejected instead of silently overwritten.

`MDRRMC_RECORDS` holds the approved JSON payload and revision under a stable internal record ID. Batches retain source filenames and original upload bytes. Drafts retain original values, editable values, cleaned features, issues, review decisions and the preprocessing version. History records reviewed changes and approved before/after values. Original spreadsheet row numbers are not incident identifiers.

Back up the Oracle schema with your normal Oracle backup process. The source CSV is preserved as the initial migration reference, not a backup of subsequent changes.

## Data workflow

- **All data** shows every stored column with a 10/25/50/100-entry selector and search. Select a row to view its history or edit it. The review banner, pending-review panel and date/severity filters are removed.
- **Upload file** accepts CSV, TSV and XLSX. The dataset preview supports search, pagination, original/cleaned views, filename, row/column counts, empty-cell counts, duplicate-row counts and per-column missing/unique counts. Uploads open directly in the preview with automatic heading recognition and mixed-date parsing. Multi-sheet workbooks retain a worksheet selector; no heading-mapping or date-format form is shown.
- **Clean and add data** adds valid rows together without individual approvals. Exact duplicates are skipped, including matches against existing records. Different people or additional values remain separate. Invalid date/time rows, unresolved severity and conflicting severity are excluded.
- **Download excluded rows** provides original submitted values, file row numbers and reasons. It is available before and after import while the session-owned preview remains valid (30 minutes). Original files and import summaries are retained in Oracle.
- Dataset persistence, history and analysis rebuilding share one transaction. A failure rolls back the import; the in-memory analysis updates only after commit. Duplicate checks are repeated under the write lock. Repeating the same successful import request returns its original result.
- **Add one record** cleans and saves a valid individual record directly. Invalid values produce an error in the form.
- Selecting a data row opens record details and change history. Editing an existing approved record retains the prior correction-review workflow and revision checks. Earlier saved drafts are retained; new file uploads do not create a review queue.

The database connection is configured once. There are no Oracle import, connection-test or agency-source controls in Data. If Oracle is unavailable the application shows a connection error and does not save to another location.

## Preprocessing

`services/incoming_pipeline.py` runs the versioned `dataset-v2` methodology on new records only. The historical 2019–2025 data are the reference schema and fallback source for numeric medians; historical records are not rewritten.

- Mixed date strings and fractional Excel serial dates/times are parsed before extracting year, month, weekday, hour and minute. The established six right-closed time periods are retained. Unambiguous day-first dates are recognised per row. Ambiguous numeric dates default to month/day/year and their count is disclosed in Processing summary.
- Manual dictionaries run first, followed by [RapidFuzz ratio matching](https://rapidfuzz.github.io/RapidFuzz/Usage/process.html) with an 85 cutoff. Close ties remain unchanged. Geographic prefixes such as P1 are removed before splitting barangay, municipality and province. New categorical fields receive cardinality and case/whitespace checks; frequent values anchor fuzzy correction.
- Each variable is profiled before imputation. New columns with at least 70% missing values are marked Storage/Auditing Only. Identifiers and high-cardinality new text are also excluded from the active model. Explicit reporting fields can yield an information-presence flag; missing documentation is not interpreted as a negative finding. Eligible new variables/flags are analysis candidates, while the established seven-feature analysis model remains unchanged.
- Regex rules derive Fatal, Non-Fatal or Damage-to-Property from injury/damage text. Negation is handled before positive outcome words. Ambiguous or unparsed descriptions get Unknown and `needs_manual_review=True`; under the agreed import policy these rows are excluded from publication and remain in the downloadable correction file.
- Numeric values are coerced and typed as float64 or nullable Int64. Continuous missing values receive the incoming median, falling back to historical medians where available. With no observed median, values remain null. Categorical gaps use Unknown. Date/time-derived values and identifiers are not median-filled. Imputed coordinates are explicitly marked and excluded from map points.
- Every saved new record receives a sequential `ACC-000001`-style accident ID. Allocation uses state row 2 under the existing transaction lock; rejected rows receive no ID, failed transactions roll back allocation, and the counter prevents reuse after deletions. Uploaded accident IDs are preserved separately.

Original files, row values, normalization scores, imputation counts, variable roles, processing version and import outcomes remain available in the batch/history audit. The preview exposes column information and Processing summary without requiring individual record approval.

## Filters and downloads

Data supports search and a 10/25/50/100-entry page size. Existing report API filters remain available for other dashboard uses. **Download Excel** includes all matching approved records, retained extra columns, applied filters and generation time. Formula-like uploaded text is escaped. **Analysis PDF** includes the same selection, summary counts, charts, and up to ten patterns with their suggested actions; its patterns are recomputed from the filtered subset. The PDF records its filters, generation time in Philippine time, and dataset revision.

Existing CSV endpoints remain available for compatibility. The upper-right Download report menu on Overview provides Excel and PDF, using the active Overview filters. The records table is paginated; exports include the complete matching selection.

## Authentication

All dashboard and API routes require sign-in; writes require a session CSRF token. Passwords are stored as Werkzeug hashes. `LOGIN_USERNAME` and `LOGIN_PASSWORD_HASH` can override the initial account. Sessions expire after eight hours and Sign out clears the browser session. Configure a long random `SECRET_KEY`. Use HTTPS and `SESSION_COOKIE_SECURE=1` for remote deployment. Five sign-in attempts per IP are allowed within fifteen minutes; this limiter resets on process restart.

## Verification

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
$env:ORACLE_INTEGRATION_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests/test_review_oracle.py -q
```

Ordinary tests explicitly use CSV fixtures or mocks and never write to the live Oracle configuration. Opt-in Oracle tests run against the actual tables but roll back every test change. They verify bulk dataset import, paging, session ownership, retry protection, duplicate skipping, exclusions, mining rollback and the retained edit-review workflow. `scripts/qa_browser_server.py` is an optional developer browser check, requiring the bundled Playwright module and Microsoft Edge; it also rolls back all database changes and writes screenshots/sample exports under `tmp/qa`.


## Echague municipal heatmap

The Accident Map uses locally vendored MapLibre GL JS 5.6.2 (BSD-3-Clause), replacing Leaflet and its heat plugin. The local `static/geo/openfreemap-liberty.json` style uses [OpenFreeMap](https://openfreemap.org/) vector tiles, fonts and sprites. Its public service is intended for website maps, requires no API key, and supplies OpenFreeMap, OpenMapTiles and OpenStreetMap attribution through its tile metadata. WebGL and internet access are required for the street basemap. The local municipal boundary and heat data still initialize if the tile service is unavailable. The standard Liberty basemap keeps its full colors. A continuous heatmap uses transparent orange-to-red gradients, soft edges and overlapping kernels, with no discrete contour bands.

Only the Echague municipal feature is bundled (about 5 KB), not a province or country map. `static/geo/source.json` records the geoBoundaries source, represented year (2020), source agencies and CC BY 3.0 IGO license. The exact source is https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/PHL/ADM3/geoBoundaries-PHL-ADM3_simplified.geojson. The simplified geometry supports visualization, not cadastral or legal boundary decisions. It does not contain barangay polygons.

The server filters coordinates against that polygon, including its eastern extent omitted by the former hard-coded rectangle. Missing, invalid, imputed and outside-boundary locations are excluded from spatial display, with coverage reported in the UI. Barangay rankings count filtered records by their recorded barangay, including unplottable records; these are descriptive counts, not risk rates. Every eligible crash contributes equal weight to the continuous MapLibre heatmap. Nearby kernels blend together, with transparent low-density tails and soft red centers. Intensity and radius vary with zoom; there is no per-filter normalization, coordinate jitter, capped weighting or contour classification. Heat colors indicate recorded concentration, not calibrated risk thresholds or TOPSIS scores. Repeated geocodes can still represent address centroids rather than surveyed crash sites.

Year options come from the dataset. Requests are cancelled and versioned to prevent stale filter responses. The old `/api/map` list endpoint remains compatible; `/api/map/summary` adds counts and coverage. The boundary and bundled renderer work without street tiles if the app itself is accessible.

Validation: `python -m pytest tests -q`. Browser QA uses the isolated CSV backend and never writes to Oracle: set `PLAYWRIGHT_MODULE` to your installed Playwright module and run `python scripts/qa_map_server.py` from this directory (the script currently uses installed Microsoft Edge on Windows). Screenshots are in `docs/map-desktop.png` and `docs/map-mobile.png`.

Cleanup on 2026-10-10 removed the unused Leaflet distribution, project Python bytecode, pytest caches and temporary test datasets, generated QA exports/screenshots, and regenerable rule-cache files: 150 files / 35,530,884 bytes (33.88 MiB). Production data, environment settings, dependencies, tests, operational scripts, and possibly active log files were retained. Rule caching remains enabled for faster starts; deleting generated caches saves disk space, not necessarily runtime memory. Restart the application process to load the updated server code.

