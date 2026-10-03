# Assumptions and design decisions

This page explains every judgment call made while turning `data/data.xlsx` into
a database and an API. You do not need to know the code to follow it. Each
decision starts with a one-line summary and a concrete example, most of them
taken from the real file. The technical details (alternatives, where it is
implemented, tests) follow for readers who want them.

Each decision has an ID used in code comments and tests. The log was kept up
to date throughout the work: [D1](#d1) to [D15](#d15) were set before implementation, from the
assignment and a first profile of the data; [D16](#d16) to [D22](#d22) were added during
implementation, as the data and the code raised new questions. Some earlier
decisions were revised along the way, and each says so. Data problems found in
the file and questions for analysts are at the end.

## Terms used on this page

| Term | Meaning |
|---|---|
| **Headcount** | Number of people employed, counted once each. |
| **FTE** (full-time equivalent) | Employment measured in full-time workloads: two half-time employees are 1.0 FTE. FTE can be fractional (`29.8`). |
| **Tenure** | Type of employment: *indeterminate* (permanent), *term* (fixed end date), *casual*, *student*, and *missing* (the employer did not record a tenure). RCMP and CAF report one *combined* figure. |
| **Source** / **sheet** | The workbook has four sheets: *Federal Public Service* (FPS, monthly headcount and FTE by tenure), *RCMP* and *CAF* (headcount only), and *Departments* (names in English and French). |
| **Row** | One line of a sheet, identified by its Excel row number (row 1 is the header). |
| **Quarantined** / **rejected** | A row that failed validation. It is not used in any figure, but it is kept, with its raw values and a reason, in the [`import_rejection`](data-model.md#import_rejection-import_warning) table and the import report. |
| **Warning** | A row that looks unusual but is accepted unchanged and flagged for review. |
| **Reporting month** | A month in which a department has at least one accepted FPS row. |
| **Version** | Imports never delete or overwrite a figure. When a later file changes or drops a row, the old row is *closed* and kept as history; the row in use is the *current* version. All figures use current versions ([D16](#d16)). |

---

<a id="d1"></a>

### D1: Monthly data is the source of truth

**In short:** the database keeps the figures exactly as the source reports them,
month by month; quarters are calculated only when someone asks for them.

**Example:** Accessibility Standards Canada (ASC) in December 2021 is stored as
three rows, one per tenure the source reported:

| Month | Tenure | Headcount | FTE |
|---|---|---|---|
| 2021-12 | indeterminate | 31 | 30.80 |
| 2021-12 | term | 9 | 7.33 |
| 2021-12 | student | 2 | 1.00 |

The figure for 2021 Q4 is computed from October, November, and December when
the API is called. If analysts later prefer fiscal quarters ([D2](#d2)) or a different
averaging rule ([D3](#d3)), only the query changes; nothing is re-imported.

- **Decision:** store one current row per department, month, tenure, and
  source (earlier versions are kept as history, [D16](#d16)); compute quarters when
  queried.
- **Rationale:** the quarter definition ([D2](#d2)) and the averaging rule ([D3](#d3)) stay
  changeable without re-importing, and monthly figures remain available.
- **Alternative:** store quarterly aggregates. Rejected: it fixes the definition
  in the data and loses detail.
- **Where:** [`workforce_monthly`](data-model.md#workforce_monthly) ([`migrations/versions/0001_schema.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0001_schema.py));
  [`src/pbo_workforce/repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) → [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py).

<a id="d2"></a>

### D2: Calendar quarters by default; fiscal implemented

**In short:** quarters are calendar quarters (January to March is Q1) unless
the server is configured for the federal fiscal year (April to March).

**Example:** the same month falls in different quarters depending on the basis:

| Month | Calendar quarter | Fiscal quarter |
|---|---|---|
| December 2021 | 2021 Q4 | 2021 Q3 (fiscal 2021-22) |
| March 2026 | 2026 Q1 | 2025 Q4 (fiscal 2025-26) |
| April 2026 | 2026 Q2 | 2026 Q1 (fiscal 2026-27) |

A fiscal year is labelled by the year it starts in, so fiscal 2025-26 is
`"year": 2025`. Switching is one setting, [`QUARTER_BASIS=fiscal`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py).

- **Decision:** [`QuarterBasis.CALENDAR`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) (Q1 = Jan to Mar) by default, set by
  [`QUARTER_BASIS`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py). [`QuarterBasis.FISCAL`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) (Q1 = Apr to Jun) is implemented. A
  fiscal year is labelled by the calendar year it starts in, so fiscal 2025-26 is
  `year: 2025` and March 2026 is 2025 Q4.
- **Rationale:** calendar quarters need no convention for labelling fiscal
  years, so they are the least surprising default. Both bases are one
  offset ([`quarter_offset_months`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py): 0 or 3) used by [`to_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) in Python and by
  the SQL in [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py).
- **Alternative:** hard-code calendar quarters. Rejected: government reporting
  commonly uses the fiscal year.
- **Where:** [`src/pbo_workforce/domain/period.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py); [`Settings.quarter_basis`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py)
  ([`src/pbo_workforce/config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py)). Tests: [`tests/unit/test_period.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_period.py) →
  [`test_fiscal_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_period.py); [`tests/integration/test_workforce_repo.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py) →
  [`test_fiscal_quarters`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py); [`tests/api/test_fte.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py) →
  [`test_quarter_basis_setting_switches_to_fiscal`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py).
- **Question for analysts (first to confirm):** calendar or fiscal quarters? If
  fiscal, label by starting year (2025 for 2025-26) or ending year?

<a id="d3"></a>

### D3: Quarterly FTE is the mean of monthly FTE over reporting months

**In short:** a quarter's FTE is the average of its monthly FTEs. A tenure with
no row in a month that the department did report counts as 0. A month with no
rows at all is left out of the average.

**Example 1, an absent tenure row.** ASC reported in all three months of 2021 Q4,
but had no Casual row in December:

| Tenure | Oct | Nov | Dec | 2021 Q4 |
|---|---|---|---|---|
| indeterminate | 29.80 | 29.80 | 30.80 | (29.80 + 29.80 + 30.80) / 3 = **30.13** |
| casual | 1.00 | 1.00 | *no row → 0* | (1.00 + 1.00 + 0) / 3 = **0.67** |

These are the values `GET /api/departments/1/fte` returns for 2021 Q4.

**Example 2, a month with no data (a known limitation).** In 2016 Q3 the Office
of the Prime Minister has rows only for July (Student, FTE 9.00); August and
September have none. Following this rule, the quarter is the average over the
one reporting month: Student **9.00**.

That result is doubtful. Across the whole file, this office's rows are almost
all summer students reported from May to August (36 of its 39 rows), because
its political staff are not part of the Federal Public Service data. A missing
month therefore most likely means *no employees in these categories*, not
*unknown*. Read that way, the quarter would be (9.00 + 0 + 0) / 3 = **3.00**,
and its winter quarters would show 0 instead of being omitted.

The opposite reading is right in other cases. ASC has no rows before October
2021 because it did not exist yet; counting those months as 0 would invent an
empty department. A rule that handles both would treat missing months *between*
a department's first and last reporting month as 0, and exclude months outside
that range. The implementation applies the rule as stated above and leaves
this choice to analysts (question 2 below).

**Example 3, a quarantined row.** In March 2016 the Public Prosecution Service of
Canada (PPSC) row that holds 899 employees has a blank tenure and is quarantined
([D7](#d7)). PPSC still reported other tenures that month, so March counts as a
reporting month with Indeterminate = 0:
(885.74 + 887.13 + 0) / 3 = **590.96**, instead of about 890 if the row had been
usable. This is why [Finding 2](#finding-2) below is a question for analysts.

- **Decision:** for each month in which the department has *any* accepted
  Federal Public Service row, take each tenure's FTE, using 0 if that tenure has
  no row. Average those values over the quarter's reporting months. Months
  without any row are excluded from the mean, and a quarter without reporting
  months is omitted.
- **Rationale:** FTE is a stock measured monthly, so a quarterly figure is an
  average. A missing tenure row in a reporting month means no employees of that
  tenure, while a missing month means no data.
- **Alternatives:** sum over months (wrong for a stock); average over all three
  months (treats missing data as zero staff); use the last month of the quarter.
- **Consequence:** a quarantined row still leaves its month as a reporting month,
  so that tenure counts as 0 for that month and lowers the mean. Every such row
  is listed in the import report and in [`import_rejection`](data-model.md#import_rejection-import_warning). The tenure filter
  never changes which months count.
- **Where:** [`src/pbo_workforce/repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) → [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py)
  (CTE [`monthly`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py), then `avg` per quarter). Tests:
  [`tests/integration/test_workforce_repo.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py) →
  [`test_calendar_quarters_hand_computed`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py),
  [`test_tenure_filter_selects_columns_without_changing_reporting_months`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py);
  [`tests/api/test_fte.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py) → [`test_fte_exact_shape`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py).
- **Questions for analysts:** does a month with no rows mean "no data" or "no
  employees" (Example 2)? Is this averaging rule the one used in PBO
  publications, and should quarantined rows lower the mean (see Findings [2](#finding-2) and [3](#finding-3))?

<a id="d4"></a>

### D4: Full precision stored, 2 decimals returned

**In short:** FTE values are stored exactly as they appear in the workbook and
rounded to two decimals only in API responses.

**Example:** row 5 of the FPS sheet (Housing, Infrastructure and Communities
Canada, Student, March 2015) has FTE `8.839999999999998`, a typical artifact of
how spreadsheets store decimals. The database keeps that exact value. The API
shows averages rounded to 2 decimals, for example ASC's 2021 Q4 Indeterminate
`30.133333…` is returned as `30.13`. Rounding happens once, at the end, so
averages are not computed from already-rounded numbers.

- **Decision:** `fte` is `double precision`; the API returns values rounded to 2
  decimals with Python `round`.
- **Rationale:** the workbook stores numbers as IEEE doubles, so `double precision` holds the source value exactly, while
  `NUMERIC(12,4)` would silently round at import. FTE is not money, and the small float error in `avg` over a
  few values is far below the 2-decimal output. The code uses `float`
  throughout; there is no `Decimal`.
- **Alternative:** `NUMERIC(12,4)`, which is exact decimal but rounds the source
  value at import.
- **Where:** [`WorkforceMonthly.fte`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/db/tables.py) ([`src/pbo_workforce/db/tables.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/db/tables.py));
  [`FteQuarter.from_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) ([`src/pbo_workforce/api/schemas.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py)).

<a id="d5"></a>

### D5: Department IDs follow sheet order and are stable

**In short:** departments are numbered in the order of the Departments sheet,
and a department keeps its number forever, even when the sheet changes.

**Example:** on the first import, Accessibility Standards Canada (first row of
the sheet) becomes [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) 1 and Administrative Tribunals Support Service of
Canada becomes 2. If a later file inserts a new department at the top of the
sheet, ASC is still 1 and the new department gets the next free number (102 in
the current data). A script that calls `/api/departments/1/fte` keeps getting
ASC.

- **Decision:** on first import, IDs are assigned in Departments-sheet order after
  de-duplication, so ASC = 1. Later imports match existing departments by
  normalized English name, keep their ID, update changed names, and give new
  departments the next IDs.
- **Rationale:** analysts and published work may refer to [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py).
- **Alternative:** database sequence IDs, which depend on insert order and history.
- **Where:** [`_upsert_departments`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) ([`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py)). Tests:
  [`tests/integration/test_import.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py) →
  [`test_departments_stored_canonical_with_ids_in_sheet_order`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_department_ids_are_stable_across_imports`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py);
  [`tests/integration/test_import_real_file.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py) → [`test_asc_is_department_1`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py).

<a id="d6"></a>

### D6: Name resolution by normalization plus a reviewed alias map

**In short:** workforce rows name their department in free text. Harmless
differences (extra spaces, apostrophe style) are ignored when matching. Known
misspellings are matched only if listed in a reviewed list. Nothing is guessed.

**Example:** these department names in the FPS sheet all match a department:

| Excel row | Name in the FPS sheet | Matched to | Why |
|---|---|---|---|
| 2362 | `Public Service␣␣Commission of Canada` (two spaces) | Public Service Commission of Canada | spaces collapsed |
| 3045 | `Innovation, Science and Economic Development Canada␣` | Innovation, Science and Economic Development Canada | outer space removed |
| 3293 | `␣Office of the Commissioner for Federal Judicial Affairs Canada` | Office of the Commissioner for Federal Judicial Affairs Canada | outer space removed |
| 2672 | `Privy Council Officee` | Privy Council Office | listed in [`KNOWN_ALIASES`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/aliases.py) |

A name such as `Privy Council Offic` would **not** be matched: it is not a
listed alias, so the row would be quarantined as [`UNKNOWN_DEPARTMENT`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) for a
person to review. Names are stored as the Departments sheet spells them, keeping
the typographic apostrophe in, for example, `Normes d’accessibilité Canada`.

- **Decision:** names are matched on [`normalize_name_key`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/normalize.py): Unicode NFC, collapsed
  internal whitespace, stripped, and `’`/`‘` compared as `'`. Names are stored
  as in the Departments sheet with only outer whitespace removed (`’`
  preserved). Known misspellings resolve only through [`KNOWN_ALIASES`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/aliases.py), persisted
  to [`department_alias`](data-model.md#department_alias). There is no fuzzy matching, and matching is
  case-sensitive (no case variants occur). Anything else is [`UNKNOWN_DEPARTMENT`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).
- **Rationale:** fuzzy matching can silently merge distinct departments. Every
  relaxation is visible and tested.
- **Where:** [`src/pbo_workforce/ingest/normalize.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/normalize.py),
  [`src/pbo_workforce/ingest/aliases.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/aliases.py). Tests: [`tests/unit/test_normalize.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_normalize.py);
  [`tests/integration/test_import_real_file.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py) → [`test_problem_1_*`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py).

<a id="d7"></a>

### D7: Tenure labels; blank is an error, not "Missing"

**In short:** tenure labels are matched ignoring case and stray spaces, but an
empty tenure cell is treated as an error, not as the "Missing" category.

**Example:** row 3893 (`Term␣`, Environment and Climate Change Canada) and row
4115 (`Indeterminate␣`, Communications Security Establishment) have a trailing
space; both are accepted as *term* and *indeterminate*. Row 3845 (Public
Prosecution Service of Canada, March 2016, 899 employees) has an empty tenure
cell and is quarantined as [`BLANK_TENURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py). It is **not** counted as *missing*:
"Missing" is a real category the source uses on 741 rows, meaning the employer
did not record a tenure. Putting 899 employees into it would invent data.

- **Decision:** strip and match case-insensitively to [`Tenure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/tenure.py). A blank tenure is
  quarantined as [`BLANK_TENURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).
- **Rationale:** `Missing` is a category the source reports; a blank is a data
  error. Mapping one to the other would invent data.
- **Where:** [`parse_tenure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/tenure.py) ([`src/pbo_workforce/domain/tenure.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/tenure.py)); [`_tenure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)
  ([`src/pbo_workforce/ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)). Tests: [`tests/unit/test_tenure.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_tenure.py) →
  [`test_blank_is_not_mapped_to_missing`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_tenure.py).

<a id="d8"></a>

### D8: Whole-row quarantine

**In short:** if any part of a row is invalid, the whole row is set aside; the
importer never keeps the good half of a bad row.

**Example:** row 639 (Canadian Heritage, Indeterminate, May 2015) has an FTE of
1518.66 but no headcount. The whole row is quarantined as [`NULL_MEASURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py),
including its FTE. Row 502 (Canadian Transportation Agency, Casual, April 2015)
has a headcount of **−20** and is quarantined as [`NEGATIVE_MEASURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py). Both rows
stay visible in [`import_rejection`](data-model.md#import_rejection-import_warning) with their original cell values.

The cost of this rule is real: without row 639, Canadian Heritage's 2015 Q2
Indeterminate FTE is **1008.77** instead of **1514.99** ([D3](#d3), [Finding 3](#finding-3)).

- **Decision:** a row is rejected, with sheet, Excel row number, raw values, and a
  reason code, if the date is invalid, the department is unknown, the tenure is
  blank or not allowed for the sheet, a required measure is null, invalid ([D17](#d17)),
  or negative. FPS requires headcount and FTE; RCMP and CAF require headcount.
  Checks run in that order and the first failure is recorded ([D18](#d18)).
- **Rationale:** partially trusting a row would mix known-bad and assumed-good
  values in one record.
- **Where:** [`validate_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) ([`src/pbo_workforce/ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)). Tests: one
  per code in [`tests/unit/test_validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py).
- **Question for analysts:** see [Finding 3](#finding-3) (rows with a valid FTE but no
  headcount) and [Finding 2](#finding-2) (a large row lost to a blank tenure).

<a id="d9"></a>

### D9: Warnings, not rejections

**In short:** values that are surprising but possible are kept unchanged and
flagged, rather than thrown away.

**Example 1:** row 9238 (Parks Canada, Student, July 2017) has FTE 2365.07 for a
headcount of 2321. More FTE than people is unusual but can happen (for example
overtime or staff changing mid-month), so the row is accepted and flagged
[`FTE_EXCEEDS_HEADCOUNT`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py). 33 rows are flagged this way.

**Example 2:** the RCMP and CAF sheets list one figure per year, each March,
until 2025. Both sheets start with an April 2015 row whose value is identical to
March 2016 (RCMP: 21,017 both times). The row is accepted and flagged
[`SUSPECT_DATE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py), because it may be a mislabelled March 2015.

- **Decision:** FTE > headcount ([`FTE_EXCEEDS_HEADCOUNT`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)) and RCMP/CAF rows off
  their annual March cadence before March 2025 ([`SUSPECT_DATE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)) are accepted
  unchanged and recorded in [`import_warning`](data-model.md#import_rejection-import_warning) and the report.
- **Rationale:** both are plausible but unusual. Neither justifies discarding
  data.
- **Where:** [`validate_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py); [`AnnualCadence`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py) ([`src/pbo_workforce/ingest/sources.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py)).
  Tests: [`test_fte_exceeds_headcount_is_accepted_with_warning`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
  [`test_off_cadence_date_is_suspect`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py).
- **Question for analysts:** should the 201504 RCMP/CAF rows be treated as
  March 2015?

<a id="d10"></a>

### D10: Duplicates

**In short:** an exact duplicate department is merged into one. A department
listed twice with different details stops the import. Duplicate workforce rows
are all set aside.

**Example 1:** Canadian Food Inspection Agency appears on rows 13 and 14 of the
Departments sheet with identical names in both languages. It is stored once, and
row 14 is reported as [`DUPLICATE_DEPARTMENT_ROW`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).

**Example 2 (hypothetical):** if row 14 had a different French name, the
importer could not know which one is right, so the whole import stops and
nothing changes in the database until the file is fixed.

**Example 3 (hypothetical):** if the FPS sheet had two rows for ASC, Term,
December 2021 (say FTE 7.33 and 8.00), both would be quarantined as
[`DUPLICATE_KEY`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py), rather than silently keeping one of them. The current file has
no such rows.

- **Decision:** identical duplicate Departments rows are collapsed with
  [`DUPLICATE_DEPARTMENT_ROW`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py). Conflicting ones (same normalized English name,
  other fields differ) fail the import. Workforce rows sharing
  `(department, month, tenure, source)` are *all* quarantined as [`DUPLICATE_KEY`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).
- **Rationale:** reference data must be consistent. With conflicting workforce
  duplicates there is no basis for choosing one.
- **Where:** [`validate_departments`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py), [`reject_duplicate_keys`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)
  ([`src/pbo_workforce/ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)). Tests:
  [`test_identical_duplicate_department_is_collapsed_with_warning`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
  [`test_conflicting_duplicate_department_fails`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
  [`test_duplicate_keys_reject_every_copy`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
  [`test_conflicting_department_duplicate_rolls_back`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py).

<a id="d11"></a>

### D11: RCMP and CAF have no FTE

**In short:** the RCMP and CAF sheets only give headcount, so their FTE endpoint
returns an empty list rather than invented numbers.

**Example:** `GET /api/departments/87/fte` (Royal Canadian Mounted Police -
Members) and `GET /api/departments/10/fte` (Canadian Armed Forces) both return
`{"fte_per_quarter": []}` with status 200. Their headcounts (for example
20,130 RCMP members in March 2025) are stored, ready for a headcount endpoint if
analysts want one. Note that [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) 86, "Royal Canadian Mounted Police"
without "- Members", is the RCMP's civilian staff from the FPS sheet and does
have FTE.

- **Decision:** imported into [`workforce_monthly`](data-model.md#workforce_monthly) with source `rcmp`/`caf`, tenure
  `combined`, `fte` NULL (enforced by [`ck_workforce_monthly_source_shape`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0001_schema.py)). The
  FTE endpoint returns `200 {"fte_per_quarter": []}` for them.
- **Rationale:** inventing FTE (for example FTE = headcount) would publish
  unsupported figures.
- **Where:** [`RCMP`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py), [`CAF`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py) in [`src/pbo_workforce/ingest/sources.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py);
  [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) reads only [`source = 'fps'`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py). Test:
  [`tests/api/test_fte.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py) → [`test_rcmp_and_caf_have_no_fte`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py).
- **Question for analysts:** would a headcount series help (for example a future
  `measure=headcount` option)?

<a id="d12"></a>

### D12: Filters

**In short:** the FTE endpoint can be narrowed to one year and to chosen
tenures; anything invalid is refused with a clear message.

**Example:** `GET /api/departments/1/fte?year=2022&tenure=term&tenure=casual`
returns only the four 2022 quarters, each with only the requested tenures:

```json
{"year": 2022, "quarter": 1, "term": 7.07, "casual": 2.6}
```

`tenure=TERM` and `tenure=term` are equivalent, and asking for `term` twice
returns it once. `year=1999` or `tenure=permanent` returns a 422 error naming the
bad parameter (`query.year: Input should be greater than or equal to 2000`).

- **Decision:** `year` is an optional single integer (2000 to 2100) matching the
  quarter's year. `tenure` is optional and repeatable, case-insensitive, one of
  the five FPS categories, and limits which tenure keys appear. Repeated values
  are de-duplicated, and keys follow the fixed order
  indeterminate, term, casual, student, missing. Invalid values return 422.
- **Where:** [`get_fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/departments.py) ([`src/pbo_workforce/api/routes/departments.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/departments.py));
  [`year_bounds`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/domain/period.py) turns `year` into a month range so the index is used. Tests:
  [`tests/api/test_fte.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py).

<a id="d13"></a>

### D13: One error format

**In short:** every error, whatever caused it, has the same JSON shape, and
internal details never reach the client.

**Example:** `GET /api/departments/9999/fte` returns status 404 with

```json
{"error": {"code": "department_not_found", "message": "No department with id 9999"}}
```

If something unexpected fails (say the database query raises an error), the
client gets status 500 with only
`"Internal server error (reference 3f9c…)"`; the full error is written to the
server log under the same reference, so support can find it without exposing
SQL or data to the caller.

- **Decision:** every error is `{"error": {"code", "message"}}`. Unknown
  department → 404 [`department_not_found`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/routes/departments.py). Unexpected errors → 500 with a
  reference ID that is also logged with the traceback.
- **Where:** [`_handle`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py) ([`src/pbo_workforce/api/errors.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/errors.py)). Tests:
  [`test_unexpected_error_hides_details`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_departments.py), [`test_unknown_department_is_404`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_fte.py).

<a id="d14"></a>

### D14: Idempotent, all-or-nothing import

**In short:** importing the file the database already holds does nothing, and
an import either completes entirely or changes nothing.

**Example:** running [`pbo-import data/data.xlsx`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/cli.py) a second time prints
`data.xlsx (sha256 476aede446a8...) was already imported as batch 1; nothing to
do.` The file is recognized by its fingerprint (SHA-256 hash), not by its name.
If an import fails halfway, for example because a sheet is missing, the
departments and rows it had already written are rolled back too.

Only the *latest* successful import counts as "already imported". Importing an
older file again after a newer one is applied, because it changes the data back
([D16](#d16)).

- **Decision:** [`import_batch`](data-model.md#import_batch) records the file's SHA-256, times, status, and
  per-sheet counts. Importing the same file as the latest successful import is a
  no-op unless [`--force`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/cli.py); with [`--force`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/cli.py) it adds a batch but no row versions.
  The whole import is one transaction.
- **Revised during implementation:** at first, a file was skipped if *any*
  earlier import had the same hash. Once imports kept history ([D16](#d16)),
  importing an older file again became a real change, so only the latest
  successful import counts as "already imported".
- **Where:** [`run_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py), [`_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) ([`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py)). Tests:
  [`test_second_import_of_same_file_is_a_noop`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_forced_reimport_of_same_file_changes_nothing`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_older_file_imported_again_is_applied_not_skipped`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_failure_after_rows_were_written_rolls_back_everything`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py).

<a id="d15"></a>

### D15: Ordering

**In short:** results always come back in the same order.

**Example:** `/api/departments` lists [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) 1, 2, 3, …; an FTE response
lists 2021 Q4, then 2022 Q1, 2022 Q2, and so on. A script comparing two calls
never sees differences caused by ordering alone.

- **Decision:** departments by [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py); quarters by year, then quarter.
- **Where:** departments are sorted by [`order_by(Department.id)`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/departments.py) in
  [`list_departments`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/departments.py)
  ([`src/pbo_workforce/repositories/departments.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/departments.py)); quarters are sorted by
  [`order_by(quarter_year, quarter)`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) in
  [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py)
  ([`src/pbo_workforce/repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py)).

<a id="d16"></a>

### D16: Imports keep history: rows are versioned, never deleted

**In short:** each file is a complete snapshot of its sheets, but importing it
never deletes or overwrites earlier data. A row whose values change, that
disappears from the file, or that is now quarantined is *closed* and kept as
history; the API serves only the current version of each row.

**Example:** the importer compares each row of the new file with the stored
current version for the same department, month, tenure, and source:

| Case | Example | What happens |
|---|---|---|
| Unchanged | ASC, Dec 2021, Term: headcount 9, FTE 7.33 in both files | Nothing; the row keeps the batch that introduced it. |
| Added | A month that was not in the previous file | New current version. |
| Revised | ASC, Dec 2021, Term: FTE 7.33 becomes 7.50 | Old version closed as `revised`; new version is current. |
| Absent | Passport Canada's July 2016 row is no longer in the file | Version closed as `absent`; nothing is deleted. |
| Now quarantined | A row that was valid now has no headcount | Version closed as [`rejected`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py); the rejection is also in [`import_rejection`](data-model.md#import_rejection-import_warning). |
| Reappears | An absent row comes back in a later file | New current version; the closed one stays as history. |

So an analyst who published 7.33 last month can still see that value, which
import replaced it, and why. Each import report lists every revised and closed
row with its old and new values, for example
`Accessibility Standards Canada, 2021-12, term: revised headcount 9, fte 7.33 -> headcount 9, fte 7.5`.
Re-importing an identical file reports `unchanged 44391, added 0, revised 0,
closed 0` for the Federal Public Service sheet.

- **Decision:** a row in [`workforce_monthly`](data-model.md#workforce_monthly) is current while
  [`valid_to_batch_id`](data-model.md#workforce_monthly) is NULL. An import closes a current version (sets
  [`valid_to_batch_id`](data-model.md#workforce_monthly) and [`closed_reason`](data-model.md#workforce_monthly): `revised`, `absent`, or [`rejected`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/report.py))
  instead of deleting or updating it, and inserts new versions for added and
  revised rows. A partial unique index allows one current version per key. The
  API reads the [`workforce_current`](data-model.md#workforce_current-view) view, which holds current versions only;
  the API role cannot read the table, so it cannot serve history by mistake.
  Values are compared exactly: any change in the source is a revision.
- **Revised during implementation:** the first version of this decision
  deleted and replaced each source's rows on every import. Reviewing the
  decisions with concrete examples showed that it silently loses figures
  analysts may already have published, so it was replaced by versioning.
- **Rationale:** analysts publish figures from this data. Deleting or
  overwriting rows would make an earlier publication impossible to reproduce
  and hide what each new file changed.
- **Alternatives:** delete and replace each source's rows on every import
  (simple, but loses history); mark only missing rows (keeps
  disappearances, but a revised value still overwrites the old one); upsert row
  by row (keeps rows that vanished from the source as if still current).
- **Where:** [`diff_snapshot`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py) ([`src/pbo_workforce/ingest/versioning.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/versioning.py)) decides
  what changed; [`_load_sheet`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) ([`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py)) applies it;
  [`migrations/versions/0003_row_versions.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0003_row_versions.py) adds the columns, partial indexes,
  and view; [`fte_per_quarter`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py) ([`src/pbo_workforce/repositories/workforce.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/repositories/workforce.py))
  reads [`workforce_current`](data-model.md#workforce_current-view). Tests: [`tests/unit/test_versioning.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_versioning.py);
  [`test_row_absent_from_new_file_is_closed_not_deleted`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_revised_value_closes_old_version_and_adds_new_one`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_row_quarantined_in_new_file_is_closed_as_rejected`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_row_that_reappears_gets_a_new_version`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_closed_versions_are_ignored`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_workforce_repo.py),
  [`test_reimporting_the_same_file_changes_nothing`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py).
- **Question for analysts:** should the API also expose history, for example
  figures "as of" an earlier import, so published analyses can be reproduced
  through the API rather than the database?

<a id="d17"></a>

### D17: `INVALID_MEASURE` reason code

**In short:** a headcount or FTE that is not a usable number is rejected with
its own reason code.

**Example (hypothetical):** a headcount typed as text (`"12"`), a headcount of
`20.5` (people are counted in whole numbers), or an FTE of `#N/A` would each be
quarantined as [`INVALID_MEASURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py). No row in the current file triggers it; the
code exists so a future file with such values fails loudly instead of being
misread.

- **Decision:** a measure that is text, NaN, infinite, or a fractional headcount
  is rejected as [`INVALID_MEASURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).
- **Where:** [`_measure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py) ([`src/pbo_workforce/ingest/validate.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py)). Test:
  [`test_invalid_measure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py).

<a id="d18"></a>

### D18: First failing check determines the reason

**In short:** when a row has several problems, it is reported under the first
one found, in a fixed order: date, department, tenure, measures.

**Example:** row 2672 has a misspelled department (`Privy Council Officee`) and
no headcount. The misspelling is resolved through the alias list ([D6](#d6)), so the
first real problem is the missing headcount: the row is reported as
[`NULL_MEASURE`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py), not [`UNKNOWN_DEPARTMENT`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).

- **Decision:** one reason code per rejected row, in the order of [`RejectReason`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/validate.py).
- **Test:** [`test_first_failing_check_wins`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py),
  [`test_alias_resolved_row_with_null_measure_is_null_measure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/unit/test_validate.py).

<a id="d19"></a>

### D19: Failed imports leave a record

**In short:** a failed import changes no data, but the attempt itself is
recorded so it can be investigated.

**Example:** importing a file without a [`CAF`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/sources.py) sheet stops with
`Import failed, nothing was changed: sheet 'CAF' not found`. The database is
exactly as before, and [`import_batch`](data-model.md#import_batch) gains one row with status `failed`, the
file's hash, and that message. Fixing the file and importing again works
normally.

- **Decision:** after a rollback, a `failed` row is written to [`import_batch`](data-model.md#import_batch) in a
  separate transaction. For known failures the message is stored; for unexpected
  errors only the exception type is stored, so no SQL or data is kept. A failed
  batch never blocks a retry.
- **Where:** [`_record_failure`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) ([`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py)). Tests:
  [`test_conflicting_department_duplicate_rolls_back`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_failed_import_does_not_block_retry`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py).

<a id="d20"></a>

### D20: Departments are never deleted by an import

**In short:** if a department disappears from a later Departments sheet, it
stays in the database with its ID, and anything that names it still finds it.

**Example 1 (hypothetical):** Passport Canada ([`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) 75) only has data for
two months in 2016. If a future Departments sheet dropped it, it would remain at
ID 75, so any script or published table that refers to 75 still resolves.
Removing a department is left as a deliberate, manual decision.

**Example 2 (hypothetical):** Privy Council Office ([`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) 78) is the target
of the reviewed alias `Privy Council Officee` ([D6](#d6)). If a future sheet dropped
it, the alias would still point to department 78, and workforce rows naming
Privy Council Office, or its misspelling, would still be accepted under ID 78.
The import does not fail because the alias target is missing from the sheet.
An alias pointing to a name that is not a department at all, for example a typo
in [`aliases.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/aliases.py), still stops the import.

- **Decision:** a department missing from a later Departments sheet is kept.
  Names in workforce rows and alias targets resolve against the departments in
  the sheet plus those kept from earlier imports.
- **Rationale:** stable IDs ([D5](#d5)) are referenced by analysts.
- **Revised during implementation:** writing a test for this decision showed
  that dropping a department that is the target of a reviewed alias made the
  next import fail. Names and aliases now resolve against kept departments as
  well as the current sheet.
- **Where:** [`src/pbo_workforce/ingest/load.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py) → [`_upsert_departments`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/ingest/load.py), which
  returns the IDs of all departments, kept ones included. Tests:
  [`tests/integration/test_import.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py) →
  [`test_department_missing_from_later_sheet_is_kept`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py),
  [`test_rows_and_aliases_still_resolve_to_a_kept_department`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import.py).

<a id="d21"></a>

### D21: `dept_short` is `null` when the source has no short names

**In short:** departments without an abbreviation return `null`, not an empty
text.

**Example:** Canadian Polar Commission has no short name in the source, so the
API returns:

```json
{"dept_id": 20, "dept_long": {"en": "Canadian Polar Commission", "fr": "Commission canadienne des affaires polaires"}, "dept_short": null}
```

`{"en": "", "fr": ""}` would look like real, empty abbreviations. This applies
to 10 departments.

- **Decision:** the 10 departments without short names return `"dept_short": null`
  rather than empty strings.
- **Where:** [`Department.from_row`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) ([`src/pbo_workforce/api/schemas.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py)). Test:
  [`test_departments_exact_shape_and_order`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/api/test_departments.py).

<a id="d22"></a>

### D22: Credentials per process

**In short:** each part of the system receives only the database password it
needs.

**Example:** in [`docker-compose.yml`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml), the [`import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml) container receives only
[`IMPORT_DATABASE_URL`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py) (role [`pbo_import`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py)) and the [`api`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml) container only
[`DATABASE_URL`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py) (role [`pbo_api`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/migrations/versions/0002_roles.py), read-only). If the API were compromised, the
attacker would hold a password that can read the department list and the
current figures (the [`workforce_current`](data-model.md#workforce_current-view) view) and nothing else; apart
from the database itself, only the one-off [`migrate`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml) container receives the
owner's password.

- **Decision:** the API, the importer, and migrations each load their own settings
  class and receive only their own database URL (migrations also read the two
  role URLs to set passwords).
- **Where:** [`src/pbo_workforce/config.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/config.py); [`docker-compose.yml`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/docker-compose.yml).

---

## Findings from profiling `data/data.xlsx`

Profiling the file found ten data problems: department names that differ
between sheets, tenure labels with trailing spaces, a blank tenure, null and
negative measures, FTE above headcount, a duplicated department, departments
without short names, suspicious RCMP/CAF dates, and absent tenure rows. Each is
handled by a decision above and covered by a test in
[`tests/integration/test_import_real_file.py`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py)
([`test_problem_1_*`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py) to [`test_problem_10_*`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py)).

The findings below go further: they describe what the data shows and how the
rules affect specific figures. They are numbered so the decisions above can
refer to them.

- <a id="finding-1"></a>**Finding 1: 10 departments have no short names.** They are Canadian Polar
  Commission, Federal Judges not part of any department, Indian Oil and Gas
  Canada, Indian Residential Schools Truth and Reconciliation Commission,
  International Joint Commission, Office of the Prime Minister, Registrar of the
  Supreme Court of Canada, Royal Canadian Mounted Police - Members, Security
  Intelligence Review Committee, and Statistical Survey Operations
  ([`test_problem_8_missing_short_names_are_null`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/tests/integration/test_import_real_file.py)).
- <a id="finding-2"></a>**Finding 2: The blank-tenure row is very likely PPSC's Indeterminate row** (201603, 899 of
  about 970 staff). Quarantining it makes PPSC's 2016 Q1 Indeterminate FTE
  590.96 instead of about 890 ([D3](#d3), Example 3).
- <a id="finding-3"></a>**Finding 3: 7 of the 9 null-headcount rows have a valid FTE.** For example, Canadian
  Heritage, 201505, Indeterminate, FTE 1518.66. Because [D8](#d8) requires headcount,
  that FTE is discarded, and Canadian Heritage's 2015 Q2 Indeterminate FTE is
  1008.77 instead of 1514.99.
- <a id="finding-4"></a>**Finding 4: The misspelled `Privy Council Officee` row also has no headcount**, so it is
  rejected either way ([D18](#d18)).
- <a id="finding-5"></a>**Finding 5: The negative headcount (−20) has a normal FTE (18.03)**, so it is probably a
  sign error.
- <a id="finding-6"></a>**Finding 6: FTE > headcount: 34 rows, 33 warnings.** The 34th is the negative-headcount
  row, which is rejected instead.
- <a id="finding-7"></a>**Finding 7: 16 departments have fewer than 136 months.** Some start or stop within the
  period (ASC starts 202110), and some have gaps. For example, the Office of the
  Prime Minister has 37 months between 201503 and 202606, almost all of them
  summer months with only students, so its gaps likely mean zero employees
  rather than missing data ([D3](#d3), Example 2).
- <a id="finding-8"></a>**Finding 8: The CAF row in the Departments sheet also has a trailing space in the French
  name.**

## Questions for analysts (by priority)

1. **Quarter basis ([D2](#d2)):** calendar or fiscal, and how to label fiscal years?
2. **What a missing month means ([D3](#d3), Example 2):** when a department has no
   rows for a month, is that "no data" (excluded from the average, as now) or
   "no employees" (counted as 0)? A middle option is to count gaps as 0 only
   between a department's first and last reporting month. This changes figures
   for seasonal or small departments, such as the Office of the Prime Minister
   (2016 Q3 Student FTE: 9.00 now, 3.00 if gaps count as 0).
3. **Averaging rule ([D3](#d3)):** confirm the mean over reporting months with absent
   tenures as 0, and that quarantined rows should lower the mean.
4. **FTE without headcount ([Finding 3](#finding-3)):** should FPS rows with a valid FTE and a
   null headcount be accepted for FTE purposes?
5. **Blank tenure ([Finding 2](#finding-2)) and negative headcount ([Finding 5](#finding-5)):** correct at the
   source, or accept documented corrections in the importer (like the alias map)?
6. **RCMP/CAF ([D11](#d11)):** is a headcount endpoint wanted, and should the 201504 rows
   be treated as March 2015 ([D9](#d9))?
7. **Department IDs ([D5](#d5)):** is [`dept_id`](https://github.com/Rain6435/pbo-workforce-data-service/blob/main/src/pbo_workforce/api/schemas.py) already used in analysts' scripts, and
   should IDs match any existing PBO reference list?
8. **History ([D16](#d16)):** should the API expose earlier versions of the data (an "as
   of" option), so published figures can be reproduced through the API?
