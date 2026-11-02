import type { ReactNode } from "react";

export function ActionBar({ title, description, children }: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="action-bar panel">
      <div>
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      <div className="action-bar-actions">{children}</div>
    </section>
  );
}
