"use client";

import {
  createContext,
  FormEvent,
  ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";

import { postJson } from "@/lib/api";
import type { JobResponse } from "@/types/api";

const STORAGE_KEY = "portfolio-iq-current-job-id";

interface JobContextValue {
  jobId: string;
  hydrated: boolean;
  creating: boolean;
  error: string | null;
  setJobId: (jobId: string) => void;
  createJob: () => Promise<void>;
}

const JobContext = createContext<JobContextValue | null>(null);

export function JobProvider({ children }: { children: ReactNode }) {
  const [jobId, setJobIdState] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setJobIdState(window.localStorage.getItem(STORAGE_KEY) ?? "");
    setHydrated(true);
  }, []);

  const setJobId = (value: string) => {
    const normalized = value.trim();
    setJobIdState(normalized);
    setError(null);
    if (normalized) {
      window.localStorage.setItem(STORAGE_KEY, normalized);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  };

  const createJob = async () => {
    setCreating(true);
    setError(null);
    try {
      const job = await postJson<JobResponse>("/api/jobs");
      setJobId(job.job_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create a job.");
    } finally {
      setCreating(false);
    }
  };

  return (
    <JobContext.Provider
      value={{ jobId, hydrated, creating, error, setJobId, createJob }}
    >
      {children}
    </JobContext.Provider>
  );
}

export function useJob(): JobContextValue {
  const context = useContext(JobContext);
  if (!context) throw new Error("useJob must be used inside JobProvider");
  return context;
}

export function JobControl() {
  const { jobId, creating, error, setJobId, createJob } = useJob();
  const [draft, setDraft] = useState(jobId);

  useEffect(() => setDraft(jobId), [jobId]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setJobId(draft);
  };

  return (
    <section className="job-control" aria-labelledby="job-control-title">
      <div className="eyebrow" id="job-control-title">Current Job</div>
      <div className={`job-badge ${jobId ? "is-active" : ""}`}>
        <span className="status-dot" />
        <span title={jobId}>{jobId || "No job selected"}</span>
      </div>
      <form onSubmit={submit} className="job-form">
        <label htmlFor="job-id">Use existing job ID</label>
        <div className="inline-field">
          <input
            id="job-id"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Paste job ID"
            autoComplete="off"
          />
          <button className="button button-secondary button-compact" type="submit">
            Use
          </button>
        </div>
      </form>
      <button
        className="button button-primary button-full"
        type="button"
        onClick={createJob}
        disabled={creating}
      >
        {creating ? "Creating…" : "+ New Job"}
      </button>
      {error && <p className="message message-error compact-message">{error}</p>}
    </section>
  );
}
