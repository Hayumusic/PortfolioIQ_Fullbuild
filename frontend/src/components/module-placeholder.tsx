import { JobSummary } from "@/components/job-summary";

interface ModulePlaceholderProps {
  title: string;
  purpose: string;
  endpoint: string;
}

export function ModulePlaceholder({ title, purpose, endpoint }: ModulePlaceholderProps) {
  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Analysis module</p>
          <h2>{title}</h2>
          <p>{purpose}</p>
        </div>
        <JobSummary />
      </section>
      <section className="empty-state panel">
        <div className="empty-icon" aria-hidden="true">→</div>
        <h3>Ready for the next frontend phase</h3>
        <p>
          This page is connected to the shared job workspace. It will call
          <code>{endpoint}</code> and render only backend-provided results.
        </p>
        <p className="muted">No analysis has been run or simulated on this page.</p>
      </section>
    </div>
  );
}
