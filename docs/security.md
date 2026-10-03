---
hide:
  - toc
---

# Security

The data is workforce statistics for federal organizations: not personal
information, but not published in this form either. The main concerns are
unauthorized access, the integrity of the figures analysts rely on, and not
leaking internals.

## Risk register

The risks below are mitigated in this code base, ranked by likelihood and
impact for a prototype running on an internal network behind a reverse proxy.

<div class="risk-register" markdown>

| Priority | Risk | Mitigation | Evidence |
|---|---|---|---|
| **1** | Unauthenticated access to the API | API key required on all `/api` routes; only SHA-256 digests configured; constant-time comparison over all digests; auth runs before validation; startup refuses `prod` without keys; several digests can be configured, so keys can be rotated without downtime | [`api/security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py) → [`require_api_key`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py); [`config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py) → [`Settings._safe_in_prod`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py); [`tests/api/test_security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_security.py) |
| **2** | SQL injection | Only SQLAlchemy Core/ORM with bound parameters; the one piece of DDL with a value (role passwords) is quoted by psycopg [`sql.Literal`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py); ruff `S` rules (S608) in CI | [`repositories/`](https://github.com/Rain6435/pbo-workforce-data-service/tree/main/src/pbo_workforce/repositories), [`migrations/versions/0002_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) → [`_execute`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) |
| **3** | Compromised API process can change data or read import internals | API connects as [`pbo_api`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py): SELECT on `department` and the [`workforce_current`](data-model.md#workforce_current-view) view only (no history, no import tables), sessions read-only, 5 s statement timeout; importer as [`pbo_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) without DDL; migrations alone use the owner | [`migrations/versions/0002_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py), [`0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py); [`tests/integration/test_db_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_db_roles.py) |
| **4** | Secrets leaked through the repository, image, or other containers | `.env` git-ignored and in [`.dockerignore`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.dockerignore); [`.env.example`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.env.example) holds only labelled local values; each process loads only its own URL ([D22](assumptions.md#d22)); compose passes each container only its variables | [`.gitignore`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.gitignore), [`.dockerignore`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.dockerignore), [`config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py), [`docker-compose.yml`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml) |
| **5** | Wrong figures from bad source rows | Validation and whole-row quarantine with reasons; warnings; reconciliation; one transaction; DB CHECK constraints; stable IDs; history of every revision, so a bad file can be traced and reverted by importing the previous one | [`ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py), [`ingest/versioning.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py), [`ingest/report.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py), [`0001_schema.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0001_schema.py), [`0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py); [`tests/integration/test_import_real_file.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py) |
| **6** | Information leakage in errors | One error body; 500 returns a reference ID only, details logged; failed imports store only the exception type for unexpected errors | [`api/errors.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py) → [`_handle`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py); [`test_unexpected_error_hides_details`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_departments.py); [`ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) → [`_record_failure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) |
| **7** | Malicious or malformed input file | Rejects non-xlsx files; reads only declared sheets and columns; header check; formulas are not evaluated ([`data_only=True`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/reader.py)); streaming read | [`ingest/reader.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/reader.py); [`tests/unit/test_reader.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_reader.py) |
| **8** | Vulnerable dependencies or base images | [`uv.lock`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/uv.lock) pins every package; [`pip-audit --strict`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.github/workflows/ci.yml) in CI; base images pinned by version and digest | [`.github/workflows/ci.yml`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.github/workflows/ci.yml) ([`audit`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.github/workflows/ci.yml)), [`Dockerfile`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/Dockerfile) |
| **9** | Container escape or privilege misuse | Non-root user (UID 10001), read-only root filesystem, all capabilities dropped, [`no-new-privileges`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml), slim pinned base, no build tools in the runtime image | [`Dockerfile`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/Dockerfile), [`docker-compose.yml`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml) |
| **10** | Browser-based misuse of responses (sniffing, framing, caching) | `nosniff`, `X-Frame-Options: DENY`, strict CSP, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`; no CORS | [`api/security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py) → [`SecurityHeadersMiddleware`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py); [`test_security_headers_on_every_response`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_security.py) |
| **11** | API documentation exposing the surface in production | `/docs` and `/openapi.json` off unless [`DOCS_ENABLED`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py); startup refuses it with [`ENVIRONMENT=prod`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py) | [`api/app.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/app.py), [`config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py); [`test_docs_disabled_by_default`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_security.py) |
| **12** | Concurrent imports corrupting data | Transaction-scoped advisory lock | [`ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) → [`_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) |

</div>

## Left to the platform

These risks were identified but belong in shared infrastructure, where they are
done once for every service rather than re-implemented in each:

- **Transport encryption:** terminate TLS at the reverse proxy or API gateway.
  The compose file binds every port to 127.0.0.1 in the meantime.
- **Rate limiting:** at the gateway. API keys are long random tokens, so
  guessing is impractical, and the database's 5 s statement timeout already
  bounds the cost of one request.
- **Single sign-on:** for production, replace shared API keys with the
  organization's identity provider (for example Microsoft Entra ID), so access
  is tied to people and revoked centrally.
- **Audit logging** of who read what: at the gateway, once a log destination and
  retention policy exist.
- **Backups:** managed PostgreSQL point-in-time recovery. Imports already never
  delete or overwrite figures ([D16](assumptions.md#d16)), so a bad file can be reverted by importing the
  previous one.

Smaller known gaps in the prototype: no file-size or decompression-ratio limit on
imported workbooks (files come from a known source), no automated
dependency-update pull requests, and role passwords sent to PostgreSQL as
literal SQL by [`0002_roles.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py) (visible only if statement logging is on).

## Prioritization

Risks 1 to 6 were addressed first: they are the likeliest in any deployment, or
they would silently corrupt the figures (risk 5), and each costs little to fix in
the application. Risks 7 to 12 are less likely in this setting, but their
mitigations were cheap, so they were done too. Platform concerns were
deliberately not rebuilt inside the service.
