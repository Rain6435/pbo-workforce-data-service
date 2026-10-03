# Design questions

## Q1: Scaling from thousands to tens of millions of records

Much of the current design already holds up at that scale: data is stored monthly and quarters are computed in SQL ([`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py#L35-L105)), every row [records its source and version](data-model.md#workforce_monthly), and [partial indexes](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py#L78-L83) cover only current rows. Three parts, however, were built for the 44,000 rows in the provided file and would change.

First, the import would move from Python loops to set-based SQL. Today [`_load_sheet`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py#L265-L333) holds a sheet's accepted rows in memory and [`diff_snapshot`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py#L41-L67) compares them in Python.

At this scale I would stream the source into an unlogged staging table with [`COPY`](https://www.postgresql.org/docs/16/sql-copy.html), apply the [`validate_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py#L106-L168) rules as SQL where they translate (date, tenure, null and negative checks), and compute the version changes as joins between staging and current rows. `COPY` is PostgreSQL's bulk-load command: its documentation recommends it over a series of `INSERT` statements because it has [significantly less overhead for large data loads](https://www.postgresql.org/docs/16/populate.html#POPULATE-COPY-FROM), and psycopg, the driver already used here, [streams rows to it directly from Python](https://www.psycopg.org/psycopg3/docs/basic/copy.html).

Today the whole import runs in one transaction. At this scale I would commit each source or period range separately and record its progress in [`import_batch`](data-model.md#import_batch), so a failed run picks up where it stopped instead of starting over. I would also replace Excel with a format suited to large volumes, such as CSV or Parquet.

Second, storage: partition [`workforce_monthly`](data-model.md#workforce_monthly) by year, and move closed versions to a history partition so current queries never touch them.

Third, reads: precompute quarterly figures in a materialized view refreshed after each import, and cache API responses keyed by batch, since data only changes when a batch lands. A read replica handles growth in analyst traffic.

## Q2: External API source with daily updates and historical revisions

### (a) Automating synchronization while ensuring data quality

A scheduled job pulls the source daily. It uses a "changed since" query if the API offers one, and otherwise a full snapshot, which the importer already handles ([D16](assumptions.md#d16)). Each response is stored raw and unchanged, with its hash, before any processing, so any day can be replayed and the hash makes reruns idempotent.

Each update would go through the same pipeline as the Excel import: a schema check against a declared source definition (like [`SheetSpec`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py#L37-L46)), row validation with quarantine, versioning that keeps the old and new value of every revision, and a [check that every record received is either stored or quarantined](import.md#reconciliation).

Before publishing an update, the job would check that it looks plausible: a sharp drop in row count, an unusual number of revisions, or a failed check would hold the update and alert the team instead. The job itself would use timeouts and retries with backoff, and alert when a run fails or does not happen at all.

### (b) Working with analysts so the change fits their workflows

The risk for analysts is figures changing under published work. I would add an `as_of` parameter so a script can pin the data version its analysis used, publish a short change log with each release (the import report already lists every revision ([D16](assumptions.md#d16))), and flag revisions that touch periods analysts have published. Before switching sources, I would load the external API's data into a separate database for a few weeks, while analysts keep using the current data. I would then compare the figures both sources give for the same departments and months, go through the differences with analysts, and switch only once they are explained.

The revision policy should be agreed with them, not imposed: how far back revisions may go, and whether published versions are frozen. This prototype already works that way. Decisions that affect figures, such as the quarter basis ([D2](assumptions.md#d2)) or what a missing month means ([D3](assumptions.md#d3)), are listed as [questions for analysts](assumptions.md#questions-for-analysts-by-priority) instead of being settled silently.

### (c) Reviewing a colleague's pull request that implements the sync

I would review in order of impact on published figures and how hard a mistake
is to reverse:

1. **Data integrity**, because a wrong figure can reach a published analysis
   before anyone notices:
    - a revised figure is stored as a new version and the old value is kept;
    - each sync is applied in a single transaction, so a failure partway
      through publishes none of that update's changes;
    - processing the same update twice (for example on a retry) changes nothing;
    - every record received is
      [either stored or quarantined](import.md#reconciliation).
2. **Security**, because the job holds credentials and writes to the database
   unattended: credentials stored as secrets, TLS verification on, a
   [least-privilege database role](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py#L74-L114), and external data validated as untrusted
   input.
3. **Failure handling**, because the job runs daily with no one watching:
   timeouts, retries with backoff, rate limits, pagination that cannot silently
   skip a page, and an alert when a run fails.
4. **Tests**, because they keep items 1 to 3 true as the code changes: recorded
   API responses that include revisions, and tests that fail when the source's
   format changes.
5. **Observability**, so problems are seen quickly: logs and counts for every
   run. Then readability and style, which matter but are the easiest to fix
   later.

I'd phrase comments as questions, explain the risk behind each request, and, if
the pull request is large, suggest splitting it so each part can be reviewed
properly.

## Q3: Direct use from Power BI and Python

Both tools work best with flat tables, so the main additions are data shapes rather than features:

- A long-format export of monthly rows (department, month, tenure, headcount, FTE), as CSV or Parquet, plus pagination on list endpoints.
- For Power BI: read-only database views for direct queries, such as the existing [`workforce_current`](data-model.md#workforce_current-view) plus a quarterly view, under a reporting role. Use Entra ID sign-in rather than API keys, so scheduled refresh works in the Power BI service.
- For Python: a small client that returns pandas DataFrames, an example notebook, and the published OpenAPI spec.
- A metadata endpoint: data dictionary, current batch and its date, quarter basis, and links to release notes.

Finally, I'd let analyst feedback prioritize the items already identified: headcount for RCMP and CAF ([D11](assumptions.md#d11)), `as_of` ([D16](assumptions.md#d16)), and monthly data.
