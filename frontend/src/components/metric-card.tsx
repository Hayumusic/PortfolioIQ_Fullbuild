import type { ReactNode } from "react";

export function MetricCard({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note?: string;
}) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value ?? "Not available"}</strong>
      {note && <p>{note}</p>}
    </article>
  );
}
