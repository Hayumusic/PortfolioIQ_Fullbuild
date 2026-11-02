"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { MetricCard } from "@/components/metric-card";
import { StatusBadge } from "@/components/status-badge";
import { useJob } from "@/context/job-context";
import { ApiError, csvDownloadUrl, getUploadStatus, runPortfolioInsights } from "@/lib/api";
import type { PortfolioInsightsResponse } from "@/types/api";

export default function PortfolioInsightsPage() {
  const { jobId, hydrated } = useJob();
  const [insights, setInsights] = useState<PortfolioInsightsResponse | null>(null);
  const [checking, setChecking] = useState(true);
  const [running, setRunning] = useState(false);
  const [cmdbReady, setCmdbReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!hydrated) return;
    setError(null);
    if (!jobId) {
      setCmdbReady(false);
      setInsights(null);
      setChecking(false);
      return;
    }
    setRunning(true);
    try {
      const status = await getUploadStatus(jobId);
      setCmdbReady(status.cmdb_ready);
      if (!status.cmdb_ready) {
        setInsights(null);
        return;
      }
      setInsights(await runPortfolioInsights(jobId));
    } catch (caught) {
      setInsights(null);
      if (caught instanceof ApiError && caught.status === 404) setError("Portfolio Insights could not find the current CMDB. Upload or select a job with CMDB data, then refresh.");
      else setError(caught instanceof Error ? caught.message : "Could not load Portfolio Insights.");
    } finally {
      setRunning(false);
      setChecking(false);
    }
  }, [hydrated, jobId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const result = insights;
  const summary = result?.summary;
  const executive = result?.executive_summary;

  return <div className="page-stack portfolio-insights-page">
    <section className="page-heading">
      <div><h2>Portfolio Insights</h2><p>Executive portfolio health, evidence-backed risks, and actions from the current analysis job.</p></div>
      <button className="button button-primary" type="button" disabled={!jobId || running || !cmdbReady} onClick={() => void refresh()}>{running ? "Refreshing insights…" : "Refresh insights"}</button>
    </section>
    {checking && <p className="muted">Loading portfolio insights…</p>}
    {!checking && !jobId && <p className="message message-info">Select or create a job, then upload the CMDB to view Portfolio Insights.</p>}
    {!checking && jobId && !cmdbReady && <p className="message message-info">A current-session CMDB is required for Portfolio Insights.</p>}
    {error && <p className="message message-error" role="alert">{error}</p>}
    {result && summary && executive && <>
      <section className="metric-grid portfolio-insights-metrics" aria-label="Portfolio summary metrics">
        <MetricCard label="Applications" value={summary.total_applications.toLocaleString()} note="In the current CMDB" />
        <MetricCard label="Portfolios" value={summary.total_portfolios.toLocaleString()} note="Including unassigned applications" />
        <MetricCard label="High and critical risks" value={(summary.high_risk_count + summary.critical_risk_count).toLocaleString()} note={`${summary.critical_risk_count} critical · ${summary.high_risk_count} high`} />
        <MetricCard label="Possible duplicates" value={count(executive.possible_duplicate_count)} note="From available similarity analysis" />
        <MetricCard label="Action items" value={summary.action_item_count.toLocaleString()} note="Recommended follow-up actions" />
        <MetricCard label="CMDB completeness" value={percent(executive.cmdb_completeness_percent)} note="Mandatory-field completeness" />
        <MetricCard label="Source of truth" value={summary.source_of_truth_label} note={`Reliability: ${summary.reliability_label}`} />
        <MetricCard label="Analysis modules" value={`${summary.available_module_count} / ${summary.available_module_count + summary.missing_module_count}`} note={`${summary.missing_module_count} unavailable`} />
      </section>

      <section className="panel section-panel" aria-labelledby="executive-summary-title">
        <div className="section-heading"><div><h3 id="executive-summary-title">Executive summary</h3><p>Findings and limits are based on evidence available in this job.</p></div><StatusBadge tone={result.analysis_status === "completed" ? "success" : "warning"}>{result.analysis_status === "completed" ? "Complete" : "Complete with warnings"}</StatusBadge></div>
        <div className="portfolio-insights-summary-grid">
          <div><h4>Key findings</h4>{executive.key_findings.length ? <ul>{executive.key_findings.map((finding, index) => <li key={`${index}-${finding}`}>{finding}</li>)}</ul> : <p className="muted">No portfolio findings were generated from the available inputs.</p>}</div>
          <div><h4>Limitations</h4>{executive.limitations.length ? <ul>{executive.limitations.map((limitation, index) => <li key={`${index}-${limitation}`}>{limitation}</li>)}</ul> : <p className="muted">No analysis limitations were reported.</p>}</div>
        </div>
      </section>

      {result.warnings.length > 0 && <section className="panel section-panel" aria-labelledby="insights-warnings-title"><h3 id="insights-warnings-title">Warnings</h3><ul className="portfolio-insights-warnings">{result.warnings.map((warning, index) => <li key={`${index}-${warning}`}>{warning}</li>)}</ul></section>}

      <section className="panel section-panel" aria-labelledby="module-status-title">
        <div className="section-heading"><div><h3 id="module-status-title">Analysis module status</h3><p>Portfolio findings use only modules with current-job results.</p></div></div>
        <DataTable headers={["Module", "Status", "Analysis status", "Key metrics", "Warnings"]} rows={result.module_status.map((module) => ({ id: module.module_name, cells: [moduleLabel(module.module_name), <StatusBadge key="status" tone={module.status === "available" ? "success" : module.status === "error" ? "danger" : "warning"}>{module.status}</StatusBadge>, module.analysis_status || "Not run", Object.entries(module.key_metrics).filter(([, value]) => value !== null && value !== undefined).map(([key, value]) => `${humanize(key)}: ${value}`).join(" · ") || "No metrics available", module.warnings.join("; ") || "—"] }))} empty="No module status is available." />
      </section>

      <section className="panel section-panel" aria-labelledby="portfolio-scorecard-title">
        <div className="section-heading"><div><h3 id="portfolio-scorecard-title">Portfolio scorecards</h3><p>Compare application volume, completeness, risks, and cross-module findings.</p></div><a className="button button-secondary" href={csvDownloadUrl(result.detail_endpoints.portfolio_scorecard_csv_endpoint)}>Download CSV</a></div>
        <DataTable headers={["Portfolio", "Applications", "Completeness", "Critical apps", "Possible duplicates", "Obsolete tech indicators", "Integrations", "Unmapped outputs", "Risks", "Highest risk"]} rows={result.top_portfolio_scorecards.map((portfolio) => ({ id: portfolio.portfolio, cells: [portfolio.portfolio, portfolio.application_count.toLocaleString(), percent(portfolio.completeness_percent), portfolio.critical_application_count.toLocaleString(), count(portfolio.possible_duplicate_count), count(portfolio.obsolete_indicator_count), count(portfolio.explicit_integration_count), count(portfolio.unmapped_output_family_application_count), portfolio.risk_count.toLocaleString(), portfolio.highest_risk_severity || "—"] }))} empty="No portfolio scorecards are available." />
      </section>

      <section className="panel section-panel" aria-labelledby="risk-register-title">
        <div className="section-heading"><div><h3 id="risk-register-title">Risk register</h3><p>Showing the highest-priority risks returned for this analysis.</p></div><a className="button button-secondary" href={csvDownloadUrl(result.detail_endpoints.risks_csv_endpoint)}>Download CSV</a></div>
        <DataTable headers={["Severity", "Application", "Portfolio", "Risk", "Evidence", "Recommended action", "Source", "Confidence"]} rows={result.risk_sample.map((risk) => ({ id: risk.risk_id, cells: [<StatusBadge key="severity" tone={severityTone(risk.severity)}>{risk.severity}</StatusBadge>, applicationLabel(risk.application_name, risk.application_code), risk.portfolio || "Unassigned", humanize(risk.risk_type), risk.evidence, risk.recommended_action, moduleLabel(risk.evidence_module), risk.confidence] }))} empty="No risks were identified from available module results." />
      </section>

      <section className="panel section-panel" aria-labelledby="action-items-title">
        <div className="section-heading"><div><h3 id="action-items-title">Recommended actions</h3><p>Actions are linked to their source risks and available evidence.</p></div><a className="button button-secondary" href={csvDownloadUrl(result.detail_endpoints.action_items_csv_endpoint)}>Download CSV</a></div>
        <DataTable headers={["Priority", "Application", "Portfolio", "Action", "Owner hint", "Evidence module"]} rows={result.action_item_sample.map((action) => ({ id: action.action_id, cells: [<StatusBadge key="priority" tone={severityTone(action.priority)}>{action.priority}</StatusBadge>, applicationLabel(action.application_name, action.application_code), action.portfolio || "Unassigned", action.description, action.owner_hint || "Not specified", moduleLabel(action.evidence_module)] }))} empty="No action items are available." />
      </section>
    </>}
  </div>;
}

function DataTable({ headers, rows, empty }: { headers: string[]; rows: Array<{ id: string; cells: ReactNode[] }>; empty: string }) {
  if (!rows.length) return <p className="message message-info">{empty}</p>;
  return <div className="table-scroll portfolio-insights-table"><table className="simple-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.id}>{row.cells.map((cell, index) => <td key={`${row.id}-${index}`}>{cell}</td>)}</tr>)}</tbody></table></div>;
}

function count(value: number | null): string { return value === null ? "Not available" : value.toLocaleString(); }
function percent(value: number | null): string { return value === null ? "Not available" : `${value.toFixed(1)}%`; }
function applicationLabel(name: string | null, code: string | null): string { return name && code ? `${name} (${code})` : name || code || "Application unavailable"; }
function humanize(value: string): string { return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()); }
function moduleLabel(value: string): string { return ({ cmdb_preview: "CMDB", validation: "CMDB Validation", dashboard: "Dashboard Metrics", similarity: "Similarity and Redundancy", technology: "Technology and Integration", output_families: "Application Outputs" } as Record<string, string>)[value] ?? humanize(value); }
function severityTone(value: string): "success" | "warning" | "neutral" | "danger" { if (value === "critical") return "danger"; if (value === "high") return "warning"; if (value === "medium") return "warning"; if (value === "low") return "neutral"; return "neutral"; }
