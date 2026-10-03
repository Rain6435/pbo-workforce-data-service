# PBO Workforce Data Service

A prototype backend for the Parliamentary Budget Office (PBO) that imports federal
workforce data (Federal Public Service, RCMP, CAF, and the department list) from
`data/data.xlsx` into PostgreSQL, validating and standardizing every row.
It serves departments and quarterly FTE by tenure through a small, authenticated
REST API.
Every quarantined row and warning is kept, with its Excel row number, so analysts
can trace each figure back to the source.

Technical documentation: **<https://rain6435.github.io/pbo-workforce-data-service/>**.

There are two ways to run it:

- **[Docker Compose](#quick-start-docker-compose):** one command, needs only
  Docker.
- **[Without Docker](#running-without-docker):** Python 3.12, uv, and a local
  PostgreSQL, with step-by-step instructions.

## Technology stack

| Concern | Choice | In one line |
|---|---|---|
| Language | Python 3.12 | Strong data tooling, readable, and the language analysts already script in |
| API | FastAPI + Pydantic v2 | Request validation and an OpenAPI schema generated from typed models |
| Database | PostgreSQL 16 | Transactional DDL, CHECK constraints and enums, roles for least privilege; Power BI and Python connect to it directly |
| Data access | SQLAlchemy 2.0 (typed) + psycopg 3 | Composable, parameterized SQL with type-checked models |
| Migrations | Alembic | Versioned, reversible schema and role changes |
| Excel reading | openpyxl (read-only mode) | Streams rows; no pandas needed for a row-by-row validator |
| Tooling | uv, ruff, pyright (strict), pytest | Locked installs, lint, static types, tests on real PostgreSQL |
| Packaging | Docker + Docker Compose | One command for evaluators; same image for API, import, and migrations |

Rationale and alternatives considered:
[docs/architecture.md](docs/architecture.md#technology-choices).

## Quick start (Docker Compose)

```sh
cp .env.example .env          # local-only throwaway values; see comments inside
docker compose up --build     # db -> migrate -> import -> api
```

When [`api`](docker-compose.yml#L63) is healthy (the import takes about 20 s):

```sh
KEY=local-dev-key-change-me   # the key whose SHA-256 digest is in .env.example

curl http://127.0.0.1:8000/health
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/departments
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/departments/1/fte?year=2022&tenure=term&tenure=casual"
```

Interactive docs: <http://127.0.0.1:8000/docs> (enabled by [`DOCS_ENABLED=true`](src/pbo_workforce/config.py#L46) in
[`.env.example`](.env.example); always off when [`ENVIRONMENT=prod`](src/pbo_workforce/config.py#L45)). Click **Authorize**, enter
the key `local-dev-key-change-me`, then use **Try it out** on any endpoint; see
[docs/api.md](docs/api.md#trying-the-api-in-swagger-ui). The compose services are
described at the top of [`docker-compose.yml`](docker-compose.yml).

## Running without Docker

Everything runs natively with Python and a local PostgreSQL. Allow about 10
minutes the first time. Run every command **from the repository root**: the
application reads `.env` from the current directory.

### 1. Install the prerequisites

| Tool | Version | How to check | Install |
|---|---|---|---|
| Python | 3.12 or newer | `python3 --version` | <https://www.python.org/downloads/> |
| uv (Python package manager) | any recent | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` (Windows); see <https://docs.astral.sh/uv/> |
| PostgreSQL | 16 (15+ works) | `psql --version` | Linux: `sudo apt install postgresql`; macOS: `brew install postgresql@16` or Postgres.app; Windows: the EDB installer from <https://www.postgresql.org/download/> |

PostgreSQL must be running and listening on `localhost:5432` (the default after
installation).

### 2. Create the database owner and the two databases

Connect to PostgreSQL as its administrator and create the role that owns the
schema, the application database, and the test database. The passwords below
match [`.env.example`](.env.example); they are local-only throwaway values.

```sh
# Linux:          sudo -u postgres psql
# macOS (brew):   psql postgres
# Windows:        psql -U postgres   (password chosen during installation)
```

```sql
CREATE ROLE pbo_admin LOGIN CREATEDB CREATEROLE PASSWORD 'local-dev-only-admin';
CREATE DATABASE pbo_workforce OWNER pbo_admin;
CREATE DATABASE pbo_workforce_test OWNER pbo_admin;
```

`pbo_admin` needs `CREATEROLE` because the second migration creates two
restricted roles: [`pbo_api`](migrations/versions/0002_roles.py#L33) (used by the API; reads only departments and current
figures, never writes) and [`pbo_import`](migrations/versions/0002_roles.py#L34)
(read/write without schema changes, used by the importer). See
[docs/security.md](docs/security.md).

### 3. Configure the environment

```sh
cp .env.example .env            # Windows (PowerShell): Copy-Item .env.example .env
```

[`.env.example`](.env.example) is set up for the Docker database on port **5433**. For a
local PostgreSQL, change the port to **5432** in the four `*_DATABASE_URL` lines:

```sh
sed -i.bak 's/127.0.0.1:5433/127.0.0.1:5432/' .env   # or edit the four lines by hand
```

The relevant part of `.env` should then read:

```dotenv
MIGRATIONS_DATABASE_URL=postgresql+psycopg://pbo_admin:local-dev-only-admin@127.0.0.1:5432/pbo_workforce
DATABASE_URL=postgresql+psycopg://pbo_api:local-dev-only-api@127.0.0.1:5432/pbo_workforce
IMPORT_DATABASE_URL=postgresql+psycopg://pbo_import:local-dev-only-import@127.0.0.1:5432/pbo_workforce
TEST_DATABASE_URL=postgresql+psycopg://pbo_admin:local-dev-only-admin@127.0.0.1:5432/pbo_workforce_test
```

You do not create [`pbo_api`](migrations/versions/0002_roles.py#L33) or [`pbo_import`](migrations/versions/0002_roles.py#L34) yourself: the migration in step 5
creates them with the passwords written in [`DATABASE_URL`](src/pbo_workforce/config.py#L39) and
[`IMPORT_DATABASE_URL`](src/pbo_workforce/config.py#L77). To use other passwords, change them in these URLs (and
the `pbo_admin` password in both the SQL above and the two `pbo_admin` URLs).

### 4. Install the dependencies

```sh
uv sync                         # creates .venv with the exact versions in uv.lock
```

### 5. Create the schema and roles

```sh
uv run alembic upgrade head     # prints nothing on success
uv run alembic current          # should print: 0003 (head)
```

### 6. Import the workbook

```sh
uv run pbo-import data/data.xlsx
```

This takes about 20 seconds and prints the import report: rows read, accepted,
and rejected per sheet, every rejected row with its Excel row number, what the
import changed compared with the stored data, and two checks at the end:
`Reconciliation (...): OK` and `Versions (...): OK`. Running it again prints
"already imported"; add [`--force`](src/pbo_workforce/ingest/cli.py#L26) to import the same file again (nothing
changes). Details:
[docs/import.md](docs/import.md).

### 7. Start the API

```sh
uv run uvicorn --factory pbo_workforce.api.app:create_app --reload
```

The API listens on <http://127.0.0.1:8000>. Leave it running and use a second
terminal.

### 8. Try it

The API key matching [`.env.example`](.env.example) is `local-dev-key-change-me`.

```sh
curl http://127.0.0.1:8000/health
curl -H "X-API-Key: local-dev-key-change-me" http://127.0.0.1:8000/api/departments
curl -H "X-API-Key: local-dev-key-change-me" "http://127.0.0.1:8000/api/departments/1/fte?year=2022"
```

On Windows PowerShell, use `curl.exe` instead of `curl`, or:

```powershell
Invoke-RestMethod -Headers @{ "X-API-Key" = "local-dev-key-change-me" } http://127.0.0.1:8000/api/departments
```

In a browser: open <http://127.0.0.1:8000/docs>, click **Authorize**, enter
`local-dev-key-change-me`, then **Try it out** on an endpoint
([details](docs/api.md#trying-the-api-in-swagger-ui)).

### 9. Run the tests (optional)

```sh
uv run pytest                   # 267 tests, about 45 s, uses pbo_workforce_test
```

### Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `password authentication failed for user "pbo_admin"` | The password in the `pbo_admin` URLs differs from the one in `CREATE ROLE`. Reset it in `psql`: `ALTER ROLE pbo_admin PASSWORD 'local-dev-only-admin';` |
| `connection refused` on port 5432 or 5433 | PostgreSQL is not running, or `.env` still points at port 5433 (the Docker database). See step 3. |
| `permission denied to create role` | `pbo_admin` lacks `CREATEROLE`: `ALTER ROLE pbo_admin CREATEROLE;` |
| `Field required ... database_url` (or a similar settings error) | `.env` is missing or the command was not run from the repository root. |
| `401 Missing X-API-Key header` | Send the `X-API-Key` header, or click **Authorize** in `/docs`. |
| Tests stop with [`TEST_DATABASE_URL is not set`](tests/conftest.py#L33) or `Refusing to use ...` | Set [`TEST_DATABASE_URL`](tests/conftest.py#L27) in `.env` to a database whose name ends in `_test`. |

### Using the Docker database with the local tools

To skip installing PostgreSQL but still run Python natively: start only the
database with `docker compose up -d db`, keep [`.env.example`](.env.example)'s port 5433, and
follow steps 4 to 9.

## Tests and checks

```sh
uv run ruff check && uv run ruff format --check   # lint, format
uv run pyright                                    # strict type checking
uv run pytest                                     # against real PostgreSQL
uv run pytest -m "not slow"                       # skip the full data.xlsx import
uv run pytest --cov=pbo_workforce --cov-report=term-missing
```

Tests use [`TEST_DATABASE_URL`](tests/conftest.py#L27) (a database whose name must end in `_test`; the
suite resets its schema). Each test runs in a transaction that is rolled back.
CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs lint and type
checks, the tests with coverage against a PostgreSQL service container,
`pip-audit`, and `docker compose up` followed by API smoke tests.

## Project layout

```
src/pbo_workforce/
  config.py          per-process settings (API, importer, migrations)
  domain/            tenure and period types; pure, no I/O
  ingest/            reader -> normalize -> validate -> compare -> load -> report; pbo-import CLI
  db/                SQLAlchemy models and engine factory
  repositories/      read queries used by the API (incl. quarterly FTE SQL)
  api/               FastAPI app factory, auth, errors, schemas, routes
migrations/          Alembic: 0001 schema, 0002 least-privilege roles, 0003 row versions
tests/               unit/, integration/, api/; factories.py builds .xlsx files
docker/initdb/       creates the test database in the compose db
docs/                see below
```

## Known limitations and next steps

All required features are implemented. What the prototype does not do yet, and
how each item would be completed:

| Limitation | How it would be completed |
|---|---|
| RCMP and CAF report headcount only, so their FTE endpoint returns an empty list ([D11](https://rain6435.github.io/pbo-workforce-data-service/assumptions/#d11)) | Their headcounts are already stored; add a headcount option (for example `measure=headcount`) once analysts confirm they want it |
| The API serves current figures only; revised and removed values are kept but not exposed ([D16](https://rain6435.github.io/pbo-workforce-data-service/assumptions/#d16)) | Add an `as_of` parameter that reads the versions valid at a given import batch, so published figures can be reproduced |
| Some data rules await analyst confirmation: quarter basis, missing months, averaging ([questions for analysts](https://rain6435.github.io/pbo-workforce-data-service/assumptions/#questions-for-analysts-by-priority)) | Each rule lives in one place ([`QuarterBasis`](src/pbo_workforce/domain/period.py#L12-L20), [`fte_per_quarter`](src/pbo_workforce/repositories/workforce.py#L35-L105)), so an answer is a small, tested change |
| No TLS, rate limiting, single sign-on, audit logging or backups in the service | Provided by the platform (reverse proxy, gateway, identity provider, managed PostgreSQL); see [Left to the platform](https://rain6435.github.io/pbo-workforce-data-service/security/#left-to-the-platform) |
| No size limit on imported workbooks; no automated dependency updates | Check the file size in [`open_workbook`](src/pbo_workforce/ingest/reader.py#L36-L50); enable Dependabot |
| Excel input only, loaded in one transaction, sized for the provided file | Scaling plan in [design question Q1](https://rain6435.github.io/pbo-workforce-data-service/design-questions/#q1-scaling-from-thousands-to-tens-of-millions-of-records): staging tables loaded with `COPY`, set-based comparison, partitioning |

## Documentation

**Full documentation: <https://rain6435.github.io/pbo-workforce-data-service/>**

The site gives a suggested reading order for reviewers and shows where each
evaluation criterion is demonstrated. Its pages, also readable here on GitHub
under [`docs/`](docs/):

| Page | Contents |
|---|---|
| [Assumptions and decisions](https://rain6435.github.io/pbo-workforce-data-service/assumptions/) | Design decisions D1 to D22 with examples from the data, findings, questions for analysts |
| [Import process](https://rain6435.github.io/pbo-workforce-data-service/import/) | Pipeline stages, rejection and warning codes, reconciliation, idempotency, the real import report, flow diagram |
| [API](https://rain6435.github.io/pbo-workforce-data-service/api/) | Endpoints, parameters, examples, errors, authentication, Swagger UI |
| [Architecture](https://rain6435.github.io/pbo-workforce-data-service/architecture/) | Layers, technology choices, request flow |
| [Data model](https://rain6435.github.io/pbo-workforce-data-service/data-model/) | ER diagram, tables, constraints, indexes |
| [Security](https://rain6435.github.io/pbo-workforce-data-service/security/) | Risks mitigated in code, ranked; what is left to the platform |
| [Design questions](https://rain6435.github.io/pbo-workforce-data-service/design-questions/) | Written answers to Q1 to Q3 |
| [AI usage](https://rain6435.github.io/pbo-workforce-data-service/ai-usage/) | How AI tools were used |

To preview the site locally: `uv run --only-group docs mkdocs serve`, then open
<http://127.0.0.1:8000> (stop the API first, or add `-a 127.0.0.1:8001`). The
site is built from [`mkdocs.yml`](mkdocs.yml) and published by
[`.github/workflows/docs.yml`](.github/workflows/docs.yml).
