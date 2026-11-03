# Portfolio IQ backend

This directory contains the FastAPI backend for Portfolio IQ. It provides
job-scoped local storage, the Phase A upload/configuration foundation,
deterministic CMDB validation, similarity analysis, dashboard metrics, and
Technology & Integration, Output Family, and Portfolio Insights analysis.
Compatibility placeholders for later analysis remain registered, along with an
isolated shared OpenAI service boundary that Output Family classification does not use.
It contains no sample application inventory.

## Current Phase A-F modules

- Phase A: jobs, uploads, job/global configuration, parsed CMDB previews, and
  storage abstraction.
- Phase B: enhanced deterministic CMDB validation and optional-input evidence
  labels.
- Phase C: deterministic similarity/redundancy analysis and dashboard metrics.
- Phase D: deterministic technology clustering, explicit integration analysis,
  maps, and potential obsolete-technology indicators.
- Phase E: deterministic, explainable Output Family classification.
- Phase F: deterministic Portfolio Insights, executive summary, portfolio
  scorecards, risks, and action items.

Application Code is the primary identity throughout the backend. Documented
legacy identifier columns remain lower-priority parsing fallbacks, and missing
codes are never replaced with application names. All current Phase A-F analysis
is deterministic. Portfolio Insights treats
validation, dashboard, similarity, technology, and output-family results as
optional: missing or stale results produce module-status warnings rather than
failing the analysis.

Analysis overview responses consistently expose job/upload identity, analysis
status, summary data, warnings, and detail links. Existing flat endpoint fields
remain available for compatibility, with a nested `detail_endpoints` alias on
validation, similarity, technology, and Output Family overviews. List endpoint
limits must be positive; oversized values are capped at the documented safety
maximum returned in the response.

## Run locally

From this `backend` directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The equivalent recommended command from the repository root is:

```bash
python3 -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the generated API documentation, or call:

```bash
curl http://127.0.0.1:8000/health
```

## Run tests

From the repository root:

```bash
python3 -m compileall backend/app
PYTHONPATH=backend python3 -m unittest discover backend/tests
```

## Workflow

This is also the recommended manual smoke-test order: create the job, upload
configuration and CMDB inputs, validate, run similarity, generate dashboard
metrics, run technology analysis, run Output Family analysis, and finally run
Portfolio Insights so it can consume every current optional result.

1. Create a job with `POST /api/jobs`.
2. Upload a job-specific mandatory-fields spreadsheet with
   `POST /api/jobs/{job_id}/upload/mandatory-fields-config`, or retain the
   existing admin-managed fallback through `PUT /api/config/cmdb-mandatory-fields`.
3. Upload the mandatory CMDB workbook with
   `POST /api/jobs/{job_id}/upload/cmdb`.
4. Upload the output-family configuration with
   `POST /api/jobs/{job_id}/upload/output-family-config`. Explicit membership
   should use `Application Code` and/or `Application Name` columns.
5. Optionally upload Confluence PDFs, a team-validation table, and CloudWatch
   tables through their source-specific routes.
6. Check `GET /api/jobs/{job_id}/uploads/status` for input readiness.
7. Run deterministic validation with
   `POST /api/jobs/{job_id}/analysis/validation`. The request body may be omitted;
   `{}` remains accepted for existing clients.
8. Read the compact stored-result views:
   - `GET /api/jobs/{job_id}/analysis/validation/summary`
   - `GET /api/jobs/{job_id}/analysis/validation/details?page=1&page_size=50`
   - `GET /api/jobs/{job_id}/analysis/validation/duplicates`
   - `GET /api/jobs/{job_id}/analysis/validation/completeness.csv`
9. Inspect the uploaded workbook's ordered columns and detected identity fields
   with `GET /api/jobs/{job_id}/cmdb/columns`.
10. Run CMDB-only similarity analysis with
   `POST /api/jobs/{job_id}/analysis/similarity`. Its request body is optional;
   `{}` uses the production defaults.
11. Read similarity summary, paginated pairs, or grouped application matches:
   - `GET /api/jobs/{job_id}/analysis/similarity/summary`
   - `GET /api/jobs/{job_id}/analysis/similarity/pairs?page=1&page_size=50`
   - `GET /api/jobs/{job_id}/analysis/similarity/apps`
12. Generate compact dashboard cards and distributions with
    `POST /api/jobs/{job_id}/analysis/dashboard-metrics`. The request body is
    optional; `{}` uses `top_n=10` and includes stored similarity metrics.
13. Read the stored dashboard result with
    `GET /api/jobs/{job_id}/analysis/dashboard-metrics/summary`.
14. Run deterministic Technology & Integration analysis with
    `POST /api/jobs/{job_id}/analysis/technology`. The request body may be
    omitted; `{}` uses the Phase D defaults.
15. Inspect technology clusters, explicit integrations, maps, and potential
    obsolete indicators, then download either Phase D CSV export as needed.
16. Run deterministic Output Family analysis with
    `POST /api/jobs/{job_id}/analysis/output-families`, then inspect its summary,
    family/member views, gaps, application matrix, and CSV exports.
17. Run cross-module Portfolio Insights with
    `POST /api/jobs/{job_id}/analysis/portfolio-insights`, then inspect its
    executive summary, module status, scorecards, risks, action items, and
    application-level views.

The configuration and CMDB upload steps may be performed in either order. CMDB
validation uses the job-specific uploaded mandatory-fields configuration when
present and otherwise uses the existing global configuration.

## Phase A uploads and configuration

Uploaded files are saved beneath
`LOCAL_STORAGE_ROOT/jobs/{job_id}/uploads/{source}/` with a UUID-prefixed,
basename-only version of the original filename. Per-file metadata and bounded
previews/configuration artifacts are saved under the job's `processed` folder.

- Mandatory-fields configuration accepts `.xlsx`, `.xls`, and `.csv`. It finds
  common field-column headers case-insensitively; for a one-column table it uses
  that column directly. Values are trimmed and duplicates/blanks are removed in
  source order. The parsed job configuration is immediately usable by existing
  CMDB validation.
- Output-family configuration accepts `.xlsx`, `.xls`, and `.csv`. It parses a
  family column plus optional family key, `Application Code`, `Application
  Name`, `members`, `keywords`, `patterns`, and `description` columns.
  Comma-separated values are trimmed and deduplicated where applicable. Phase E
  uses family names, descriptions, keywords, and member terms as taxonomy
  evidence; these values are not treated as hardcoded application assignments.
- Team-validation and CloudWatch uploads accept `.xlsx`, `.xls`, and `.csv`.
  Phase A stores row count, column count, ordered columns, and at most 20 preview
  rows. Detailed validation/enrichment logic is deferred.
- Confluence accepts one or more `.pdf` files and stores file metadata. No deep
  PDF text extraction, OCR, or evidence generation occurs in Phase A.

`GET /api/jobs/{job_id}/uploads/status` reports each source's upload and
processing state, latest file, accepted extensions, warnings, and the computed
`can_run_validation` and `can_run_outputs_analysis` flags. CMDB and
mandatory-fields configuration are required for validation; a previously saved
global mandatory-fields configuration satisfies the validation fallback.
Output-family configuration is additionally required for outputs readiness.

## CMDB validation

CMDB upload accepts `.xlsx` and `.xls`, validates the extension, size, workbook
format, and configured `MAX_CMDB_ROWS` limit, then preserves the original file.
The first worksheet is parsed; fully empty rows are ignored and all source
columns are retained. A normalized preview is stored under the job's
`processed` artifacts.

Validation matches mandatory fields to headers using case-insensitive,
punctuation-insensitive matching. Application Code is the primary application
identifier; legacy headers such as Application ID, App ID, CMDB ID, and CI ID
remain supported as lower-priority fallbacks. It reports per-application and
overall completeness, missing columns and values, duplicate Application Code
groups and names, identity fallbacks, warnings, and CMDB
evidence/source/reliability labels. The latest
complete result is stored under the job's `results` artifacts. Validation is
fully deterministic and makes no OpenAI calls.

### Phase B validation enhancements

Validation resolves mandatory fields in strict priority order. A usable
job-scoped configuration uploaded through
`POST /api/jobs/{job_id}/upload/mandatory-fields-config` wins; otherwise the
global configuration at `PUT /api/config/cmdb-mandatory-fields` is used. The
summary reports `mandatory_fields_config_source` as `job_upload`,
`global_config`, or `default_or_missing`, plus the job configuration upload ID
when applicable. It also returns a complete `mandatory_field_mappings` list.
Each mapping contains the configured name, resolved CMDB column, match flag, and
match type (`exact`, `case_insensitive`, `normalized`, or `not_found`). Existing
matched- and missing-column fields remain unchanged.

Optional evidence changes labels deterministically:

- `Source of Truth 1`: CMDB only. Team Validation without Confluence remains at
  level 1 and produces a warning.
- `Source of Truth 2`: CMDB plus at least one Confluence PDF.
- `Source of Truth 3`: CMDB plus Confluence plus a processed Team Validation
  upload.
- CloudWatch is reported as available evidence but does not change the Source
  of Truth label in Phase B.

Reliability is `High` when processed Team Validation is available and overall
mandatory-field completeness is at least 70%; it is `Average` otherwise. The
summary includes `reliability_reason` as well as the backward-compatible
`reliability_label` and `reliability_note` fields.

For the latest processed Team Validation spreadsheet, validation performs a
first-pass deterministic check over the full uploaded table. It reports table
dimensions and columns, recognizes `Application Code`, `App Code`,
`application_code`, and `app_code` case-insensitively, and counts populated and
missing codes, records unmatched to CMDB, and CMDB applications without a team
record. When a supported Yes/No column (`confirmed in use`, `in use`,
`validated`, `confirmed`, `active`, or `reviewed`) exists, it counts values
outside `yes`, `no`, `y`, `n`, `true`, `false`, `1`, and `0`. These findings
produce warnings but never make validation fail.

`optional_input_summary` reports Confluence file count, latest Team Validation
and CloudWatch upload IDs, availability flags, and the inputs that contributed
to Source of Truth. Row-level validation continues to be paginated and now
includes Application Code plus the enhanced Source of Truth and reliability
labels. `GET /api/jobs/{job_id}/analysis/validation/completeness.csv` streams
the current per-application completeness result directly as `text/csv`; it does
not create a duplicate export artifact and returns `404` until the latest CMDB
has been validated.

The validation POST and `GET .../validation` return a compact overview rather
than all application rows. The summary endpoint contains aggregate metrics only;
row details are available in pages of 50 by default, with a maximum page size of
200. Duplicate groups have a dedicated endpoint. These read endpoints reuse the
stored result and return `404` until validation has run. Uploading a newer CMDB
also requires validation to run again before stored validation views are served.

## Similarity and redundancy

The similarity module identifies potential similar, redundant, or duplicate
applications using only the latest parsed CMDB upload. Application Code is the
primary identity; legacy identifier columns remain parsing fallbacks. The
service compares available name, description, portfolio, technology stack,
application technology, platform/hosting, department, and classification
values. It uses normalized text, token/Jaccard overlap, sequence similarity,
and exact categorical matches to produce scores from 0 to 100 with evidence,
matched fields, and missing-field warnings.

The default similar-pair threshold is 60, the possible-duplicate threshold is
85, at most 1,000 pairs are stored, and each application receives at most 10
matches. These values can be overridden in the POST body with
`similar_pair_threshold`, `possible_duplicate_threshold`, `max_pairs`, and
`per_application_limit`. Candidate blocking is used for larger inventories;
API responses remain bounded and pair details are paginated with a maximum page
size of 200.

Similarity can run before CMDB validation if a parsed upload exists. In that
case, its response explicitly warns that validation has not run. Results are
stored under the job's `results` folder and read endpoints return `404` until
analysis has run for the latest upload. This first version is fully
deterministic and makes no OpenAI calls.

## Dashboard metrics

The dashboard metrics module summarizes the latest parsed CMDB upload into a
compact result suitable for UI cards and charts. It reports portfolio overview
totals; application and operational status; portfolio and business criticality;
hosting type and provider; technology and platform; security/access indicators;
CMDB data quality; and similarity/redundancy indicators. Application Code
remains the primary application identifier.

Generate the result with
`POST /api/jobs/{job_id}/analysis/dashboard-metrics`. With no body or `{}`, the
service returns the top 10 ranked values and uses a current stored similarity
result when present. A request such as
`{"top_n": 5, "include_similarity": false}` changes the cap and deliberately
excludes similarity values. The compact result is stored as
`results/dashboard_metrics.json`. The summary GET returns that stored result and
returns `404` until generation has run for the latest CMDB upload.

A parsed CMDB preview is required. Validation and similarity are optional: if
either current result is absent, generation continues with a clear warning and
unavailable values remain null or empty. Category counts are normalized
deterministically, top lists are bounded, and generic placeholder technology
tokens are excluded. This version uses only uploaded CMDB data and stored
analysis results; it does not call OpenAI.

## Technology & Integration analysis

Phase D analyzes the latest parsed CMDB preview deterministically. Validation
is optional; when a current validation result exists, the analysis reuses its
Source of Truth and reliability labels. The result is stored through the
storage abstraction at `jobs/{job_id}/results/technology.json`.

Generate a compact result with
`POST /api/jobs/{job_id}/analysis/technology`. With no body or `{}`, it uses
`top_n=10`, `cluster_limit=50`, `integration_limit=100`, and
`include_obsolete=true`. A custom request can change those bounded limits or
disable obsolete-pattern checks.

Stored result views and exports are available from:

- `GET /api/jobs/{job_id}/analysis/technology/summary`
- `GET /api/jobs/{job_id}/analysis/technology/clusters?limit=50`
- `GET /api/jobs/{job_id}/analysis/technology/integrations?limit=100`
- `GET /api/jobs/{job_id}/analysis/technology/application-map?limit=100`
- `GET /api/jobs/{job_id}/analysis/technology/portfolio-map?limit=100`
- `GET /api/jobs/{job_id}/analysis/technology/obsolete`
- `GET /api/jobs/{job_id}/analysis/technology/clusters.csv`
- `GET /api/jobs/{job_id}/analysis/technology/integrations.csv`

Clusters use meaningful values from Technology Stack, Application Technology,
Platform, Hosting Provider, and Hosting Type and exclude placeholder-only
values. Obsolete findings are conservative configured keyword matches reported
as potential indicators requiring confirmation, not final lifecycle decisions.

Integrations are shown only when the uploaded CMDB contains explicit API,
webservice, interface, feed, or integration evidence. A target must match an
uploaded Application Code or an unambiguous recognizable application name.
Explicit observations without an identifiable target may be returned with null
target fields and low confidence. Shared technology, portfolio, hosting, owner,
or classification values never create integration relationships. When no
explicit relationship is present, the endpoint returns an empty list and an
insufficient-data warning.

The uncertain-items analysis route and legacy `/analysis/outputs` route remain
explicit placeholders; they never manufacture application records or
conclusions. The legacy
`technology-integrations` placeholder remains for compatibility; Phase D
clients should use the `/analysis/technology` endpoint family.

## Output Family analysis

Phase E scores every populated current-CMDB field against the configured
Output Family names, descriptions, keywords, patterns, and member terms. It
uses the current-session mandatory-fields configuration as an internal field
weight, with additional field relevance weights for functional descriptions,
output-related fields, application names, and general context. These weights
are analysis details and are not shown in the UI. Matching uses normalized
phrases and meaningful-token overlap; it does not call OpenAI or need an API
key. Each application is assigned to one best-supported configured family.
When no family meets the evidence threshold, the application is assigned to a
single `Others` cluster and a comment records the closest family considered
and the CMDB evidence reviewed. The result is stored at
`jobs/{job_id}/results/output_families.json`. Both current-session inputs are
required; mandatory-field configuration is used when available.

Run the analysis with no body, `{}`, or bounded options such as
`{"family_limit": 50, "member_limit": 200, "include_unmapped": true,
"include_inactive": true}`. Stored views are available at:

- `GET /api/jobs/{job_id}/analysis/output-families/summary`
- `GET /api/jobs/{job_id}/analysis/output-families/families?limit=50`
- `GET /api/jobs/{job_id}/analysis/output-families/families/{family_key}`
- `GET /api/jobs/{job_id}/analysis/output-families/members?limit=200`
- `GET /api/jobs/{job_id}/analysis/output-families/gaps`
- `GET /api/jobs/{job_id}/analysis/output-families/application-matrix?limit=200`

The application matrix records family/cluster relationships, deterministic
confidence and status, contributing `fields_used`, `matched_evidence`, and a
concise deterministic rationale. Below-threshold evidence is assigned to
`Others` with `Insufficient Evidence` status. Read filters reuse stored results.
Download the complete stored family, member, and gap tables from:

- `GET /api/jobs/{job_id}/analysis/output-families/families.csv`
- `GET /api/jobs/{job_id}/analysis/output-families/members.csv`
- `GET /api/jobs/{job_id}/analysis/output-families/gaps.csv`

Stored reads and exports return `404` until analysis has run, and again when a
newer CMDB or output-family configuration has made the result stale.

## Portfolio Insights and executive summary

Phase F provides a deterministic, cross-module view for leadership and
portfolio owners. It requires only the latest parsed CMDB preview. Current
validation, dashboard metrics, similarity, technology, and output-family
results are optional: missing, stale, or unreadable module artifacts are shown
in `module_status` and warnings instead of failing the run. Metrics that cannot
be supported by available evidence are returned as null with an explanatory
warning.

Run the analysis with
`POST /api/jobs/{job_id}/analysis/portfolio-insights`. The body is optional;
`{}` uses `risk_limit=100`, `action_limit=100`, `portfolio_limit=100`, and
`include_low_severity=true`. The result is stored at
`jobs/{job_id}/results/portfolio_insights.json`. Uploading a newer CMDB makes
the stored result stale and all Phase F read endpoints return `404` until the
analysis is rerun.

The compact POST response includes the aggregate summary, executive summary,
module availability, top portfolio scorecards, risk and action samples,
warnings, and links to these stored-result views:

- `GET /api/jobs/{job_id}/analysis/portfolio-insights/summary`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/executive-summary`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/module-status`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard?limit=100`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/risks?limit=100&include_low_severity=true`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/action-items?limit=100`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/applications/{application_code}`

Portfolio scorecards use the CMDB Portfolio value and group blank values under
`Unassigned`. Application detail lookup uses an exact Application Code; names
are never substituted for missing codes. Risks are created only from explicit
CMDB or stored analysis evidence, and each action item maps to a source risk.
Recommendations are limited to direct review or data-quality actions. The
executive findings, limitations, risks, and actions are generated by fixed
rules from uploaded/analyzed data only—Phase F does not call OpenAI and does not
invent financial, operational, or transformation conclusions.

Complete stored tables can be downloaded as `text/csv` from:

- `GET /api/jobs/{job_id}/analysis/portfolio-insights/risks.csv`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/action-items.csv`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard.csv`

The local adapter stores artifacts beneath
`LOCAL_STORAGE_ROOT/jobs/{job_id}/`. Set the storage root in `.env`. Uploaded
files are treated as confidential: logs contain metadata only, not file contents.

## Available endpoints

- `GET /health`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `DELETE /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/upload/cmdb`
- `POST /api/jobs/{job_id}/upload/mandatory-fields-config`
- `POST /api/jobs/{job_id}/upload/output-family-config`
- `GET /api/jobs/{job_id}/cmdb/columns`
- `POST /api/jobs/{job_id}/upload/confluence`
- `POST /api/jobs/{job_id}/upload/team-validation`
- `POST /api/jobs/{job_id}/upload/validation`
- `POST /api/jobs/{job_id}/upload/cloudwatch`
- `GET /api/jobs/{job_id}/uploads/status`
- `GET /api/jobs/{job_id}/config/mandatory-fields`
- `GET /api/jobs/{job_id}/config/output-families`
- `GET /api/config/cmdb-mandatory-fields`
- `PUT /api/config/cmdb-mandatory-fields`
- `POST /api/jobs/{job_id}/analysis/validation`
- `GET /api/jobs/{job_id}/analysis/validation`
- `GET /api/jobs/{job_id}/analysis/validation/summary`
- `GET /api/jobs/{job_id}/analysis/validation/details`
- `GET /api/jobs/{job_id}/analysis/validation/duplicates`
- `GET /api/jobs/{job_id}/analysis/validation/completeness.csv`
- `POST /api/jobs/{job_id}/analysis/similarity`
- `GET /api/jobs/{job_id}/analysis/similarity/summary`
- `GET /api/jobs/{job_id}/analysis/similarity/pairs`
- `GET /api/jobs/{job_id}/analysis/similarity/apps`
- `POST /api/jobs/{job_id}/analysis/dashboard-metrics`
- `GET /api/jobs/{job_id}/analysis/dashboard-metrics/summary`
- `POST /api/jobs/{job_id}/analysis/technology`
- `GET /api/jobs/{job_id}/analysis/technology/summary`
- `GET /api/jobs/{job_id}/analysis/technology/clusters`
- `GET /api/jobs/{job_id}/analysis/technology/integrations`
- `GET /api/jobs/{job_id}/analysis/technology/application-map`
- `GET /api/jobs/{job_id}/analysis/technology/portfolio-map`
- `GET /api/jobs/{job_id}/analysis/technology/obsolete`
- `GET /api/jobs/{job_id}/analysis/technology/clusters.csv`
- `GET /api/jobs/{job_id}/analysis/technology/integrations.csv`
- `POST /api/jobs/{job_id}/analysis/output-families`
- `GET /api/jobs/{job_id}/analysis/output-families/summary`
- `GET /api/jobs/{job_id}/analysis/output-families/families`
- `GET /api/jobs/{job_id}/analysis/output-families/families/{family_key}`
- `GET /api/jobs/{job_id}/analysis/output-families/members`
- `GET /api/jobs/{job_id}/analysis/output-families/gaps`
- `GET /api/jobs/{job_id}/analysis/output-families/application-matrix`
- `GET /api/jobs/{job_id}/analysis/output-families/families.csv`
- `GET /api/jobs/{job_id}/analysis/output-families/members.csv`
- `GET /api/jobs/{job_id}/analysis/output-families/gaps.csv`
- `POST /api/jobs/{job_id}/analysis/portfolio-insights`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/summary`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/executive-summary`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/module-status`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/risks`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/action-items`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/applications/{application_code}`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/risks.csv`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/action-items.csv`
- `GET /api/jobs/{job_id}/analysis/portfolio-insights/portfolio-scorecard.csv`
- `POST /api/jobs/{job_id}/analysis/technology-integrations`
- `POST /api/jobs/{job_id}/analysis/outputs`
- `POST /api/jobs/{job_id}/analysis/uncertain-items`

The storage contract lives in `app/storage/base.py`; local disk is selected via
`STORAGE_MODE=local`, leaving provider selection isolated for future cloud
adapters. `MAX_CMDB_ROWS` controls the accepted non-empty CMDB row count and
defaults to 5,000.

Analysis modules implement an asynchronous contract and receive a job-scoped
context containing configuration, storage, job metadata, and the isolated
OpenAI service boundary. Similarity, dashboard metrics, and Technology &
Integration and Output Family delegate to deterministic services. The
legacy outputs and uncertain-items modules remain explicit placeholders. The CMDB validation path
uses dedicated parser, configuration, orchestration, and validation services.
Validation, similarity, dashboard metrics, Technology & Integration, and Output
Family do not call OpenAI. API routes translate service results into Pydantic response schemas
and obtain services through typed FastAPI dependencies.

`API_PREFIX` controls the API route prefix and defaults to `/api`; `/health`
remains unprefixed.

## Manual testing in `/docs`

1. Start the backend and open `http://127.0.0.1:8000/docs`.
2. Create a job and copy its `job_id`.
3. Call `GET /api/jobs/{job_id}/uploads/status` and confirm all sources initially
   show `uploaded: false`.
4. Upload a mandatory-fields Excel/CSV file. A one-column file headed
   `mandatory_field` with values such as `Application Code`, `Application Name`,
   `Portfolio`, `Business Criticality`, and `Status` is sufficient.
5. Upload an output-family Excel/CSV file with `output_family`, optional
   `keywords`, and optional `description` columns. Confirm the response contains
   normalized families but does not run outputs analysis.
6. Upload the real `.xlsx` or `.xls` CMDB to that job.
7. Optionally upload multiple Confluence PDFs and one team-validation and
   CloudWatch Excel/CSV table. Confirm tabular responses report only basic schema
   metadata and the files are marked as stored for future enhancement.
8. Call the upload status endpoint again. Confirm `can_run_validation` is true
   after CMDB plus mandatory fields are available, and
   `can_run_outputs_analysis` is true after CMDB plus output families are
   available.
9. Call the columns endpoint to verify header order and that
   `application_code_column` contains the selected identity header.
10. Call the validation POST with no request body (or with `{}`). Its response is
   safe to inspect for a 1,259-row workbook because it contains no row records.
11. Inspect aggregate metrics through the summary endpoint, duplicate groups
   through the duplicates endpoint, and rows through the paginated details
   endpoint. Use `page_size` from 1 through 200.
12. Call `POST /api/jobs/{job_id}/analysis/similarity` with no body. To test
   custom limits, use a body such as
   `{"similar_pair_threshold": 60, "possible_duplicate_threshold": 85, "max_pairs": 1000, "per_application_limit": 10}`.
13. Confirm the response includes a bounded `top_similar_pairs` list, evidence,
   warnings, and links to the three stored-result endpoints.
14. Call the similarity summary endpoint and confirm it contains no pair or
    per-application detail. Page through the pairs endpoint, then call the apps
    endpoint and confirm matches are grouped by Application Code.
15. Call `POST /api/jobs/{job_id}/analysis/dashboard-metrics` with no body (or
    `{}`). Confirm the response contains `overview`, `cards`, `distributions`,
    `data_quality`, `similarity_summary`, `warnings`, and `generated_from`.

## Manual testing for Phase B

1. Create a job, configure global mandatory fields, then upload a different
   job-level mandatory-fields table and a real CMDB workbook. Run validation and
   confirm the summary says `job_upload`, includes its upload ID, and shows every
   configured field in `mandatory_field_mappings`.
2. Repeat on a new job without a job-level config and confirm the source is
   `global_config`.
3. With CMDB alone, confirm `Source of Truth 1` and `Average` reliability. Add a
   Confluence PDF and rerun to confirm `Source of Truth 2`.
4. Upload Team Validation containing matching, missing, and unknown Application
   Codes plus a supported Yes/No column with one invalid value. Rerun and inspect
   `team_validation_summary`, coverage warnings, `Source of Truth 3`, and `High`
   reliability when completeness is at least 70%.
5. On another job, upload Team Validation without Confluence. Confirm the label
   remains `Source of Truth 1` and the response explains that level 3 requires
   both inputs.
6. Upload CloudWatch data and confirm its availability and upload ID appear in
   `optional_input_summary` without changing Source of Truth.
7. Download
   `GET /api/jobs/{job_id}/analysis/validation/completeness.csv`; confirm the
   response is `text/csv` and contains Application Code, Application Name,
   completeness, missing fields, Source of Truth, and reliability. A job that
   has not run validation should receive `404`.
8. Recheck paginated details, duplicates, similarity, dashboard metrics, and
   upload status to confirm their existing contracts still work.
16. Optionally call it again with `{"top_n": 5, "include_similarity": true}`
    and confirm ranked lists are capped at five. If validation or similarity was
    skipped, confirm generation still succeeds and the corresponding warning is
    present.
17. Call `GET /api/jobs/{job_id}/analysis/dashboard-metrics/summary` and confirm
    it returns the stored result for the latest CMDB upload.

## Manual testing for Phase D

1. Create a job and upload a real CMDB workbook. Optionally run validation first
   so its Source of Truth and reliability labels can be reused.
2. Call `POST /api/jobs/{job_id}/analysis/technology` once without a body and on
   another job with `{}`. Confirm both use the documented defaults and write the
   stored result.
3. Inspect summary and clusters. Confirm meaningful technology, platform, and
   hosting values are grouped, placeholders are absent, and missing Application
   Codes remain null rather than being populated with application names.
4. Inspect integrations and both map endpoints. Shared technology or portfolio
   values must not create edges. Explicit evidence naming another uploaded
   Application Code should create an evidence-backed edge; unresolved explicit
   observations should remain low-confidence with null targets.
5. Inspect obsolete indicators. Confirm configured legacy patterns are labeled
   as potential indicators and normal modern technologies are not flagged.
6. Download both CSV endpoints and verify the documented headers. Before a run,
   and after uploading a newer CMDB, all stored-result views and exports should
   return a clear `404` response.

## Manual testing for Phase E

1. Create a job and confirm Output Family POST returns a clear prerequisite
   error before a CMDB preview exists.
2. Upload a real CMDB, retry, and confirm a job-level output-family config is
   still required.
3. Upload an Excel/CSV config containing family names and useful family/member
   terminology. No OpenAI configuration is required.
4. Run `POST /api/jobs/{job_id}/analysis/output-families` once without a body
   and, on another job, with `{}`. Confirm both return a compact response and
   store a result.
5. Inspect summary and application mapping. Verify every CMDB application has a
   validated result with confidence, status, Fields Used, and rationale.
6. Exercise competing-family and insufficient-evidence cases. Confirm each
   application maps to one best-supported configured family or the single
   `Others` fallback, with the reason and reviewed CMDB evidence in its comment.
7. Download the three CSV endpoints and verify their documented headers and
   `text/csv` content type. Confirm all stored views return `404` before a run
   and after either required input is replaced.

## Manual testing for Phase F

1. Create a job and call the Portfolio Insights POST before uploading a CMDB;
   confirm the API clearly reports that a parsed CMDB preview is required.
2. Upload a real CMDB and run Portfolio Insights with no body or `{}` before
   running other analyses. Confirm it succeeds, stores a result, marks the CMDB
   preview available, and marks all optional source modules missing.
3. Inspect the executive summary, module status, and portfolio scorecard.
   Confirm blank Portfolio values appear under `Unassigned`, unsupported module
   metrics are null, and the associated warnings and limitations are explicit.
4. Run any desired validation, dashboard, similarity, technology, and
   output-family analyses, then rerun Portfolio Insights. Confirm only current
   stored results become available and contribute evidence-backed metrics.
5. Inspect risks and action items. Confirm every risk cites an evidence module,
   every action refers to an existing `source_risk_id`, and
   `include_low_severity=false` excludes low-severity risks.
6. Request a known application with its exact Application Code, then change its
   case and confirm the latter request returns `404` unless that differently
   cased code exists in the CMDB.
7. Download all three Phase F CSV exports and verify their headers and
   `text/csv` content type. Upload a newer CMDB and confirm stored Phase F views
   and exports return `404` until the analysis is rerun.
