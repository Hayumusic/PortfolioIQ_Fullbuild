"use client";

import { useJob } from "@/context/job-context";

export function JobSummary() {
  const { jobId, hydrated } = useJob();
  return (
    <div className="job-summary">
      <span>Current job</span>
      <strong>{hydrated ? jobId || "Not selected" : "Loading…"}</strong>
    </div>
  );
}
