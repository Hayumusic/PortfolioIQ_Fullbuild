"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { JobSummary } from "@/components/job-summary";
import { UploadCard, type UploadCardDefinition } from "@/components/upload-card";
import { useJob } from "@/context/job-context";
import { getJson, uploadFiles } from "@/lib/api";
import type {
  UploadResult,
  UploadSourceKey,
  UploadStatusResponse,
} from "@/types/api";

interface UploadDefinition extends UploadCardDefinition {
  key: UploadSourceKey;
  endpoint: string;
  fieldName: "file" | "files";
}

const requiredUploads: UploadDefinition[] = [
  {
    key: "cmdb",
    title: "CMDB Excel - mandatory",
    description: "The CMDB is the primary application inventory and source of truth.",
    requirement: "Mandatory",
    endpoint: "cmdb",
    fieldName: "file",
    accept: ".xlsx,.xls",
    acceptedLabel: "XLSX or XLS",
  },
  {
    key: "mandatory_fields_config",
    title: "CMDB mandatory-fields config - mandatory",
    description: "Defines exactly which CMDB fields are used for mandatory-field completeness validation.",
    requirement: "Mandatory",
    endpoint: "mandatory-fields-config",
    fieldName: "file",
    accept: ".xlsx,.xls,.csv",
    acceptedLabel: "XLSX, XLS, or CSV",
  },
  {
    key: "output_family_config",
    title: "Output family config - mandatory",
    description: "Defines the configured output families used by output-family analysis.",
    requirement: "Mandatory",
    endpoint: "output-family-config",
    fieldName: "file",
    accept: ".xlsx,.xls,.csv",
    acceptedLabel: "XLSX, XLS, or CSV",
  },
];

const optionalUploads: UploadDefinition[] = [
  {
    key: "confluence",
    title: "Confluence PDF exports - optional",
    description: "Supporting documentation evidence; select one or more exported PDFs.",
    requirement: "Optional",
    endpoint: "confluence",
    fieldName: "files",
    accept: ".pdf",
    acceptedLabel: "PDF (multiple supported)",
    multiple: true,
  },
  {
    key: "team_validation",
    title: "Team validation document - optional",
    description: "Supporting business-validation evidence checked against Application Code.",
    requirement: "Optional",
    endpoint: "team-validation",
    fieldName: "file",
    accept: ".xlsx,.xls,.csv",
    acceptedLabel: "XLSX, XLS, or CSV",
  },
  {
    key: "cloudwatch",
    title: "CloudWatch Excel reports - optional",
    description: "Supporting operational evidence retained for later analysis.",
    requirement: "Optional",
    endpoint: "cloudwatch",
    fieldName: "file",
    accept: ".xlsx,.xls,.csv",
    acceptedLabel: "XLSX, XLS, or CSV",
  },
];

export default function UploadsPage() {
  const { jobId, hydrated } = useJob();
  const [status, setStatus] = useState<UploadStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadInputs = useCallback(async () => {
    if (!jobId) {
      setStatus(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    const encoded = encodeURIComponent(jobId);
    try {
      setStatus(await getJson<UploadStatusResponse>(`/api/jobs/${encoded}/uploads/status`));
    } catch (caught) {
      setStatus(null);
      setError(caught instanceof Error ? caught.message : "Could not load input status.");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    void loadInputs();
  }, [loadInputs]);

  const upload = async (definition: UploadDefinition, selectedFiles: File[]) => {
    const result = await uploadFiles<UploadResult>(
      `/api/jobs/${encodeURIComponent(jobId)}/upload/${definition.endpoint}`,
      definition.fieldName,
      selectedFiles,
    );
    await loadInputs();
    return result;
  };

  const requiredReady = Boolean(
    status && requiredUploads.every(({ key }) => status.sources[key]?.uploaded && status.sources[key]?.processed),
  );

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <h2>Input Uploads</h2>
        </div>
        <JobSummary />
      </section>

      {!jobId && hydrated && (
        <p className="message message-info">Create a New Job or use an existing job ID before uploading files.</p>
      )}

      {loading && <p className="muted">Loading upload status…</p>}
      {error && <p className="message message-error">{error}</p>}

      <UploadGroup title="Required inputs" definitions={requiredUploads} status={status} jobId={jobId} onUpload={upload} />
      <UploadGroup title="Optional inputs" definitions={optionalUploads} status={status} jobId={jobId} onUpload={upload} />

      <section className="mvp-action-area" aria-labelledby="load-validate-title">
        <div>
          <h3 id="load-validate-title">Load and validate inputs</h3>
          <p>Upload the required files, then open CMDB Validation and run validation.</p>
          <p className={`message ${requiredReady ? "message-success" : "message-info"}`}>
            {requiredReady ? "Required inputs are loaded." : "Upload CMDB, mandatory-fields config, and output-family config before analysis."}
          </p>
        </div>
        <Link className={`button button-primary ${!requiredReady ? "disabled" : ""}`} aria-disabled={!requiredReady} href={requiredReady ? "/validation" : "#"}>
          Load and validate inputs
        </Link>
      </section>
    </div>
  );
}

function UploadGroup({
  title,
  definitions,
  status,
  jobId,
  onUpload,
}: {
  title: string;
  definitions: UploadDefinition[];
  status: UploadStatusResponse | null;
  jobId: string;
  onUpload: (definition: UploadDefinition, files: File[]) => Promise<UploadResult>;
}) {
  return (
    <section aria-labelledby={`${title.replaceAll(" ", "-").toLowerCase()}-title`}>
      <div className="section-heading">
        <h3 id={`${title.replaceAll(" ", "-").toLowerCase()}-title`}>{title}</h3>
      </div>
      <div className="upload-list">
        {definitions.map((definition) => (
          <UploadCard
            key={definition.key}
            definition={definition}
            source={status?.sources[definition.key]}
            jobId={jobId}
            disabled={!jobId}
            onUpload={(files) => onUpload(definition, files)}
          />
        ))}
      </div>
    </section>
  );
}
