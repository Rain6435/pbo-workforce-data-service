# Design questions

## Q1: Scaling from thousands to tens of millions of records

The design scales in shape: monthly grain, quarters computed in SQL, provenance and version columns, and partial indexes over current rows. But three parts were deliberately built for 44,000 rows and would change.

First, the import would move from Python loops to set-based SQL. Today _load_sheet holds a sheet's accepted rows in memory and diff_snapshot compares them in Python. At this scale I would stream the source into an unlogged staging table with COPY, apply the validate_row rules as SQL where they translate (date, tenure, null and negative checks), and compute the version changes as joins between staging and current rows. The single transaction would become one per source or per period range, each recorded in import_batch, so a failed run resumes instead of restarting. The input itself should become CSV, Parquet or an API rather than Excel.

Second, storage: partition workforce_monthly by year, and move closed versions to a history partition so current queries never touch them.

Third, reads: precompute quarterly figures in a materialized view refreshed after each import, and cache API responses keyed by batch, since data only changes when a batch lands. A read replica handles growth in analyst traffic.

## Q2: External API source with daily updates and historical revisions

### (a) Automating synchronization while ensuring data quality

A scheduled job pulls the source daily. It uses a "changed since" query if the API offers one, and otherwise a full snapshot, which the importer already handles (D16). Each response is stored raw and unchanged, with its hash, before any processing, so any day can be replayed and the hash makes reruns idempotent.

Processing reuses what exists: a schema check like SheetSpec, row validation and quarantine, versioning that keeps every revision with its old and new values, and reconciliation. I would add release gates: a sharp drop in row counts, an unusual volume of revisions, or a failed reconciliation holds the batch and alerts someone instead of publishing it. Retries with backoff, timeouts, and an alert when a run fails or doesn't happen at all complete the job.

### (b) Working with analysts so the change fits their workflows

The risk for analysts is figures changing under published work. I would add an as_of parameter so a script can pin the data version its analysis used, publish a short change log with each release (the import report already lists every revision), and flag revisions that touch periods analysts have published. Before switching sources, I would run the old and new feeds in parallel for a few weeks and review the differences with analysts.

The revision policy should be agreed with them, not imposed: how far back revisions may go, and whether published versions are frozen. This prototype already works that way. Decisions that affect figures are listed as questions for analysts instead of being settled silently.

### (c) Reviewing a colleague's pull request that implements the sync

I would review in order of impact on published figures and how hard a mistake is to reverse:
1. Data integrity: revisions never overwrite history; each run is transactional and idempotent; partial failures can't publish half a day; counts reconcile.
2. Security: credentials stored as secrets, TLS verification on, a least-privilege database role, external data validated as untrusted input.
3. Failure behaviour: timeouts, retries, rate limits, pagination, alerting.
4. Tests: recorded API responses including revisions, and contract tests that catch changes in the source format.
5. Observability, then readability and style.

I'd phrase comments as questions, explain the risk behind each request, and ask for the work in small pull requests.

## Q3: Direct use from Power BI and Python

Both tools work best with flat tables, so the main additions are data shapes rather than features:
- A long-format export of monthly rows (department, month, tenure, headcount, FTE), as CSV or Parquet, plus pagination on list endpoints.
- For Power BI: read-only database views for direct queries, such as the existing workforce_current plus a quarterly view, under a reporting role. Use Entra ID sign-in rather than API keys, so scheduled refresh works in the Power BI service.
- For Python: a small client that returns pandas DataFrames, an example notebook, and the published OpenAPI spec.
- A metadata endpoint: data dictionary, current batch and its date, quarter basis, and links to release notes.

Finally, I'd let analyst feedback prioritize the items already identified: headcount for RCMP and CAF (D11), as_of (D16), and monthly data.

## Hooks in the code

Places in the implementation that the answers can refer to:

- [`import_batch`](data-model.md#import_batch) (file hash, status, per-sheet counts) and [`workforce_monthly.import_batch_id`](data-model.md#workforce_monthly): batch-level lineage. See [`src/pbo_workforce/db/tables.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/db/tables.py), [`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) → [`run_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py).
- Provenance columns [`source_sheet`](data-model.md#workforce_monthly), [`source_row`](data-model.md#workforce_monthly) on [`workforce_monthly`](data-model.md#workforce_monthly); [`import_rejection`](data-model.md#import_rejection-import_warning) and [`import_warning`](data-model.md#import_rejection-import_warning) with raw values.
- [`SheetSpec`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py) and [`WORKFORCE_SHEETS`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py) in [`src/pbo_workforce/ingest/sources.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py): declarative source definitions and schema-drift detection.
- [`validate_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) and [`RejectReason`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) / [`WarningCode`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) in [`src/pbo_workforce/ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py): pure validation, independent of the input format.
- [`QuarterBasis`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) and [`quarter_offset_months`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) in [`src/pbo_workforce/domain/period.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py): the quarter definition as configuration.
- Monthly grain with quarters computed in SQL: [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) in [`src/pbo_workforce/repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py); partial index [`ix_workforce_monthly_current_department_id_source_period`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py) (current rows only).
- Row versions ([D16](assumptions.md#d16)): [`diff_snapshot`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py) in [`src/pbo_workforce/ingest/versioning.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py), closed versions with [`valid_to_batch_id`](data-model.md#workforce_monthly) / [`closed_reason`](data-model.md#workforce_monthly), the [`workforce_current`](data-model.md#workforce_current-view) view, and the change list in each import report; the advisory lock in [`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py).
- Stable department IDs ([D5](assumptions.md#d5)), departments kept when dropped from the sheet ([D20](assumptions.md#d20)), and [`department_alias`](data-model.md#department_alias).
- [`ImportReport.to_json`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py) and the reconciliation check in [`src/pbo_workforce/ingest/report.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py).
- Least-privilege roles in [`migrations/versions/0002_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py), with the API limited to the [`workforce_current`](data-model.md#workforce_current-view) view by [`0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py); per-process settings in [`src/pbo_workforce/config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py).
