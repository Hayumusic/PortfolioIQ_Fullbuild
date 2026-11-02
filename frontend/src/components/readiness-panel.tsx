"use client";

import { ErrorMessage } from "@/components/error-message";
import { StatusBadge } from "@/components/status-badge";
import type { UploadSourceKey, UploadStatusResponse } from "@/types/api";

const requiredInputs: Array<{ key: UploadSourceKey; label: string }> = [
  { key: "cmdb", label: "CMDB Excel" },
  { key: "mandatory_fields_config", label: "CMDB mandatory-fields config" },
  { key: "output_family_config", label: "Output family config" },
];

const optionalInputs: Array<{ key: UploadSourceKey; label: string }> = [
  { key: "confluence", label: "Confluence PDF exports" },
  { key: "team_validation", label: "Team validation document" },
  { key: "cloudwatch", label: "CloudWatch Excel reports" },
];

function uploadedForJob(status: UploadStatusResponse, key: UploadSourceKey): boolean {
  const source = status.sources[key];
  return Boolean(source?.uploaded && source.processed);
}

function fallbackAvailable(status: UploadStatusResponse, key: UploadSourceKey): boolean {
  if (uploadedForJob(status, key)) return false;
  if (key === "mandatory_fields_config") return status.mandatory_fields_config_ready;
  if (key === "output_family_config") return status.output_family_config_ready;
  return false;
}

export function ReadinessPanel({
  status,
  loading,
  error,
  onRefresh,
  compact = false,
}: {
  status: UploadStatusResponse | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  compact?: boolean;
}) {
  const validationReady = Boolean(
    status && uploadedForJob(status, "cmdb") && uploadedForJob(status, "mandatory_fields_config"),
  );
  const outputReady = Boolean(
    status && uploadedForJob(status, "cmdb") && uploadedForJob(status, "output_family_config"),
  );
  const missing = status
    ? requiredInputs.filter(({ key }) => !uploadedForJob(status, key)).map(({ label }) => label)
    : [];

  return (
    <section className={`readiness-panel panel ${compact ? "readiness-panel-compact" : ""}`} aria-live="polite">
      <div className="status-panel-heading">
        <div>
          <p className="eyebrow">Current job</p>
          <h3>Input readiness</h3>
        </div>
        <button className="button button-ghost" onClick={onRefresh} disabled={loading} type="button">
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <ErrorMessage message={error} />
      {!status && !loading && !error && <p className="muted">Select a job to load its input readiness.</p>}
      {status && (
        <>
          <div className="readiness-group">
            <h4>Required inputs</h4>
            <div className="readiness-list">
              {requiredInputs.map(({ key, label }) => {
                const uploaded = uploadedForJob(status, key);
                const fallback = fallbackAvailable(status, key);
                return (
                  <div className="readiness-row" key={key}>
                    <span>{label}</span>
                    <StatusBadge tone={uploaded ? "success" : fallback ? "neutral" : "warning"}>
                      {uploaded ? "Uploaded for this job" : fallback ? "Backend fallback/default available" : "Missing for this job"}
                    </StatusBadge>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="readiness-group">
            <h4>Optional evidence</h4>
            <div className="readiness-list">
              {optionalInputs.map(({ key, label }) => (
                <div className="readiness-row" key={key}>
                  <span>{label}</span>
                  <StatusBadge tone={uploadedForJob(status, key) ? "success" : "neutral"}>
                    {uploadedForJob(status, key) ? "Uploaded" : "Not uploaded"}
                  </StatusBadge>
                </div>
              ))}
            </div>
          </div>

          <div className="readiness-summary">
            <div>
              <span>Missing required inputs</span>
              <strong>{missing.length ? missing.join(", ") : "None"}</strong>
            </div>
            <div>
              <span>Ready for CMDB validation</span>
              <strong className={validationReady ? "ready" : "pending"}>{validationReady ? "Yes" : "No"}</strong>
            </div>
            <div>
              <span>Ready for output family analysis</span>
              <strong className={outputReady ? "ready" : "pending"}>{outputReady ? "Yes" : "No"}</strong>
            </div>
          </div>
          {(fallbackAvailable(status, "mandatory_fields_config") || fallbackAvailable(status, "output_family_config")) && (
            <p className="message message-info fallback-note">
              Backend fallback/default config is available, but it is not treated as a configuration uploaded for this job.
            </p>
          )}
        </>
      )}
    </section>
  );
}
