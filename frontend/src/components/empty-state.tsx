import type { ReactNode } from "react";

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="empty-state compact-empty">
      <div className="empty-icon" aria-hidden="true">—</div>
      <h3>{title}</h3>
      <div className="muted">{children}</div>
    </div>
  );
}
