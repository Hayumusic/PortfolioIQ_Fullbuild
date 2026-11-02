"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState, type FormEvent } from "react";
import { useJob } from "@/context/job-context";
import { ApiError, getCmdbApplications, getCmdbColumns, getSimilarityAlerts, getSimilarityApps, getSimilarityClusters, getSimilarityHeatmap, getSimilarityRules, getSimilaritySummary, getUploadStatus, runSimilarityAnalysis } from "@/lib/api";
import type { HeatmapApplication, SimilarAppsGroup, SimilarityAlertsResponse, SimilarityAnalysisResponse, SimilarityClustersResponse, SimilarityHeatmapResponse, UploadStatusResponse } from "@/types/api";

type RuleKey = "businessUseCase" | "businessFunction" | "capability" | "supportedProcess";
type FieldSelections = Record<RuleKey, string>;
type WeightSelections = Record<RuleKey, string>;
type HeatmapLimit = 25 | 50 | 100 | "all";
type SimilarAppsLimit = 5 | 10 | 25 | 50;
type AlertLimit = 25 | 50 | 100 | 200;
type ScoreRange = "50-100" | "20-100" | "0-100" | "0-10" | "11-20" | "21-30" | "31-40" | "41-50" | "51-60" | "61-70" | "71-80" | "81-90" | "91-100";

export const similarityTabs = ["App vs App Heatmap", "Similar Apps Panel", "Cluster Map", "Redundancy Alerts"] as const;
const similarityRules = [
  { key: "businessUseCase", apiKey: "business_use_case", label: "Business Use Case", defaultFields: ["Business Use Case"] },
  { key: "businessFunction", apiKey: "business_function", label: "Business Function", defaultFields: ["Business Function"] },
  { key: "capability", apiKey: "capability", label: "Capability", defaultFields: ["Capability"] },
  { key: "supportedProcess", apiKey: "supported_process", label: "Supported Process", defaultFields: ["Supported Process", "Business Process"] },
] as const;
const scoreRanges: Array<{ value: ScoreRange; label: string }> = [
  { value: "50-100", label: "50% or higher" }, { value: "0-100", label: "All Percentage" },
  { value: "20-100", label: "20% or higher" },
  { value: "0-10", label: "0–10%" }, { value: "11-20", label: "11–20%" },
  { value: "21-30", label: "21–30%" }, { value: "31-40", label: "31–40%" },
  { value: "41-50", label: "41–50%" }, { value: "51-60", label: "51–60%" },
  { value: "61-70", label: "61–70%" }, { value: "71-80", label: "71–80%" },
  { value: "81-90", label: "81–90%" }, { value: "91-100", label: "91–100%" },
];
const emptyFields: FieldSelections = { businessUseCase: "", businessFunction: "", capability: "", supportedProcess: "" };
const defaultWeights: WeightSelections = { businessUseCase: "30", businessFunction: "30", capability: "20", supportedProcess: "10" };

function appLabel(name: string, code: string): string {
  if (name && code) return `${name} (${code})`;
  if (code) return `Missing Name (${code})`;
  if (name) return `${name} (Missing Code)`;
  return "Missing Application";
}
function score(value: number | null | undefined): string { return value == null ? "Not Comparable" : `${value.toFixed(2)}%`; }
function identity(app: HeatmapApplication): string { return app.application_key || `${app.application_code}\u0000${app.application_name}`; }
function defaultDimensionFields(columns: string[]): FieldSelections {
  return similarityRules.reduce<FieldSelections>((result, rule) => {
    result[rule.key] = columns.find((column) => rule.defaultFields.some((field) => column.toLocaleLowerCase() === field.toLocaleLowerCase())) ?? "";
    return result;
  }, { ...emptyFields });
}

export default function SimilarityPage() {
  const { jobId, hydrated } = useJob();
  const [activeTab, setActiveTab] = useState(0);
  const [status, setStatus] = useState<UploadStatusResponse | null>(null);
  const [cmdbColumns, setCmdbColumns] = useState<string[]>([]);
  const [applications, setApplications] = useState<HeatmapApplication[]>([]);
  const [selectedApplicationKey, setSelectedApplicationKey] = useState("");
  const [selectedHeatmapApplicationKey, setSelectedHeatmapApplicationKey] = useState("");
  const [fields, setFields] = useState<FieldSelections>(emptyFields);
  const [weights, setWeights] = useState<WeightSelections>(defaultWeights);
  const [heatmapLimit, setHeatmapLimit] = useState<HeatmapLimit>("all");
  const [heatmapSearch, setHeatmapSearch] = useState("");
  const [heatmapApplicationSearch, setHeatmapApplicationSearch] = useState("");
  const [portfolio, setPortfolio] = useState("");
  const [heatmapScoreRange, setHeatmapScoreRange] = useState<ScoreRange>("50-100");
  const [heatmapExcludedKeys, setHeatmapExcludedKeys] = useState<string[]>([]);
  const [heatmapExclusionSearch, setHeatmapExclusionSearch] = useState("");
  const [similarExcludedKeys, setSimilarExcludedKeys] = useState<string[]>([]);
  const [similarExclusionSearch, setSimilarExclusionSearch] = useState("");
  const [alertExcludedKeys, setAlertExcludedKeys] = useState<string[]>([]);
  const [alertExclusionSearch, setAlertExclusionSearch] = useState("");
  const [similarApplied, setSimilarApplied] = useState<{ applicationKey: string; limit: SimilarAppsLimit; portfolio: string; excludedKeys: string[] }>({ applicationKey: "", limit: 5, portfolio: "", excludedKeys: [] });
  const [alertSearchClick, setAlertSearchClick] = useState(0);
  const [heatmapSearchClick, setHeatmapSearchClick] = useState(0);
  const [portfolioOptions, setPortfolioOptions] = useState<string[]>([]);
  const [similarAppsLimit, setSimilarAppsLimit] = useState<SimilarAppsLimit>(5);
  const [similarAppsPortfolio, setSimilarAppsPortfolio] = useState("");
  const [alertLimit, setAlertLimit] = useState<AlertLimit>(25);
  const [alertScoreRange, setAlertScoreRange] = useState<ScoreRange>("20-100");
  const [alertsPortfolio, setAlertsPortfolio] = useState("");
  const [similarApplicationSearch, setSimilarApplicationSearch] = useState("");
  const [heatmap, setHeatmap] = useState<SimilarityHeatmapResponse | null>(null);
  const [selectedGroup, setSelectedGroup] = useState<SimilarAppsGroup | null>(null);
  const [clusters, setClusters] = useState<SimilarityClustersResponse | null>(null);
  const [alerts, setAlerts] = useState<SimilarityAlertsResponse | null>(null);
  const [analysisRun, setAnalysisRun] = useState(false);
  const [analysisSummary, setAnalysisSummary] = useState<SimilarityAnalysisResponse["summary"] | null>(null);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sessionMissing, setSessionMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tabSetId = useId();
  const heatmapRequestId = useRef(0);

  const clearResults = useCallback(() => {
    heatmapRequestId.current += 1;
    setHeatmap(null); setSelectedGroup(null); setClusters(null); setAlerts(null); setAnalysisRun(false); setAnalysisSummary(null); setPortfolioOptions([]);
  }, []);
  const loadHeatmap = useCallback(async (currentJobId: string, limit: HeatmapLimit, query: string, selectedPortfolio: string, applicationKey: string, scoreRange: ScoreRange, excludedKeys: string[]) => {
    const requestId = ++heatmapRequestId.current;
    const response = await getSimilarityHeatmap(currentJobId, limit === "all" ? Math.max(1, applications.length) : limit, query, selectedPortfolio, applicationKey, scoreRange, excludedKeys);
    if (requestId !== heatmapRequestId.current) return;
    setHeatmap(response); setPortfolioOptions(response.portfolio_options);
  }, [applications.length]);
  const loadResults = useCallback(async (currentJobId: string) => {
    try {
      const [rules, summaryResults, clusterResults, alertResults] = await Promise.all([getSimilarityRules(currentJobId), getSimilaritySummary(currentJobId), getSimilarityClusters(currentJobId), getSimilarityAlerts(currentJobId, 25)]);
      setApplications(rules.applications); setPortfolioOptions(rules.portfolio_options); setAnalysisSummary(summaryResults.summary); setClusters(clusterResults); setAlerts(alertResults); setAnalysisRun(true);
      if (Object.keys(rules.rules_config.dimension_fields_used ?? {}).length === similarityRules.length) {
        const restored = similarityRules.reduce<FieldSelections>((result, rule) => { result[rule.key] = rules.rules_config.dimension_fields_used[rule.apiKey] ?? ""; return result; }, { ...emptyFields });
        setFields(restored);
        setWeights(similarityRules.reduce<WeightSelections>((result, rule) => { result[rule.key] = String(rules.rules_config.field_weights_used[rule.apiKey] ?? 0); return result; }, { ...defaultWeights }));
      }
      return true;
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 404) { clearResults(); return false; }
      throw caught;
    }
  }, [clearResults]);
  const loadStatus = useCallback(async () => {
    if (!jobId) { setStatus(null); setCmdbColumns([]); setApplications([]); setFields(emptyFields); setSessionMissing(false); setError(null); clearResults(); return; }
    setLoading(true); setSessionMissing(false); setError(null);
    try {
      const currentStatus = await getUploadStatus(jobId); setStatus(currentStatus);
      if (!currentStatus.cmdb_ready) { setCmdbColumns([]); setApplications([]); setFields(emptyFields); clearResults(); return; }
      const [columns, appResponse] = await Promise.all([getCmdbColumns(jobId), getCmdbApplications(jobId)]);
      setCmdbColumns(columns.columns);
      setApplications(appResponse.applications.map((app, index) => ({ application_key: `app-${index}`, application_code: app.application_code ?? "", application_name: app.application_name ?? "", portfolio: "", strongest_similarity_score: null })));
      // Defaults only use like-named functional columns. In particular,
      // Portfolio is never substituted for Supported Process and Description
      // is never fanned out across missing dimensions. Stored explicit
      // dimension selections, when present, are restored by loadResults.
      setFields(defaultDimensionFields(columns.columns));
      const hasSavedResults = await loadResults(jobId);
      if (!hasSavedResults) {
        const defaults = defaultDimensionFields(columns.columns);
        if (similarityRules.every(({ key }) => defaults[key])) {
          const selectedFields = similarityRules.map(({ key }) => defaults[key]);
          const fieldWeights = similarityRules.reduce<Record<string, number>>((result, rule) => { result[defaults[rule.key]] = Number(defaultWeights[rule.key]); return result; }, {});
          const dimensionFields = similarityRules.reduce<Record<string, string>>((result, rule) => { result[rule.apiKey] = defaults[rule.key]; return result; }, {});
          const dimensionWeights = similarityRules.reduce<Record<string, number>>((result, rule) => { result[rule.apiKey] = Number(defaultWeights[rule.key]); return result; }, {});
          setRunMessage("Preparing similarity results for this CMDB using the configured functional fields…");
          await runSimilarityAnalysis(jobId, { selected_fields: selectedFields, field_weights: fieldWeights, dimension_fields: dimensionFields, dimension_weights: dimensionWeights });
          await loadResults(jobId);
          setRunMessage("Similarity results are ready. Adjust filters to explore the matches.");
        }
      }
    } catch (caught) {
      setStatus(null); setCmdbColumns([]); setApplications([]); clearResults();
      if (caught instanceof ApiError && caught.status === 404) setSessionMissing(true);
      else setError(caught instanceof Error ? caught.message : "Could not load CMDB status.");
    } finally { setLoading(false); }
  }, [clearResults, jobId, loadResults]);
  useEffect(() => { setRunMessage(null); setRunError(null); void loadStatus(); }, [loadStatus]);

  const cmdbLoaded = Boolean(jobId && status?.cmdb_ready && cmdbColumns.length);
  const invalidField = similarityRules.some(({ key }) => !fields[key] || !cmdbColumns.includes(fields[key]));
  const invalidWeight = similarityRules.some(({ key }) => weights[key].trim() === "" || !Number.isFinite(Number(weights[key])) || Number(weights[key]) < 0);
  const allWeightsZero = !invalidWeight && similarityRules.every(({ key }) => Number(weights[key]) === 0);
  const disabledReason = !hydrated || loading ? "Checking current CMDB inputs." : !cmdbLoaded ? "Load CMDB inputs before running similarity analysis." : invalidField ? "Select valid CMDB fields for similarity analysis." : invalidWeight ? "Similarity weights must be non-negative numbers." : allWeightsZero ? "At least one similarity weight must be greater than zero." : running ? "Running similarity analysis. This can take a few moments for large CMDB files." : null;

  const submitRules = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!jobId || disabledReason) return;
    const selectedFields = similarityRules.map(({ key }) => fields[key]);
    const fieldWeights = similarityRules.reduce<Record<string, number>>((result, { key }) => { result[fields[key]] = (result[fields[key]] ?? 0) + Number(weights[key]); return result; }, {});
    const dimensionFields = similarityRules.reduce<Record<string, string>>((result, rule) => { result[rule.apiKey] = fields[rule.key]; return result; }, {});
    const dimensionWeights = similarityRules.reduce<Record<string, number>>((result, rule) => { result[rule.apiKey] = Number(weights[rule.key]); return result; }, {});
    setRunning(true); setRunError(null); setRunMessage("Running similarity analysis. This can take a few moments for large CMDB files.");
    try {
      const completed = await runSimilarityAnalysis(jobId, { selected_fields: selectedFields, field_weights: fieldWeights, dimension_fields: dimensionFields, dimension_weights: dimensionWeights });
      setHeatmapSearch(""); setPortfolio(""); setHeatmapLimit("all"); setHeatmapScoreRange("50-100"); setHeatmapExcludedKeys([]); setHeatmapExclusionSearch(""); setSimilarExcludedKeys([]); setSimilarExclusionSearch(""); setAlertExcludedKeys([]); setAlertExclusionSearch(""); setSimilarAppsLimit(5); setAlertLimit(25); setAlertScoreRange("20-100"); setSelectedGroup(null);
      await loadResults(jobId); setRunMessage(`Similarity analysis completed in ${completed.summary.analysis_elapsed_seconds.toFixed(2)} seconds for ${completed.summary.total_applications_analyzed.toLocaleString()} applications.`);
    } catch (caught) { setRunMessage(null); setRunError(caught instanceof Error ? caught.message : "Similarity analysis failed."); }
    finally { setRunning(false); }
  };

  useEffect(() => {
    heatmapRequestId.current += 1;
    setHeatmap(null);
    if (!jobId || !analysisRun) return;
    const timeout = window.setTimeout(() => { void loadHeatmap(jobId, heatmapLimit, heatmapSearch, portfolio, selectedHeatmapApplicationKey, heatmapScoreRange, heatmapExcludedKeys).catch((caught) => setRunError(caught instanceof Error ? caught.message : "Could not load heatmap data.")); }, 200);
    return () => window.clearTimeout(timeout);
  }, [analysisRun, heatmapExcludedKeys, heatmapLimit, heatmapScoreRange, jobId, loadHeatmap, portfolio, selectedHeatmapApplicationKey, heatmapSearch, heatmapSearchClick]);
  useEffect(() => {
    if (!jobId || !analysisRun || !similarApplied.applicationKey) { setSelectedGroup(null); return; }
    void getSimilarityApps(jobId, similarApplied.applicationKey, similarApplied.limit, similarApplied.portfolio, similarApplied.excludedKeys).then((response) => setSelectedGroup(response.applications[0] ?? null)).catch((caught) => setRunError(caught instanceof Error ? caught.message : "Could not load similar applications."));
  }, [analysisRun, jobId, similarApplied]);
  useEffect(() => {
    if (!jobId || !analysisRun) return;
    void getSimilarityAlerts(jobId, alertLimit, alertScoreRange, alertsPortfolio, alertExcludedKeys).then(setAlerts).catch((caught) => setRunError(caught instanceof Error ? caught.message : "Could not load redundancy candidates."));
  }, [alertLimit, alertScoreRange, alertsPortfolio, analysisRun, alertExcludedKeys, jobId, alertSearchClick]);

  const heatmapScores = useMemo(() => {
    const values = new Map<string, number>();
    for (const cell of heatmap?.matrix ?? []) { values.set(`${cell.anchor_application_key}\u0001${cell.candidate_application_key}`, cell.similarity_score); }
    return values;
  }, [heatmap]);
  const dimensionDetail = (item: SimilarAppsGroup["similar_applications"][number], key: RuleKey) => {
    const apiKey = similarityRules.find((rule) => rule.key === key)?.apiKey ?? key;
    const detail = item.component_details[apiKey];
    if (!detail?.comparable) return `Not Comparable — ${detail?.reason || "usable evidence is unavailable"}`;
    const evidence = detail.evidence.length ? ` Evidence: ${detail.evidence.join(", ")}.` : "";
    return `${score(detail.score)} — ${detail.reason}.${evidence}`;
  };
  const emptyState = analysisRun ? "No comparable similarity results are available for the configured fields." : "Similarity results are not available yet.";
  const similarSearchPending = selectedApplicationKey !== similarApplied.applicationKey || similarAppsPortfolio !== similarApplied.portfolio || similarAppsLimit !== similarApplied.limit || JSON.stringify(similarExcludedKeys) !== JSON.stringify(similarApplied.excludedKeys);

  return <div className="page-stack">
    <section className="page-heading"><div><h2>2. Application Similarity and Redundancy</h2><p>Analyze the current CMDB portfolio with deterministic, configurable comparison rules.</p></div></section>
    {hydrated && (!jobId || sessionMissing) && <p className="message message-info">Load CMDB inputs before running similarity analysis.</p>}
    {hydrated && jobId && !sessionMissing && !loading && status && !status.cmdb_ready && <p className="message message-info">Load CMDB inputs before running similarity analysis.</p>}
    {hydrated && status?.cmdb_ready && !loading && !error && <p className="message message-success">CMDB loaded</p>}
    {loading && <p className="muted">Checking CMDB status…</p>}{error && <p className="message message-error">{error}</p>}
    <section className="similarity-rules panel" aria-labelledby="similarity-rules-title">
      <div className="section-heading"><div><h3 id="similarity-rules-title">Similarity rules</h3><p>Select real fields from the current CMDB. Weights are normalized automatically.</p></div></div>
      <form onSubmit={submitRules}><div className="table-scroll"><table className="simple-table similarity-rules-table"><thead><tr><th>Rule</th><th>CMDB field</th><th>Weight</th></tr></thead><tbody>{similarityRules.map((rule) => <tr key={rule.key}><th scope="row">{rule.label}</th><td><label className="visually-hidden" htmlFor={`${rule.key}-field`}>{rule.label} field</label><select id={`${rule.key}-field`} value={fields[rule.key]} disabled={!cmdbLoaded || running} onChange={(event) => setFields((current) => ({ ...current, [rule.key]: event.target.value }))}><option value="">Select a CMDB field</option>{cmdbColumns.map((column) => <option key={column} value={column}>{column}</option>)}</select></td><td><label className="visually-hidden" htmlFor={`${rule.key}-weight`}>{rule.label} weight</label><input id={`${rule.key}-weight`} type="number" min="0" step="any" value={weights[rule.key]} disabled={running} onChange={(event) => setWeights((current) => ({ ...current, [rule.key]: event.target.value }))} /></td></tr>)}</tbody></table></div>
        <p className="similarity-rules-note">Weights do not need to total 100; the engine normalizes every non-negative configuration.</p>
        <div className="similarity-rules-actions"><button className="button button-primary" type="submit" disabled={Boolean(disabledReason)}>Run similarity analysis</button>{disabledReason && !running && <p className="field-error" role="alert">{disabledReason}</p>}{runMessage && <p className="muted" role="status">{runMessage}</p>}</div>{runError && <p className="message message-error similarity-run-error" role="alert">{runError}</p>}
      </form>
      {analysisSummary && <p className="similarity-rules-note" role="status">Similarity analysis completed in {analysisSummary.analysis_elapsed_seconds.toFixed(2)} seconds for {analysisSummary.total_applications_analyzed.toLocaleString()} applications. {analysisSummary.total_candidate_pairs_evaluated.toLocaleString()} candidate pairs evaluated. Analysis time varies with portfolio size and available evidence.</p>}
    </section>
    <section className="similarity-tabs" aria-label="Similarity views">
      <div className="similarity-tab-list" role="tablist" aria-label="Similarity views">{similarityTabs.map((tab, index) => <button className="similarity-tab" id={`${tabSetId}-tab-${index}`} key={tab} type="button" role="tab" aria-controls={`${tabSetId}-panel-${index}`} aria-selected={activeTab === index} tabIndex={activeTab === index ? 0 : -1} onClick={() => setActiveTab(index)}>{tab}</button>)}</div>
      <div className="similarity-tab-panel panel" id={`${tabSetId}-panel-${activeTab}`} role="tabpanel" aria-labelledby={`${tabSetId}-tab-${activeTab}`} tabIndex={0}>
        {activeTab === 0 && <HeatmapView heatmap={heatmap} applications={applications} analysisRun={analysisRun} emptyState={emptyState} search={heatmapSearch} setSearch={setHeatmapSearch} applicationSearch={heatmapApplicationSearch} setApplicationSearch={setHeatmapApplicationSearch} selectedApplicationKey={selectedHeatmapApplicationKey} setSelectedApplicationKey={setSelectedHeatmapApplicationKey} portfolio={portfolio} setPortfolio={setPortfolio} portfolios={portfolioOptions} limit={heatmapLimit} setLimit={setHeatmapLimit} scoreRange={heatmapScoreRange} setScoreRange={setHeatmapScoreRange} excludedApplicationKeys={heatmapExcludedKeys} setExcludedApplicationKeys={setHeatmapExcludedKeys} exclusionSearch={heatmapExclusionSearch} setExclusionSearch={setHeatmapExclusionSearch} scores={heatmapScores} onSearch={() => setHeatmapSearchClick((value) => value + 1)} />}
        {activeTab === 1 && <section aria-labelledby="similar-apps-title"><h3 id="similar-apps-title">Similar applications</h3><div className="similarity-filter-grid"><SearchableApplication label="Application" applications={applications} query={similarApplicationSearch} onQueryChange={(value, key) => { setSimilarApplicationSearch(value); setSelectedApplicationKey(key); }} /><label>Portfolio<select value={similarAppsPortfolio} onChange={(event) => setSimilarAppsPortfolio(event.target.value)}><option value="">All Portfolios</option>{portfolioOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label>Show similar applications<select value={similarAppsLimit} onChange={(event) => setSimilarAppsLimit(Number(event.target.value) as SimilarAppsLimit)}>{[5, 10, 25, 50].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><ExclusionMultiSelect applications={applications} selectedApplicationKey={selectedApplicationKey} selectedKeys={similarExcludedKeys} setSelectedKeys={setSimilarExcludedKeys} search={similarExclusionSearch} setSearch={setSimilarExclusionSearch} /><button className="button button-primary" type="button" onClick={() => setSimilarApplied({ applicationKey: selectedApplicationKey, limit: similarAppsLimit, portfolio: similarAppsPortfolio, excludedKeys: [...similarExcludedKeys] })}>Search</button></div>{!selectedApplicationKey ? <p className="message message-info">Search for and select an application to view its closest matches.</p> : !analysisRun ? <p className="message message-info">Similarity results are not available yet.</p> : similarSearchPending ? <p className="message message-info">Choose the application and filters, then select Search to load its matches.</p> : !selectedGroup?.similar_applications.length ? <p className="message message-info">No similar applications with comparable functional evidence were found.</p> : <ResultTable headers={["Similar Application", "Portfolio", "Overall Similarity", "Similarity Reason", "Evidence"]} rows={selectedGroup.similar_applications.map((item) => { const matched = Object.entries(item.component_details).filter(([, detail]) => detail.comparable && detail.score !== null && detail.score > 0).map(([key]) => key.replaceAll("_", " ")); const reason = matched.length ? `Shared ${matched.join(", ")} functionality supports this match.` : item.similarity_reason; const application = applications.find((app) => app.application_code === item.application_code && app.application_name === item.application_name); return [item.application_name || "Missing Name", application?.portfolio || "Not Available", score(item.similarity_score), reason, item.evidence.join("; ") || item.matched_fields.join(", ") || "No additional evidence"] })} />}</section>}
        {activeTab === 2 && <section aria-labelledby="clusters-title"><h3 id="clusters-title">Similarity clusters</h3>{!clusters?.clusters.length ? <p className="message message-info">{analysisRun ? "No multi-application clusters satisfy the internal grouping rule." : emptyState}</p> : <div className="cluster-accordion-list">{clusters.clusters.map((cluster) => <details className="cluster-accordion" key={cluster.cluster}><summary>{cluster.cluster} · {cluster.application_count} applications · {score(cluster.average_similarity)}</summary><ResultTable headers={["Applications", "Comparable Dimensions", "Common Cluster Function", "Why These Apps Were Clustered", "Average Calculation"]} rows={[[cluster.applications.map((app) => appLabel(app.application_name, app.application_code)).join(", "), String(cluster.comparable_dimension_count), cluster.common_cluster_function, cluster.cluster_reason, cluster.average_calculation]]} /></details>)}</div>}</section>}
        {activeTab === 3 && <section aria-labelledby="alerts-title"><div className="similarity-view-heading"><div><h3 id="alerts-title">Potential redundancy candidates</h3></div><div className="similarity-filter-grid"><label>Similarity percentage<select value={alertScoreRange} onChange={(event) => setAlertScoreRange(event.target.value as ScoreRange)}>{scoreRanges.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}</select></label><label>Portfolio<select value={alertsPortfolio} onChange={(event) => setAlertsPortfolio(event.target.value)}><option value="">All Portfolios</option>{portfolioOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></label><label>Show candidates<select value={alertLimit} onChange={(event) => setAlertLimit(Number(event.target.value) as AlertLimit)}>{[25, 50, 100, 200].map((value) => <option key={value} value={value}>{value}</option>)}</select></label><ExclusionMultiSelect applications={applications} selectedApplicationKey="" selectedKeys={alertExcludedKeys} setSelectedKeys={setAlertExcludedKeys} search={alertExclusionSearch} setSearch={setAlertExclusionSearch} /><button className="button button-primary" type="button" onClick={() => setAlertSearchClick((value) => value + 1)}>Search</button></div></div><p className="similarity-rules-note">Score bands use the displayed score rounded to the nearest whole percent; 10.50% enters 11–20%.</p>{!alerts?.alerts.length ? <p className="message message-info">{analysisRun ? "No application pair satisfies the selected redundancy score range and filters." : emptyState}</p> : <RedundancyTable alerts={alerts.alerts} />}</section>}
      </div>
    </section>
  </div>;
}

function HeatmapView({ heatmap, applications, analysisRun, emptyState, search, setSearch, applicationSearch, setApplicationSearch, selectedApplicationKey, setSelectedApplicationKey, portfolio, setPortfolio, portfolios, limit, setLimit, scoreRange, setScoreRange, excludedApplicationKeys, setExcludedApplicationKeys, exclusionSearch, setExclusionSearch, scores, onSearch }: { heatmap: SimilarityHeatmapResponse | null; applications: HeatmapApplication[]; analysisRun: boolean; emptyState: string; search: string; setSearch: (value: string) => void; applicationSearch: string; setApplicationSearch: (value: string) => void; selectedApplicationKey: string; setSelectedApplicationKey: (value: string) => void; portfolio: string; setPortfolio: (value: string) => void; portfolios: string[]; limit: HeatmapLimit; setLimit: (value: HeatmapLimit) => void; scoreRange: ScoreRange; setScoreRange: (value: ScoreRange) => void; excludedApplicationKeys: string[]; setExcludedApplicationKeys: (keys: string[]) => void; exclusionSearch: string; setExclusionSearch: (value: string) => void; scores: Map<string, number>; onSearch: () => void }) {
  const anchors = heatmap?.anchor_applications ?? [];
  const candidates = heatmap?.candidate_applications ?? [];
  const [heatmapScrollTop, setHeatmapScrollTop] = useState(0);
  const rowHeight = 32;
  const firstVisibleRow = anchors.length > 80 ? Math.min(Math.max(0, anchors.length - 48), Math.max(0, Math.floor(Math.max(0, heatmapScrollTop - 92) / rowHeight) - 4)) : 0;
  const lastVisibleRow = anchors.length > 80 ? Math.min(anchors.length, firstVisibleRow + 48) : anchors.length;
  const visibleAnchors = anchors.slice(firstVisibleRow, lastVisibleRow);
  const rangeLabel = scoreRanges.find((range) => range.value === scoreRange)?.label ?? scoreRange;
  const filterCaption = heatmap ? `Showing ${candidates.length} of ${heatmap.candidate_count} matches in the ${rangeLabel} band${portfolio ? ` for ${portfolio}` : " across all portfolios"}${excludedApplicationKeys.length ? `, excluding ${excludedApplicationKeys.length} selected application${excludedApplicationKeys.length === 1 ? "" : "s"}` : ""}.` : "";
  return <section aria-labelledby="heatmap-title">
    <div className="similarity-view-heading"><div><h3 id="heatmap-title">Application similarity heatmap</h3><p>{selectedApplicationKey ? "Compare the selected application with its strongest filtered candidate matches." : "Compare applications across the filtered portfolio. Select an application to focus on its strongest matches."}</p></div></div>
    <div className="similarity-filter-grid">
      <SearchableApplication label="Focus application" applications={applications} query={applicationSearch} onQueryChange={(value, key) => { setApplicationSearch(value); setSelectedApplicationKey(key); }} />
      <label>Search applications<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Filter apps by name or code" /></label>
      <label>Candidate portfolio<select value={portfolio} onChange={(event) => setPortfolio(event.target.value)}><option value="">All Portfolios</option>{portfolios.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <label>Similarity score<select value={scoreRange} onChange={(event) => setScoreRange(event.target.value as ScoreRange)}>{scoreRanges.map((range) => <option key={range.value} value={range.value}>{range.label}</option>)}</select></label>
      <label>Result count<select value={limit} onChange={(event) => setLimit(event.target.value === "all" ? "all" : Number(event.target.value) as HeatmapLimit)}>{[25, 50, 100].map((value) => <option key={value} value={value}>{value}</option>)}<option value="all">All applications</option></select></label>
      <ExclusionMultiSelect applications={applications} selectedApplicationKey={selectedApplicationKey} selectedKeys={excludedApplicationKeys} setSelectedKeys={setExcludedApplicationKeys} search={exclusionSearch} setSearch={setExclusionSearch} /><button className="button button-primary" type="button" onClick={onSearch}>Search</button>
    </div>
    <p className="similarity-rules-note">{heatmap?.score_range_note || "Score bands use the displayed score rounded to the nearest whole percent; 10.50% enters 11–20%."} Labels: Unique &lt;20%, Low 20–49%, Medium 50–79%, High 80–100%.</p>
    {!analysisRun ? <p className="message message-info">{emptyState}</p> : !heatmap ? <p className="message message-info">Loading filtered application matches…</p> : !candidates.length ? <><p className="similarity-match-caption">{filterCaption}</p><p className="message message-info">No comparable candidate matches satisfy the active score band and filters.</p></> : <><p className="similarity-match-caption">{filterCaption}</p><div className="heatmap-scroll" onScroll={(event) => setHeatmapScrollTop(event.currentTarget.scrollTop)}><table className="similarity-heatmap"><thead><tr><th aria-label="Application" />{candidates.map((candidate) => <th key={`head-${identity(candidate)}`} title={appLabel(candidate.application_name, candidate.application_code)}>{candidate.application_name || candidate.application_code || "Missing"}<br /><small>{candidate.application_code || "Missing Code"}</small></th>)}</tr></thead><tbody>{firstVisibleRow > 0 && <tr aria-hidden="true"><td colSpan={candidates.length + 1} style={{ height: firstVisibleRow * rowHeight, padding: 0, border: 0 }} /></tr>}{visibleAnchors.map((anchor) => <tr key={`row-${identity(anchor)}`}><th title={appLabel(anchor.application_name, anchor.application_code)}><span>{anchor.application_name || "Missing Name"}</span><br /><span>{anchor.application_code || "Missing Code"}</span></th>{candidates.map((candidate) => { const value = scores.get(`${anchor.application_key}\u0001${candidate.application_key}`) ?? scores.get(`${candidate.application_key}\u0001${anchor.application_key}`); const tooltip = `Application Name: ${anchor.application_name || "Missing Name"}\nApplication Code: ${anchor.application_code || "Missing Code"}\nCompared Application: ${candidate.application_name || "Missing Name"} (${candidate.application_code || "Missing Code"})\nPortfolio: ${candidate.portfolio || "No Portfolio"}`; if (anchor.application_key === candidate.application_key) return <td key={`${identity(anchor)}-${identity(candidate)}`} title="Same application">—</td>; if (value === undefined) return <td key={`${identity(anchor)}-${identity(candidate)}`} title={`${tooltip}\nSimilarity Score: Outside selected range or not comparable`}>—</td>; return <td key={`${identity(anchor)}-${identity(candidate)}`} title={`${tooltip}\nSimilarity Score: ${value}%`} style={{ backgroundColor: `hsl(${Math.round(value * 1.2)} 58% ${96 - value * 0.43}%)` }}>{value}</td>; })}</tr>)}{lastVisibleRow < anchors.length && <tr aria-hidden="true"><td colSpan={candidates.length + 1} style={{ height: (anchors.length - lastVisibleRow) * rowHeight, padding: 0, border: 0 }} /></tr>}</tbody></table></div></>}
  </section>;
}
function ExclusionMultiSelect({ applications, selectedApplicationKey, selectedKeys, setSelectedKeys, search, setSearch }: { applications: HeatmapApplication[]; selectedApplicationKey: string; selectedKeys: string[]; setSelectedKeys: (keys: string[]) => void; search: string; setSearch: (value: string) => void }) {
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const filtered = applications.filter((app) => !normalizedSearch || app.application_name.toLocaleLowerCase().includes(normalizedSearch) || app.application_code.toLocaleLowerCase().includes(normalizedSearch));
  return <div className="similarity-exclusion-control"><span>Exclude applications</span><details key={selectedKeys.join("|")}><summary>{selectedKeys.length ? `${selectedKeys.length} excluded` : "None excluded"}</summary><div className="similarity-exclusion-popover"><label className="visually-hidden" htmlFor="similarity-exclusion-search">Search applications to exclude</label><input id="similarity-exclusion-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name or code" />{selectedKeys.length > 0 && <button type="button" className="similarity-exclusion-clear" onClick={() => setSelectedKeys([])}>Clear exclusions</button>}<div className="similarity-exclusion-options" role="group" aria-label="Applications to exclude">{filtered.length ? filtered.map((app) => { const key = identity(app); const isAnchor = key === selectedApplicationKey; return <label key={key}><input type="checkbox" checked={selectedKeys.includes(key)} disabled={isAnchor} onChange={(event) => setSelectedKeys(event.target.checked ? [...selectedKeys, key] : selectedKeys.filter((selectedKey) => selectedKey !== key))} /><span>{app.application_name || "Missing Name"}<small>{app.application_code || "Missing Code"}{isAnchor ? " · selected application" : ""}</small></span></label>; }) : <p>No applications match this search.</p>}</div></div></details></div>;
}
function SearchableApplication({ label, applications, query, onQueryChange }: { label: string; applications: HeatmapApplication[]; query: string; onQueryChange: (value: string, key: string) => void }) { const listId = useId(); const selected = applications.find((app) => appLabel(app.application_name, app.application_code).toLocaleLowerCase() === query.trim().toLocaleLowerCase()); return <div className="searchable-application-control"><label>{label}<input type="search" list={listId} value={query} placeholder="Type application name or code" onChange={(event) => { const value = event.target.value; const match = applications.find((app) => appLabel(app.application_name, app.application_code).toLocaleLowerCase() === value.trim().toLocaleLowerCase()); onQueryChange(value, match?.application_key ?? ""); }} /><datalist id={listId}>{applications.map((app) => <option key={identity(app)} value={appLabel(app.application_name, app.application_code)} />)}</datalist></label><label>Choose from list<select value={selected?.application_key ?? ""} onChange={(event) => { const app = applications.find((candidate) => candidate.application_key === event.target.value); onQueryChange(app ? appLabel(app.application_name, app.application_code) : "", app?.application_key ?? ""); }}><option value="">All applications</option>{applications.map((app) => <option key={identity(app)} value={app.application_key}>{appLabel(app.application_name, app.application_code)}</option>)}</select></label></div>; }
function RedundancyTable({ alerts }: { alerts: SimilarityAlertsResponse["alerts"] }) { const [direction, setDirection] = useState<"asc" | "desc">("desc"); const sorted = [...alerts].sort((a, b) => direction === "desc" ? b.similarity_score - a.similarity_score : a.similarity_score - b.similarity_score); return <div className="table-scroll similarity-results-table"><table className="simple-table"><thead><tr>{["Rank", "Application A", "Application A Code", "Application B", "Application B Code"].map((header) => <th key={header}>{header}</th>)}<th><button className="table-sort-button" type="button" onClick={() => setDirection((current) => current === "desc" ? "asc" : "desc")}>Similarity Score {direction === "desc" ? "↓" : "↑"}</button></th>{["Redundant Function / Capability", "Matching Evidence"].map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{sorted.map((alert, index) => <tr key={`${alert.application_code_a}-${alert.application_code_b}`}>{[String(index + 1), alert.application_name_a || "Missing Name", alert.application_code_a || "Missing Code", alert.application_name_b || "Missing Name", alert.application_code_b || "Missing Code", score(alert.similarity_score), alert.redundancy_reason || "Functional overlap detected from comparable evidence.", alert.evidence.join("; ") || "Comparable dimensions overlap."].map((cell, cellIndex) => <td key={cellIndex}>{cell}</td>)}</tr>)}</tbody></table></div>; }
function ResultTable({ headers, rows }: { headers: string[]; rows: string[][] }) { return <div className="table-scroll similarity-results-table"><table className="simple-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>; }
