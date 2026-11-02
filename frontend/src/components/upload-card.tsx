"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import { ErrorMessage } from "@/components/error-message";
import { StatusBadge } from "@/components/status-badge";
import type { UploadResult, UploadSourceStatus } from "@/types/api";

export interface UploadCardDefinition {
  key: string;
  title: string;
  description: string;
  requirement: "Mandatory" | "Optional";
  accept: string;
  acceptedLabel: string;
  multiple?: boolean;
}

export function UploadCard({
  definition,
  source,
  disabled,
  jobId,
  onUpload,
}: {
  definition: UploadCardDefinition;
  source?: UploadSourceStatus;
  disabled: boolean;
  jobId: string;
  onUpload: (files: File[]) => Promise<UploadResult>;
}) {
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setFiles([]);
    setSuccess(null);
    setError(null);
  }, [jobId]);

  const selectFiles = (event: ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(event.currentTarget.files ?? []));
    setSuccess(null);
    setError(null);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!files.length || disabled) return;
    const form = event.currentTarget;
    setUploading(true);
    setSuccess(null);
    setError(null);
    try {
      const result = await onUpload(files);
      setSuccess(result.message);
      setFiles([]);
      const input = form.elements.namedItem("upload-file");
      if (input instanceof HTMLInputElement) input.value = "";
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <article className="upload-row">
      <div className="upload-row-copy">
        <div>
          <h3>{definition.title}</h3>
          <p>{definition.description}</p>
        </div>
        <StatusBadge tone={source?.uploaded ? "success" : "neutral"}>
          {source?.uploaded ? (source.processed ? "Processed" : "Uploaded") : definition.requirement}
        </StatusBadge>
      </div>
      <form className="upload-form" onSubmit={submit}>
        <input
          className="file-input"
          name="upload-file"
          type="file"
          accept={definition.accept}
          multiple={definition.multiple}
          disabled={disabled || uploading}
          onChange={selectFiles}
          aria-label={`Choose ${definition.title} ${definition.multiple ? "files" : "file"}`}
        />
        <button
          className="button button-secondary"
          type="submit"
          disabled={disabled || uploading || files.length === 0}
        >
          {uploading ? "Uploading…" : definition.multiple ? "Upload selected PDFs" : "Upload selected file"}
        </button>
      </form>
      <p className="upload-file-status" title={source?.latest_filename ?? undefined}>
        {source?.latest_filename ? `Uploaded file: ${source.latest_filename}` : `Accepted: ${source?.accepted_file_types?.join(", ") || definition.acceptedLabel}`}
      </p>
      {success && <p className="message message-success" role="status">{success}</p>}
      <ErrorMessage message={error} />
    </article>
  );
}
