# PBO Workforce Data Service

A prototype backend for the Parliamentary Budget Officer. It imports federal
workforce data (Federal Public Service, RCMP, CAF, and the department list) from
an Excel workbook into PostgreSQL, validating and standardizing every row. It
serves departments and quarterly FTE by tenure through a small, authenticated
REST API. Every quarantined row and warning is kept, with its Excel row number,
so analysts can trace each figure back to the source.

This site is the technical documentation. To install and run the service, see
the [README on GitHub](https://github.com/Rain6435/pbo-workforce-data-service#readme),
which covers both Docker Compose and a step-by-step setup without Docker.

```sh
cp .env.example .env
docker compose up --build          # then open http://127.0.0.1:8000/docs
```

## Suggested reading order

Decisions and data findings come before the architecture, because they explain
why the code looks the way it does. Decision IDs (D1, D2, ...) link to their
entry in [Assumptions and decisions](assumptions.md) wherever they appear.

| # | Read | Answers | Time |
|---|---|---|---|
| 1 | [Assumptions and decisions](assumptions.md) | Which decisions were made, why, with examples from the data, and what is still open for analysts? | 15 min |
| 2 | [Import process](import.md) | How is the data validated, and what happened to the real file? | 5 min |
| 3 | [API](api.md) | What do the endpoints return, and how do I try them (curl, Swagger)? | 5 min |
| 4 | [Architecture](architecture.md) | How is the code organized, and why this stack? | 5 min |
| 5 | [Data model](data-model.md) | Which tables, constraints, and indexes exist, and why? | 5 min |
| 6 | [Security](security.md) | Which risks were identified, and how were they prioritized? | 5 min |
| 7 | [Design questions](design-questions.md) | Written answers to design questions Q1 to Q3 | |

[AI usage](ai-usage.md) describes how AI tools were used.

**Short on time:** read 1 and 3.

**Reviewing the code:** start with
[`validate_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)
(the data rules),
[`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py)
(the quarterly FTE query), and
[`api/security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py)
(authentication), then their tests in
[`test_validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
[`test_workforce_repo.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py),
and [`test_security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_security.py).

## Where each evaluation criterion is demonstrated

| Criterion | Where |
|---|---|
| Secure backend / API / database design | Hashed API keys and constant-time comparison ([`api/security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py)), read-only [`pbo_api`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) limited to departments and the [`workforce_current`](data-model.md#workforce_current-view) view, and no-DDL [`pbo_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) ([`migrations/versions/0002_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py), [`0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py), [`tests/integration/test_db_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_db_roles.py)), per-process credentials ([`config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py)), [Security](security.md) |
| Scalable design | Monthly grain with quarters computed in SQL ([`repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py)), partial index for the FTE query over current rows only ([`migrations/versions/0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py)), streaming reader and chunked inserts ([`ingest/reader.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/reader.py), [`ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py)) |
| Requirements analysis in an existing environment | Every data problem profiled and tested ([`tests/integration/test_import_real_file.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py)), decisions and open questions in [Assumptions and decisions](assumptions.md) |
| Clear technical documentation | This site, docstrings explaining *why*, decision IDs ([D1](assumptions.md#d1) to [D22](assumptions.md#d22)) cited in code and tests |
| Attention to detail and quality | Strict pyright with no suppressions, 267 tests on real PostgreSQL, reconciliation in every import ([`ingest/report.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py)), migrations checked against models ([`tests/integration/test_migrations.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_migrations.py)) |
| Client service orientation | Import report with Excel row numbers and raw values for each quarantined row ([`import_rejection`](data-model.md#import_rejection-import_warning)), history of every revised or removed figure with a change list per import ([D16](assumptions.md#d16)), consistent error bodies, bilingual names preserved exactly |
| Collaboration | Questions for analysts in [Assumptions and decisions](assumptions.md#questions-for-analysts-by-priority), reviewed alias map ([`ingest/aliases.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/aliases.py)), declarative sheet specs for new sources ([`ingest/sources.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py)) |

Source code: [github.com/Rain6435/pbo-workforce-data-service](https://github.com/Rain6435/pbo-workforce-data-service).
