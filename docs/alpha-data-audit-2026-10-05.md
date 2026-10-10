# Data section alpha audit

**Follow-up, 6 October 2026:** The findings below describe the pre-fix system. See [implemented fixes and verification](data-alpha-fixes-2026-10-06.md) for the current status. The diagnostic script and browser screenshots are reusable checks and their output files now reflect the latest run.

**Date:** 5 October 2026  
**Assessment:** Suitable for supervised alpha testing. Fix the data-integrity defects below before relying on unattended imports for agency analysis.

The simple upload → dataset preview → add valid records workflow is appropriate. The main problem is not a lack of controls: some cleaning decisions can silently change the meaning of records. Adding more mandatory review screens would not solve that problem.

## Scope and evidence

- Ran the complete automated suite, including opt-in local Oracle integration tests: **103 passed in 40.45 seconds**.
- Ran the real browser workflow against a temporary local server using Oracle transactions that were rolled back. Verified a 152-row upload with 150 valid rows, one duplicate and one invalid row; preview, search, pagination, excluded-row download, bulk save, manual entry, Excel export, Overview report controls and mobile viewport containment. Browser checks passed; the server confirmed rollback of all browser-test changes.
- Added and ran **17 diagnostic probes**, including real XLSX parsing and HTTP requests. These are observations, not 17 passing assertions. Evidence: [probe-results.json](../tmp/alpha/probe-results.json). Reproduction script: [alpha_data_audit.py](../scripts/alpha_data_audit.py).
- Inspected upload, cleaning, duplicate detection, Oracle publication, record editing and analysis code; visually inspected desktop and mobile screenshots.
- No application logic or production records were changed by this audit. The diagnostic script, results and this report are the audit deliverables.

Tests used representative synthetic records, not a newly supplied agency dataset with verified outcomes. Existing tests passing does not resolve the additional failures reproduced below. This is not a penetration test, a full accessibility assessment, a disaster-recovery test or a production concurrency/capacity certification.

## Confirmed defects and policy risks

P1 means fix before routine automated importing. P2 means address during the next usability/reliability iteration.

| ID | Priority | Evidence and impact | Recommended correction |
|---|---|---|---|
| A01 | P1 | `damage_type = "Scratched bumper"` becomes null. The numeric-name expression matches `age` inside `damage_type`, forcing text into a number. Also, source `month = 3` with a March date ends with a null month: the derived `March` value is recast to the original numeric profile. New fields or derived features can lose data. | Use explicit field definitions and bounded name matching; let derived fields own their final types. Preserve original values and report failed conversions. |
| A02 | P1 | `no fracture` produces `Non-Fatal` with no review flag. `suspected fatal injury, outcome not confirmed` produces `Fatal` with no review flag. A supplied `Fatal` value with `abrasion` is silently changed to `Non-Fatal`. These probes demonstrate overconfident parsing and conflict handling, not verified medical outcomes. | Detect uncertainty and negation before positive terms. Preserve supplied and derived outcomes separately; flag conflicts. Only unresolved exceptions should require attention; routine valid rows can still be added together. |
| A03 | P1 | An actual XLSX file containing a date-only cell and no accident time produces `00:00:00`, assigned to `8:01PM-12MN`. The equivalent CSV keeps the time empty. This fabricates a time and can distort time-period patterns. | Treat a date-only value as an unknown time. Extract time only when the source actually supplies it; retain explicit midnight when known. Test CSV/XLSX parity. |
| A04 | P1 | The same original row with missing speed receives 20 in one batch and 80 in another because the batch medians differ. When compared against the first saved representation, the repeated row is marked `Ready`, not duplicate. | Persist a stable fingerprint of source values before imputation. Keep a separate normalized fingerprint if needed. Preserve casualty/person identifiers so different people from the same incident remain separate records. |
| A05 | P1 | A very large integer in `age` causes an uncaught conversion `TypeError`. A real `/api/dataset/prepare` request returns HTTP 500 with a non-JSON response. The upload UI then suggests a file type/size problem, which is not the cause. | Validate numeric bounds before casting. Return a structured row/field validation result; exclude or retain the invalid value as unknown under an explicit rule, while preserving valid rows. |
| A06 | P1 policy risk | A fixture intended as day/month/year containing `03/04/2026` and `25/04/2026` becomes March 4 and April 25. Ambiguous values use month-first even when other rows use unambiguous day-first dates. The policy is disclosed only in expandable processing details. | Configure the known agency source convention. For uncertain files, ask one plain-language question at dataset level or withhold ambiguous rows; do not silently infer the intended date. A file may legitimately contain mixed conventions, so inference alone is insufficient. |
| A07 | P2 | `age = -5` and `speed = 900` are accepted as `Ready`. Numeric conversion succeeds but domain validation is missing for these new fields. | Define agency-approved ranges and units. Negative age is invalid; speed requires an explicit unit and plausibility policy. Warn or quarantine questionable values without discarding their source text. |
| A08 | P2 | Uploading a second file in the same session invalidates the first preview: preparing the first token returns “This preview expired.” This can also affect two browser tabs. Previews otherwise expire after 30 minutes and are held in process memory. | Give each preview its own lifecycle; warn before replacement. Persist recoverable preparation/import results and provide a clear resume/re-upload path. Saved Oracle records are not erased by preview expiry. |
| A09 | P2 | A literal `N/A` produces zero missing cells in the dataset summary but one missing value in its column profile. The page currently explains that summary missingness counts empty cells, so this is a definition/usability problem rather than unexplained arithmetic. | Use a consistent “missing or unknown” definition, or explicitly display separate empty-cell and unknown-value counts. Keep original missingness separate from values filled during cleaning. |
| A10 | P2 | A corrupt XLSX correctly returns HTTP 400, but tells an administrator to “specify an engine manually.” | Translate parser errors into an action the administrator can take, such as opening and saving a valid XLSX/CSV. Keep engine diagnostics in logs. |

### Source locations for implementation

- A01: `services/incoming_pipeline.py:119` numeric-name inference; `:136` numeric casting; `:169` recasting after feature generation.
- A02: `services/incoming_pipeline.py:31` severity parsing and `:174` final overwrite. `static/js/data.js` still offers a manual severity selector, making silent replacement particularly confusing.
- A03/A06: `services/incoming_pipeline.py:46` datetime parsing and `:80` datetime-to-time extraction. `static/js/upload.js` always requests automatic date order.
- A04: `services/dataset_service.py:12` fingerprint and `:61` assessment use cleaned values, including imputed non-coordinate measurements.
- A05/A07: `services/incoming_pipeline.py:119–136`; `routes/dataset.py:31` preparation catches `ValueError`, not the observed `TypeError`.
- A08: `routes/dataset.py:20` expiry and `:112` deletion of all prior sources belonging to the same session.
- A09: `services/dataset_service.py:53` compared with `services/incoming_pipeline.py:15` missing-value definitions.
- A10: file parser error propagation through `routes/dataset.py:102` and generic response handling in `static/js/upload.js:7`.

## Design and workflow findings

These are visual/code-review findings, distinct from the reproduced failures above.

1. **The primary action is easy to miss.** The preview, pagination, statistics and optional details precede “Clean and add data.” In the tested desktop preview the action is below the initial viewport. Keep the requested statistics below the table, but put a compact “150 ready · 1 duplicate · 1 excluded” action bar near the preview heading or in a sticky footer. Since cleaning already happens during preview, “Add 150 records” describes the remaining action more accurately.
2. **All columns are available, but difficult to navigate.** Wide desktop and mobile tables require horizontal scrolling. Keep access to every column as requested. Freeze identifying columns, use readable headings and offer an optional column chooser; do not silently remove data fields. Row editing currently relies on clicking a row, a title tooltip or keyboard focus. A visible “Select a row to view or edit” hint would improve discovery without restoring a Details column.
3. **Editing returns to an older workflow.** `static/js/data.js` opens `/api/records/<id>/edit`; `routes/review.py:87` creates a legacy review batch. `services/review_service.py:29` calls the older preprocessing path, while uploads use `incoming_pipeline.run`. The severity policies demonstrably differ. Use one versioned validation/cleaning service for upload, manual entry and editing, with a small edit form and explicit exception handling.
4. **Estimated values look like observations.** The tested cleaned preview displayed identical precise latitude/longitude values filled from a historical median, with the imputation flags located elsewhere in the wide table. The map service correctly excludes flagged coordinates; the table can still mislead. Show “Unknown location” or an unmistakable estimated label. Prefer leaving operational coordinates unknown; any analytic estimate should be separate from observed coordinates. Apply the same provenance distinction to other filled measurements.
5. **Recovery is not easy to find.** The main Data page has no import-history or batch-reversal control. Original files and audit information are already persisted in Oracle, which is a useful foundation. Add a compact import history with saved/excluded/duplicate counts, download of original and excluded rows, and correction/re-upload of exceptions. A guarded “Undo this import” must preserve history and detect later edits or references before reversing anything.
6. **Mobile layout fits, but consumes space.** At 390px wide the expanded navigation takes roughly the first 340px of the page. The table stays within its scroll container, but the user reaches meaningful data late. Collapse navigation by default on small screens and keep key actions reachable.
7. **Some visual consistency remains unfinished.** Historical rows display a mixture of ISO dates and slash-formatted dates. Standardize display formatting without rewriting ambiguous historical dates blindly. The tested sidebar still says “CCDRMC Accident Monitoring System”; reconcile that branding with the requested MDRRMC naming.

## Data science and agency usefulness

- **Do not equate a saved new column with an active analysis feature.** The association-rule pipeline uses seven fixed fields (`arm/pipeline.py:29,150`). New fields labeled “Analysis candidate” are stored but do not automatically affect those rules. Use plain labels: “Used in analysis,” “Saved for later,” and “Needs definition.” Activate new features only after defining their meaning, units, missingness, allowed values and appropriate encoding.
- **Keep the analysis unit explicit.** Generated `accident_id` values currently identify imported rows. They do not establish that two people belong to one unique crash. Preserve a separate incident identifier and person/record identifier. Label record counts accurately; do not invent an incident relationship from date and location alone.
- **Track estimated versus observed values.** Batch-median filling can change the apparent distribution and, as reproduced, duplicate detection. Store the original value, final value, transformation rule/version and whether it was filled. Evaluate analysis with and without estimates where relevant. Do not infer negative findings merely because information was absent.
- **Measure quality before and after cleaning.** Useful checks include unknown dates/times, unresolved outcome descriptions, missing barangay, unmatched categories, numeric conversion failures, duplicates within the file and against saved records, and percentage filled. A single “ready” count is insufficient evidence of analytical quality.
- **Validate mappings against agency examples.** A fuzzy score of 85 is a configuration, not proof of correctness. Build an agreed reference set containing typos, local geography, vehicle combinations, negated descriptions and uncertain outcomes. Track false category merges and severity errors by rule version.

## Keep, add, simplify

| Keep | Add | Remove or simplify |
|---|---|---|
| Immediate Dataset preview; Original/Cleaned tabs | Visible summary and “Add N records” action | Technical parser messages and internal type names in routine guidance |
| Show 10/25/50/100 entries at left; search at right | Import history and recoverable exceptions | Mandatory review of every valid row; review exceptions only |
| Access to all data columns | Visible marking of estimates and corrected values | Separate cleaning policies for file imports and record edits |
| Automatic duplicate skipping and excluded-row download | One source-level date clarification only when necessary | A manual outcome selector whose value can silently be overwritten |
| Report downloads in Overview | Guarded batch reversal and per-record provenance | Long explanatory prose around routine actions; keep technical details expandable |
| Atomic Oracle publication and original-file retention | Staff-specific accounts if multiple administrators will operate the system | Requiring an administrator to understand database/parser configuration during upload |

## Recommended implementation order and acceptance gates

### 1. Correctness first

Fix A01–A06 and unify the cleaning contract across upload/manual/edit. Turn the diagnostic fixtures into regression tests with explicit expected results. Acceptance:

- Text fields such as `damage_type` survive unchanged unless an intentional, auditable normalization applies.
- Temporal features agree with the parsed date/time; absent Excel time remains unknown.
- Ambiguous and conflicting severity descriptions are not published as certain outcomes without resolution.
- Re-importing the same source rows adds zero duplicates even if another batch has different medians; different casualties remain separate.
- Invalid numeric inputs produce actionable validation results, not HTTP 500.
- Date conventions are explicit for ambiguous values.

### 2. Make recovery and decisions simple

Implement the compact action bar, consistent quality counts, import history and exception correction. Keep the user's existing minimal Data controls. Acceptance: an administrator can upload, understand what will be added, add valid rows once, retrieve exceptions later and correct only those exceptions without a technical explanation.

### 3. Agency readiness

Agree field definitions and outcome rules with the agency; add role-specific accounts if required, test backup restoration and controlled batch reversal, then exercise concurrent uploads and larger realistic files. Use a small agency-labeled dataset to compare original, cleaned, saved, exported and analysed values end to end before wider rollout.

## Performance and limitations

The latest pure preparation probes took about **0.10 seconds for 150 rows** and **0.59 seconds for 1,000 rows** on this machine. They exclude Oracle saving, mining, network/browser rendering and concurrent users. Although the endpoint allows up to 100,000 rows, this audit did not certify that size. The browser test exercised actual save and export in rollback-only transactions; it did not test process crashes, production commit recovery or multiple application workers.

Screenshots: [dataset preview](../tmp/qa/dataset-preview.png), [all data](../tmp/qa/dataset-all-data.png), [mobile](../tmp/qa/dataset-mobile.png). The mobile image includes temporary test records inside the transaction; those changes were rolled back.

Reproduce the non-writing probes from the `roadwatch` directory with `.\.venv\Scripts\python.exe scripts/alpha_data_audit.py`. The script forces CSV mode in its own process and uses isolated HTTP clients; it does not publish records. Results are written to `tmp/alpha/probe-results.json`.
