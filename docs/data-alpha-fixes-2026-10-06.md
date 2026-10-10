# Data alpha fixes — 6 October 2026

The Data workflow remains upload → preview → add valid records. The alpha audit's reproduced correctness defects have regression coverage, and the following fixes are implemented.

## Cleaning and validation

- New text such as `damage_type` is no longer mistaken for age. Date-derived month/day/year features keep their intended types.
- Negated and uncertain injury wording stays unresolved. Conflicting supplied and derived outcomes are preserved separately and excluded until resolved. Manual entry/editing offers an explicit confirmation of a verified outcome; selecting a severity alone does not silently override a conflict.
- Date-only Excel cells no longer create midnight accidents. Explicit time values, including midnight, remain supported.
- Ambiguous numeric dates trigger one file-level format choice. They are not assigned an assumed date or added until the administrator chooses the convention. ISO dates and unambiguous dates need no choice.
- Stable source fingerprints are stored before imputation. Duplicate detection is no longer changed by a different batch median. Different casualty/source identifiers remain part of record identity.
- Oversized numbers cannot crash integer casting. Invalid values are retained in the original input, and problematic rows are excluded with a reason while other valid rows remain usable.
- Intake plausibility defaults are age 0–130 and speed 0–400. These are conservative software checks, not clinical or legal definitions. `speed_kmh` uses the same range; generic `speed` requires the administrator to verify its unit when flagged. Agency-specific ranges/units should be agreed before adding further numeric fields; the current definitions are in `services/incoming_pipeline.py:NUMERIC_RANGES`.
- Missing counts consistently include empty and unknown markers. Median-filled numbers carry an `estimated_fields` marker and display an Estimated badge. Missing coordinates stay null; operational locations are not fabricated by a median.
- Independent uploads no longer invalidate each other's previews. Corrupt Excel errors tell the administrator how to save and retry a valid file.
- Uploads, manual entry, inline edits and the retained legacy review service use the same versioned incoming cleaning engine (`dataset-v3`).

## Data workspace

- “Add N records” is near the top of the preview beside ready/duplicate/excluded counts.
- Original/Cleaned tabs, all data columns, search, and 10/25/50/100-entry controls remain. The first column is frozen for horizontal scrolling.
- Record edits stay in a dialog on the Data page, with revision checks, automatic revalidation, preserved record identity and an audit history.
- Completed imports have a durable history with original-file and excluded-row downloads. New receipts retain the exact excluded originals and reasons; older receipts recover originals from their retained source file when possible.
- “Undo import” requires an explicit confirmation in the interface and is blocked if any imported record has changed, is missing, or has a pending edit. Original files, audit history and the monotonic ID counter remain. Mining and deletion occur in the same transaction; failures roll back.
- Navigation is compact on mobile and can be expanded. Sidebar branding now uses MDRRMC Echague. Report downloads remain in Overview.

## Verification

- Full automated suite, including local Oracle integration: **122 passed**.
- New regression tests reproduce the alpha failures and verify corrected behavior.
- Oracle tests cover durable receipts, downloads, inline editing, stale revisions, guarded undo, and rollback when analysis rebuilding fails.
- Browser verification covers the date-format choice, 152-row preview, pagination/search, 150 valid records added, excluded download, manual entry, inline editing, history download after leaving upload, protected undo, successful undo of an unchanged batch, Excel export and mobile containment.
- All Oracle verification writes were rolled back. No existing production records were reprocessed or deleted by this work.

## Operational limits

Completed import receipts are durable. Unsaved previews still expire after 30 minutes and are process-local; restarting the application requires re-uploading those files. The eight-preview limit remains. This work does not introduce staff accounts, new analysis model features, multi-worker coordination or a tested 100,000-row capacity guarantee. New columns are saved for reference until deliberately incorporated into the fixed analysis schema.

Existing records are not silently rewritten using the new rules. Correcting historical severity/date errors requires verified source evidence. Re-importing a record that predates source fingerprints relies on normalized stored values and available identifiers; the system cannot reconstruct originals that were never retained.
