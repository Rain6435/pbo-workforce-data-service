# API

Base URL in the compose setup: `http://127.0.0.1:8000`. Routes:
[`src/pbo_workforce/api/routes/`](https://github.com/Rain6435/pbo-workforce-data-service/tree/main/src/pbo_workforce/api/routes); response
models: [`src/pbo_workforce/api/schemas.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py).
When [`DOCS_ENABLED=true`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L46) (never in prod), the OpenAPI schema is at
`/openapi.json` and Swagger UI at `/docs`.

## Authentication

Every `/api/...` route requires the header `X-API-Key`. The server stores only
SHA-256 digests of accepted keys ([`API_KEY_HASHES`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L42), comma-separated) and compares
in constant time ([`require_api_key`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py#L37-L53) in [`src/pbo_workforce/api/security.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/security.py)).
Authentication runs before parameter validation, so an unauthenticated request
always gets 401.

| Situation | Response |
|---|---|
| Header missing or empty | `401 {"error": {"code": "unauthorized", "message": "Missing X-API-Key header"}}` |
| Key not recognized | `401 {"error": {"code": "unauthorized", "message": "Invalid API key"}}` |

`GET /health` needs no key.

## Trying the API in Swagger UI

Available when [`DOCS_ENABLED=true`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L46) (the [`.env.example`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.env.example) default; always off with
[`ENVIRONMENT=prod`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L45)).

1. Open `/docs`, for example <http://127.0.0.1:8000/docs>.
2. Click **Authorize** (padlock, top right). Under **APIKeyHeader**, enter the
   API key itself, not its digest, then click **Authorize** and **Close**. With
   [`.env.example`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/.env.example) the key is `local-dev-key-change-me`; otherwise use the key
   whose SHA-256 digest is in your [`API_KEY_HASHES`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L42).
3. Open an endpoint, click **Try it out**, fill in the parameters, and click
   **Execute**. For the FTE endpoint, [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py#L30) is required. `tenure` is a
   list: select one or more values (Ctrl-click or Cmd-click for several), or
   none for all tenures.

Swagger UI now sends `X-API-Key` with every request and shows the equivalent
`curl` command. The key is forgotten when the page is reloaded. Without it,
`/api` requests return 401 with `"Missing X-API-Key header"`.

## `GET /api/departments`

All departments, ordered by [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py#L30).

```sh
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/departments
```

```json
{
  "departments": [
    {
      "dept_id": 1,
      "dept_long": { "en": "Accessibility Standards Canada", "fr": "Normes d’accessibilité Canada" },
      "dept_short": { "en": "ASC", "fr": "NAC" }
    },
    {
      "dept_id": 20,
      "dept_long": { "en": "Canadian Polar Commission", "fr": "Commission canadienne des affaires polaires" },
      "dept_short": null
    }
  ]
}
```

[`dept_short`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py#L34) is `null` for the 10 departments whose source row has no short
names ([D21](assumptions.md#d21)). French names keep the typographic apostrophe `’`.

## `GET /api/departments/{dept_id}/fte`

Mean monthly FTE per quarter and tenure ([D3](assumptions.md#d3)), ordered by year and quarter, rounded
to 2 decimals ([D4](assumptions.md#d4)). Figures use the current version of the data only: values
revised or removed by a later import are kept as history in the database but
not served ([D16](assumptions.md#d16)). Quarters are calendar quarters unless the server sets
[`QUARTER_BASIS=fiscal`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py#L44) ([D2](assumptions.md#d2)).

| Parameter | In | Type | Rules |
|---|---|---|---|
| [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py#L30) | path | integer | 1 to 2147483647 |
| `year` | query | integer, optional | 2000 to 2100; year of the quarter |
| `tenure` | query | repeatable, optional | `indeterminate`, `term`, `casual`, `student`, `missing`; case-insensitive; default all |

```sh
curl -H "X-API-Key: $KEY" http://127.0.0.1:8000/api/departments/1/fte
```

```json
{
  "fte_per_quarter": [
    { "year": 2021, "quarter": 4, "indeterminate": 30.13, "term": 8.18, "casual": 0.67, "student": 0.73, "missing": 0.0 },
    { "year": 2022, "quarter": 1, "indeterminate": 29.93, "term": 7.07, "casual": 2.6, "student": 1.0, "missing": 0.0 }
  ]
}
```

With filters, only the selected tenure keys appear; `year` and `quarter` always
do. Keys keep the fixed order above, and repeated values are ignored.

```sh
curl -H "X-API-Key: $KEY" "http://127.0.0.1:8000/api/departments/1/fte?year=2022&tenure=term&tenure=casual"
```

```json
{
  "fte_per_quarter": [
    { "year": 2022, "quarter": 1, "term": 7.07, "casual": 2.6 },
    { "year": 2022, "quarter": 2, "term": 5.64, "casual": 2.47 },
    { "year": 2022, "quarter": 3, "term": 5.31, "casual": 1.67 },
    { "year": 2022, "quarter": 4, "term": 3.96, "casual": 1.93 }
  ]
}
```

A year with no data returns `200 {"fte_per_quarter": []}`.

### RCMP and CAF

"Royal Canadian Mounted Police - Members" and "Canadian Armed Forces" report
headcount only, so their FTE endpoint returns `200 {"fte_per_quarter": []}` ([D11](assumptions.md#d11)).
This is a known limitation, listed as a question for analysts in
[assumptions.md](assumptions.md). "Royal Canadian Mounted Police" (civilian
staff, a separate department) does have FTE.

## Errors

Every error has the same body ([D13](assumptions.md#d13), [`src/pbo_workforce/api/errors.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py)):

```json
{ "error": { "code": "department_not_found", "message": "No department with id 999" } }
```

| Status | `code` | When |
|---|---|---|
| 401 | [`unauthorized`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py#L23) | Missing or wrong API key |
| 404 | [`department_not_found`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/departments.py#L75) | [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py#L30) in range but unknown |
| 404 | [`not_found`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py#L23) | Unknown path |
| 405 | [`method_not_allowed`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py#L23) | Wrong method |
| 422 | [`invalid_request`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py#L56) | Invalid path or query value. The message lists each problem, for example `query.year: Input should be greater than or equal to 2000`. |
| 500 | [`internal_error`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py#L73) | Unexpected error. The message contains only a reference ID; the traceback is logged server-side under that ID. |
| 503 | [`unavailable`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/health.py#L24) | `/health` could not reach the database |

## `GET /health`

`200 {"status": "ok"}` if the database answers [`SELECT 1`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/health.py#L22), otherwise
`503` with the error body above. Unauthenticated, for probes.

## Response headers

All responses carry `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and (except `/docs`)
`Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. No CORS
headers are sent.
