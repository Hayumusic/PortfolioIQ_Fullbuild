import type { ReactNode } from "react";

import { StatusBadge } from "@/components/status-badge";

export function DataPreview({
  title,
  loaded,
  emptyMessage = "Not uploaded yet.",
  children,
}: {
  title: string;
  loaded: boolean;
  emptyMessage?: string;
  children?: ReactNode;
}) {
  return (
    <article className="preview-card panel">
      <div className="preview-card-heading">
        <h3>{title}</h3>
        <StatusBadge tone={loaded ? "success" : "neutral"}>
          {loaded ? "Loaded" : "Not loaded"}
        </StatusBadge>
      </div>
      {loaded ? children : <p className="preview-empty">{emptyMessage}</p>}
    </article>
  );
}
