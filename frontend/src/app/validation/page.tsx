"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ActionBar } from "@/components/action-bar";
import { EmptyState } from "@/components/empty-state";
import { ErrorMessage } from "@/components/error-message";
import { JobSummary } from "@/components/job-summary";
import { SimpleTable } from "@/components/simple-table";
import { StatusBadge } from "@/components/status-badge";
import { useJob } from "@/context/job-context";
import {
  ApiError,
  getJson,
  getUploadStatus,
  getValidationDetails,
  getValidationDuplicates,
  getValidationSummary,
  runValidation,
  validationCompletenessCsvUrl,
} from "@/lib/api";
import type {
  DuplicateValue,
  MandatoryFieldMapping,
  OutputFamiliesConfigResponse,
  TeamValidationSummary,
  UploadStatusResponse,
  ValidationDetailRow,
  ValidationDetailsResponse,
  ValidationDuplicatesResponse,
  ValidationSummaryResponse,
} from "@/types/api";

const PAGE_SIZE = 50;

export default function ValidationPage() {
  const { jobId, hydrated } = useJob();
  const [readiness, setReadiness] = useState<UploadStatusResponse | null>(null);
  const [families, setFamilies] = useState<OutputFamiliesConfigResponse | null>(null);
  const [summary, setSummary] = useState<ValidationSummaryResponse | null>(null);
  const [details, setDetails] = useState<ValidationDetailsResponse | null>(null);
  const [duplicates, setDuplicates] = useState<ValidationDuplicatesResponse | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const autoRunJob = useRef<string | null>(null);
  const autoRunPromise = useRef<Promise<void> | null>(null);

  const loadInputs = useCallback(async () => {
    if (!jobId) {
      setReadiness(null);
      setFamilies(null);
      return;
    }
    const encoded = encodeURIComponent(jobId);
    const [statusResult, familyResult] = await Promise.allSettled([
      getUploadStatus(jobId),
      getJson<OutputFamiliesConfigResponse>(`/api/jobs/${encoded}/config/output-families`),
    ]);
    setReadiness(statusResult.status === "fulfilled" ? statusResult.value : null);
    setFamilies(familyResult.status === "fulfilled" ? familyResult.value : null);
  }, [jobId]);

  const loadResults = useCallback(async (requestedPage: number) => {
    if (!jobId) {
      setSummary(null);
      setDetails(null);
      setDuplicates(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const currentSummary = await getValidationSummary(jobId);
      const [currentDetails, currentDuplicates] = await Promise.all([
        getValidationDetails(jobId, requestedPage, PAGE_SIZE),
        getValidationDuplicates(jobId),
      ]);
      setSummary(currentSummary);
      setDetails(currentDetails);
      setDuplicates(currentDuplicates);
      setPage(currentDetails.page);
    } catch (caught) {
      setSummary(null);
      setDetails(null);
      setDuplicates(null);
      if (!(caught instanceof ApiError && caught.status === 404)) {
        setError(errorText(caught, "Could not load validation results."));
      }
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    setPage(1);
    setSuccess(null);
    if (!jobId) { void loadInputs(); void loadResults(1); return; }
    let cancelled = false;
    void (async () => {
      await loadInputs();
      try {
        await getValidationSummary(jobId);
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404 && autoRunJob.current !== jobId) {
          const currentStatus = await getUploadStatus(jobId);
          if (currentStatus.can_run_validation) {
            if (autoRunJob.current !== jobId) {
              autoRunJob.current = jobId;
              setRunning(true);
              autoRunPromise.current = runValidation(jobId)
                .then(() => { if (!cancelled) setSuccess("Validation results are ready for this job."); })
                .finally(() => { if (!cancelled) setRunning(false); });
            }
            await autoRunPromise.current;
          }
        }
      }
      if (!cancelled) await loadResults(1);
    })().catch((caught) => {
      if (!cancelled) setError(errorText(caught, "Could not prepare validation results."));
    });
    return () => { cancelled = true; };
  }, [jobId, loadInputs, loadResults]);

  const requiredLoaded = Boolean(
    readiness?.sources.cmdb?.uploaded &&
      readiness.sources.cmdb.processed &&
      readiness.sources.mandatory_fields_config?.uploaded &&
      readiness.sources.mandatory_fields_config.processed &&
      readiness.sources.output_family_config?.uploaded &&
      readiness.sources.output_family_config.processed,
  );

  const run = async () => {
    if (!jobId || !requiredLoaded) return;
    setRunning(true);
    setError(null);
    setSuccess(null);
    try {
      await runValidation(jobId);
      setSuccess("Inputs loaded and CMDB validation completed.");
      await Promise.all([loadInputs(), loadResults(1)]);
    } catch (caught) {
      setError(errorText(caught, "Validation could not be run."));
    } finally {
      setRunning(false);
    }
  };

  const changePage = (nextPage: number) => {
    setPage(nextPage);
    void loadResults(nextPage);
  };

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">MVP tab 1</p>
          <h2>1. CMDB Validation and Source Labels</h2>
          <p>Validate the uploaded CMDB against the mandatory-fields configuration for this job. The CMDB remains the source of truth.</p>
        </div>
        <JobSummary />
      </section>

      {hydrated && (!jobId || (readiness && !requiredLoaded)) && (
        <section className="validation-callout panel">
          <div>
            <h3>Required inputs are not loaded yet.</h3>
            <p>Upload CMDB, mandatory-fields config, and output-family config before analysis.</p>
          </div>
          <Link className="button button-secondary" href="/uploads">Open Input Uploads</Link>
        </section>
      )}

      <ActionBar title="Load and validate inputs" description="Runs deterministic CMDB validation using the mandatory-fields configuration uploaded for this job.">
        <button className="button button-primary" type="button" disabled={!requiredLoaded || running} onClick={() => void run()}>
          {running ? "Loading and validating…" : "Load and validate inputs"}
        </button>
      </ActionBar>
      <ErrorMessage message={error} />
      {success && <p className="message message-success" role="status">{success}</p>}
      {loading && !summary && <section className="panel loading-panel" aria-live="polite">Loading validation results…</section>}
      {jobId && !summary && !loading && !error && (
        <section className="panel">
          <EmptyState title="Validation has not run yet"><p>Upload all required inputs for this job, then load and validate them.</p></EmptyState>
        </section>
      )}

      {summary && (
        <>
          <MandatoryFieldMapping result={summary} readiness={readiness} />
          <CompletenessByApplication result={summary} details={details} page={page} loading={loading} onPageChange={changePage} />
          <ValidationIssues result={summary} duplicates={duplicates} />
          <EvidenceLabels readiness={readiness} details={details} />
          <TeamValidationChecks uploaded={Boolean(readiness?.sources.team_validation?.uploaded && readiness.sources.team_validation.processed)} summary={summary.summary.team_validation_summary} />
        </>
      )}

      <ConfiguredOutputFamilies families={families} uploaded={Boolean(readiness?.sources.output_family_config?.uploaded && readiness.sources.output_family_config.processed)} />
    </div>
  );
}

function MandatoryFieldMapping({ result, readiness }: { result: ValidationSummaryResponse; readiness: UploadStatusResponse | null }) {
  const mappings = result.summary.mandatory_field_mappings;
  const uploaded = Boolean(readiness?.sources.mandatory_fields_config?.uploaded && readiness.sources.mandatory_fields_config.processed);
  const fallback = !uploaded && Boolean(readiness?.mandatory_fields_config_ready);
  return (
    <section className="section-panel panel" aria-labelledby="mapping-title">
      <div className="section-heading">
        <div><p className="eyebrow">A</p><h3 id="mapping-title">Mandatory field mapping</h3></div>
        <StatusBadge tone={uploaded ? "success" : "warning"}>
          {uploaded ? "Uploaded for this job" : fallback ? "Backend fallback/default config" : "Missing for this job"}
        </StatusBadge>
      </div>
      {!uploaded && <p className="message message-info">{fallback ? "Backend fallback/default config is available, but it is not an uploaded user input for this job." : "CMDB mandatory-fields config is not uploaded for this job."}</p>}
      {mappings.length ? (
        <SimpleTable<MandatoryFieldMapping>
          caption="Mandatory field mapping"
          columns={[
            { key: "configured", header: "Configured Mandatory Field", render: (row) => row.configured_field },
            { key: "matched", header: "Matched CMDB Column", render: (row) => row.cmdb_column ?? "Not matched" },
          ]}
          rows={mappings}
          getRowKey={(row) => row.configured_field}
        />
      ) : <EmptyState title="No mandatory fields returned"><p>No mandatory-field mapping was returned by the backend.</p></EmptyState>}
    </section>
  );
}

function CompletenessByApplication({
  result,
  details,
  page,
  loading,
  onPageChange,
}: {
  result: ValidationSummaryResponse;
  details: ValidationDetailsResponse | null;
  page: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}) {
  const fieldCount = result.summary.mandatory_field_mappings.length;
  const totalCells = result.summary.total_row_count * fieldCount;
  const populatedCells = Math.round(totalCells * result.summary.overall_completeness / 100);
  return (
    <section className="section-panel panel" aria-labelledby="completeness-title">
      <div className="section-heading">
        <div><p className="eyebrow">B</p><h3 id="completeness-title">Completeness by application</h3></div>
        {details && <p>{details.total_records} applications · Page {details.page} of {Math.max(details.total_pages, 1)}</p>}
      </div>
      <p className="calculation-note">
        Calculated as populated mandatory-field cells divided by total mandatory-field cells, using the uploaded mandatory-fields configuration.
        {result.summary.mandatory_fields_config_source !== "job_upload" && " This stored result used Backend fallback/default config instead; upload a config for this job before treating validation as ready."}
      </p>
      <dl className="validation-facts">
        <div><dt>Configured mandatory field count</dt><dd>{fieldCount}</dd></div>
        <div><dt>Populated mandatory cells (derived)</dt><dd>{populatedCells}</dd></div>
        <div><dt>Total mandatory cells</dt><dd>{totalCells}</dd></div>
        <div><dt>Missing mandatory values (derived)</dt><dd>{Math.max(totalCells - populatedCells, 0)}</dd></div>
        <div><dt>Missing mandatory columns</dt><dd>{result.summary.missing_mandatory_columns.length}</dd></div>
        <div><dt>Mandatory CMDB field completeness</dt><dd>{result.summary.overall_completeness.toFixed(1)}%</dd></div>
      </dl>
      {details?.records.length ? (
        <SimpleTable<ValidationDetailRow>
          caption="Mandatory CMDB field completeness by application"
          columns={[
            { key: "code", header: "Application Key or Application Code", render: (row) => <strong>{row.application_code ?? row.application_key}</strong> },
            { key: "name", header: "Application Name", render: (row) => row.application_name || "Not available" },
            { key: "populated", header: "Mandatory Fields Populated", render: (row) => Math.max(fieldCount - row.missing_mandatory_fields.length, 0) },
            { key: "total", header: "Mandatory Fields Total", render: () => fieldCount },
            { key: "complete", header: "Completeness %", render: (row) => `${row.completeness_percentage.toFixed(1)}%` },
            { key: "missing", header: "Missing Mandatory Fields", render: (row) => row.missing_mandatory_fields.length ? row.missing_mandatory_fields.join(", ") : "None" },
          ]}
          rows={details.records}
          getRowKey={(row) => `${row.internal_row_number}-${row.application_key}`}
        />
      ) : <EmptyState title="No application rows"><p>No application-level validation rows were returned.</p></EmptyState>}
      <div className="result-toolbar">
        <span>Application Code is the primary application identifier.</span>
        <a className="button button-secondary" href={validationCompletenessCsvUrl(result.job_id)}>Download CMDB completeness CSV</a>
      </div>
      {details && details.total_pages > 1 && (
        <div className="pagination">
          <button className="button button-secondary" disabled={loading || page <= 1} onClick={() => onPageChange(page - 1)}>Previous</button>
          <span>Page {page} of {details.total_pages}</span>
          <button className="button button-secondary" disabled={loading || page >= details.total_pages} onClick={() => onPageChange(page + 1)}>Next</button>
        </div>
      )}
    </section>
  );
}

function ValidationIssues({ result, duplicates }: { result: ValidationSummaryResponse; duplicates: ValidationDuplicatesResponse | null }) {
  const missing = result.summary.missing_mandatory_columns;
  const codes = duplicates?.duplicate_application_codes ?? [];
  const ids = duplicates?.duplicate_application_ids ?? [];
  const names = duplicates?.duplicate_application_names ?? [];
  return (
    <section className="section-panel panel" aria-labelledby="issues-title">
      <div className="section-heading"><div><p className="eyebrow">C</p><h3 id="issues-title">Validation issues</h3></div></div>
      <div className="issue-messages">
        <p className={`message ${missing.length ? "message-info" : "message-success"}`}>{missing.length ? `Missing configured mandatory CMDB columns: ${missing.join(", ")}` : "All configured mandatory fields were found in the CMDB file."}</p>
        {!codes.length && !ids.length && !names.length ? (
          <p className="message message-success">No duplicate application IDs or names detected from available identity columns.</p>
        ) : (
          <>
            <p className={`message ${codes.length ? "message-info" : "message-success"}`}>{codes.length ? `${codes.length} duplicate Application Code group(s) found.` : "No duplicate Application Codes found."}</p>
            <p className={`message ${ids.length ? "message-info" : "message-success"}`}>{ids.length ? `${ids.length} duplicate application ID group(s) found.` : "No duplicate application IDs found."}</p>
            <p className={`message ${names.length ? "message-info" : "message-success"}`}>{names.length ? `${names.length} duplicate application name group(s) found.` : "No duplicate application names found."}</p>
          </>
        )}
      </div>
      {(codes.length > 0 || ids.length > 0 || names.length > 0) && (
        <div className="duplicate-grid">
          <DuplicateTable title="Duplicate Application Codes" rows={codes} valueHeader="Application Code" />
          <DuplicateTable title="Duplicate application IDs" rows={ids} valueHeader="Application ID" />
          <DuplicateTable title="Duplicate application names" rows={names} valueHeader="Application Name" />
        </div>
      )}
    </section>
  );
}

function EvidenceLabels({ readiness, details }: { readiness: UploadStatusResponse | null; details: ValidationDetailsResponse | null }) {
  const uploaded = (key: "confluence" | "team_validation" | "cloudwatch") => Boolean(readiness?.sources[key]?.uploaded && readiness.sources[key].processed);
  const confluence = uploaded("confluence");
  const team = uploaded("team_validation");
  const cloudwatch = uploaded("cloudwatch");
  const evidence = [confluence && "Confluence", team && "Team Validation", cloudwatch && "CloudWatch"].filter(Boolean).join(", ") || "None uploaded";
  return (
    <section className="section-panel panel" aria-labelledby="evidence-title">
      <div className="section-heading"><div><p className="eyebrow">D</p><h3 id="evidence-title">CMDB source and supporting evidence labels</h3></div></div>
      <p className="calculation-note">Source of Truth: CMDB. Optional files are supporting evidence only.</p>
      <dl className="validation-facts">
        <div><dt>Source of Truth</dt><dd>CMDB</dd></div>
        <div><dt>Supporting Evidence Available</dt><dd>{evidence}</dd></div>
      </dl>
      {details?.records.length ? (
        <SimpleTable<ValidationDetailRow>
          caption="CMDB source and supporting evidence labels"
          columns={[
            { key: "code", header: "Application Code", render: (row) => <strong>{row.application_code ?? row.application_key}</strong> },
            { key: "name", header: "Application Name", render: (row) => row.application_name || "Not available" },
            { key: "truth", header: "Source of Truth", render: () => "CMDB" },
            { key: "confluence", header: "Confluence Evidence Available", render: () => confluence ? "Yes" : "No" },
            { key: "team", header: "Team Validation Evidence Available", render: () => team ? "Yes" : "No" },
            { key: "cloudwatch", header: "CloudWatch Evidence Available", render: () => cloudwatch ? "Yes" : "No" },
            { key: "coverage", header: "Evidence Coverage / Business Validation Support", render: () => evidence },
          ]}
          rows={details.records}
          getRowKey={(row) => `${row.internal_row_number}-${row.application_key}`}
        />
      ) : <p className="muted">No application evidence rows were returned.</p>}
    </section>
  );
}

function TeamValidationChecks({ uploaded, summary }: { uploaded: boolean; summary: TeamValidationSummary | null }) {
  return (
    <section className="section-panel panel" aria-labelledby="team-validation-title">
      <div className="section-heading"><div><p className="eyebrow">E</p><h3 id="team-validation-title">Team validation document checks</h3></div></div>
      {!uploaded ? <p className="message message-info">No team validation document uploaded.</p> : !summary ? (
        <p className="message message-info">Team validation document is uploaded, but validation check results are not available.</p>
      ) : (
        <dl className="validation-facts">
          <div><dt>Row results / rows checked</dt><dd>{summary.row_count}</dd></div>
          <div><dt>Rows with Application Code</dt><dd>{summary.rows_with_application_code}</dd></div>
          <div><dt>Rows missing Application Code</dt><dd>{summary.rows_missing_application_code}</dd></div>
          <div><dt>Invalid Yes/No values</dt><dd>{summary.invalid_yes_no_value_count}</dd></div>
          <div><dt>Unmatched validation rows</dt><dd>{summary.unmatched_team_validation_records}</dd></div>
          <div><dt>Applications missing validation records</dt><dd>{summary.cmdb_applications_missing_team_validation_record}</dd></div>
        </dl>
      )}
    </section>
  );
}

function ConfiguredOutputFamilies({ families, uploaded }: { families: OutputFamiliesConfigResponse | null; uploaded: boolean }) {
  return (
    <section className="section-panel panel" aria-labelledby="families-title">
      <div className="section-heading"><div><p className="eyebrow">F</p><h3 id="families-title">Configured output families</h3></div></div>
      <details className="result-details" open>
        <summary>Configured output families</summary>
        {!uploaded ? <p className="message message-info">Output-family config is not uploaded.</p> : families?.families.length ? (
          <ul className="family-list">{families.families.map((family) => <li key={family.key ?? family.name}>{family.name}</li>)}</ul>
        ) : <p className="message message-info">No output families were returned from the uploaded config.</p>}
      </details>
    </section>
  );
}

function DuplicateTable({ title, rows, valueHeader }: { title: string; rows: DuplicateValue[]; valueHeader: string }) {
  return (
    <div>
      <h4>{title}</h4>
      {rows.length ? (
        <SimpleTable<DuplicateValue>
          caption={title}
          columns={[
            { key: "value", header: valueHeader, render: (row) => <strong>{row.value}</strong> },
            { key: "rows", header: "CMDB row numbers", render: (row) => row.row_numbers.join(", ") },
          ]}
          rows={rows}
          getRowKey={(row) => row.value}
        />
      ) : <p className="muted">No groups.</p>}
    </div>
  );
}

function errorText(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}
