"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useJob } from "@/context/job-context";
import { ApiError, getIntegrationNeighborhood, getObsoleteTechnology, getTechnologyClusters, getTechnologyIntegrations, getTechnologyOptions, getUploadStatus, runTechnologyAnalysis } from "@/lib/api";
import type { IntegrationNeighborhoodResponse, ObsoleteTechnologyResponse, TechnologyClustersResponse, TechnologyIntegration, TechnologyIntegrationsResponse, TechnologyOptionsResponse } from "@/types/api";

const tabs = ["Integration Map", "Technology Stack Analysis & Visualization", "Technology Risk Register"];

export default function TechnologyPage() {
  const { jobId, hydrated } = useJob();
  const tabId = useId();
  const [activeTab, setActiveTab] = useState(0);
  const [cmdbReady, setCmdbReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [running, setRunning] = useState(false);
  const [analyzed, setAnalyzed] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [options, setOptions] = useState<TechnologyOptionsResponse | null>(null);
  const [allIntegrations, setAllIntegrations] = useState<TechnologyIntegrationsResponse | null>(null);
  const [applicationCode, setApplicationCode] = useState("");
  const [integrationPortfolio, setIntegrationPortfolio] = useState("");
  const [integrationType, setIntegrationType] = useState("");
  const [neighborhood, setNeighborhood] = useState<IntegrationNeighborhoodResponse | null>(null);
  const [integrationSearchClick, setIntegrationSearchClick] = useState(0);
  const [clusterPortfolio, setClusterPortfolio] = useState("");
  const [clusters, setClusters] = useState<TechnologyClustersResponse | null>(null);
  const [technologyRisks, setTechnologyRisks] = useState<ObsoleteTechnologyResponse | null>(null);

  const loadOptions = useCallback(async (currentJob: string) => {
    setOptions(await getTechnologyOptions(currentJob));
    setAnalyzed(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    setChecking(true);
    setError(null);
    setMessage(null);
    setAnalyzed(false);
    setOptions(null);
    setApplicationCode("");
    if (!jobId) {
      setCmdbReady(false);
      setChecking(false);
      return;
    }
    void getUploadStatus(jobId).then(async (status) => {
      if (cancelled) return;
      setCmdbReady(status.cmdb_ready);
      if (status.cmdb_ready) {
        try {
          await loadOptions(jobId);
        } catch (caught) {
          if (caught instanceof ApiError && caught.status === 404) {
            await runTechnologyAnalysis(jobId);
            await loadOptions(jobId);
          } else throw caught;
        }
      }
    }).catch((caught) => {
      if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not check CMDB status.");
    }).finally(() => {
      if (!cancelled) setChecking(false);
    });
    return () => { cancelled = true; };
  }, [hydrated, jobId, loadOptions]);

  const run = async () => {
    if (!jobId || !cmdbReady || running) return;
    setRunning(true);
    setError(null);
    setMessage(null);
    try {
      await runTechnologyAnalysis(jobId);
      await loadOptions(jobId);
      setNeighborhood(null);
      setClusters(null);
      setTechnologyRisks(await getObsoleteTechnology(jobId, { portfolio: "", indicator: "", businessCriticality: "", search: "", page: 1, pageSize: "all" }));
      setMessage("Technology and integration analysis completed for the current CMDB.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Technology analysis failed.");
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => {
    if (!jobId || !analyzed) { setAllIntegrations(null); return; }
    void getTechnologyIntegrations(jobId, 1000).then(setAllIntegrations).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load portfolio integrations."));
  }, [analyzed, jobId]);

  useEffect(() => {
    if (!jobId || !analyzed || !applicationCode) {
      setNeighborhood(null);
      return;
    }
    void getIntegrationNeighborhood(jobId, {
      applicationCode,
      portfolio: integrationPortfolio,
      integrationType,
      confidence: "",
      page: 1,
      pageSize: "all",
    }).then(setNeighborhood).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load integration relationships."));
  }, [analyzed, applicationCode, integrationPortfolio, integrationType, jobId, integrationSearchClick]);

  useEffect(() => {
    if (!jobId || !analyzed) return;
    void getTechnologyClusters(jobId, clusterPortfolio).then(setClusters).catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load technology stack analysis."));
  }, [analyzed, clusterPortfolio, jobId]);

  useEffect(() => {
    if (!jobId || !analyzed) { setTechnologyRisks(null); return; }
    void getObsoleteTechnology(jobId, { portfolio: "", indicator: "", businessCriticality: "", search: "", page: 1, pageSize: "all" })
      .then(setTechnologyRisks)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "Could not load the technology risk register."));
  }, [analyzed, jobId]);

  const availableApplications = useMemo(() => deduplicateApplications(options?.applications ?? []), [options]);

  return <div className="page-stack technology-page">
    <section className="page-heading"><div><h2>3. Technology and Integration Visualization</h2><p>CMDB-wide integration mapping and aggregate technology stack analysis.</p></div></section>
    {checking && <p className="muted">Checking CMDB status…</p>}
    {!checking && !cmdbReady && <p className="message message-info">Load a CMDB in this analysis session before running technology analysis.</p>}
    {!checking && cmdbReady && <p className="message message-success">Current-session CMDB loaded</p>}
    <section className="technology-run panel"><div><h3>Technology analysis</h3><p>One deterministic scan prepares every CMDB application and the full evidence-backed integration graph.</p></div><button className="button button-primary" type="button" disabled={!cmdbReady || running} onClick={() => void run()}>{running ? "Running…" : "Run technology analysis"}</button></section>
    {message && <p className="message message-success" role="status">{message}</p>}
    {error && <p className="message message-error" role="alert">{error}</p>}
    <section className="similarity-tabs" aria-label="Technology views">
      <div className="similarity-tab-list" role="tablist" aria-label="Technology views">{tabs.map((tab, index) => <button key={tab} id={`${tabId}-tab-${index}`} className="similarity-tab" type="button" role="tab" aria-selected={activeTab === index} aria-controls={`${tabId}-panel-${index}`} tabIndex={activeTab === index ? 0 : -1} onClick={() => setActiveTab(index)}>{tab}</button>)}</div>
      <div className="similarity-tab-panel panel" id={`${tabId}-panel-${activeTab}`} role="tabpanel" aria-labelledby={`${tabId}-tab-${activeTab}`}>
        {!analyzed ? <p className="message message-info">Preparing this module’s results…</p> : activeTab === 0 ? <IntegrationView options={options!} applications={availableApplications} allIntegrations={allIntegrations} result={neighborhood} applicationCode={applicationCode} setApplicationCode={setApplicationCode} portfolio={integrationPortfolio} setPortfolio={setIntegrationPortfolio} integrationType={integrationType} setIntegrationType={setIntegrationType} onSearch={() => setIntegrationSearchClick((value) => value + 1)} /> : activeTab === 1 ? <TechnologyStackView options={options!} result={clusters} portfolio={clusterPortfolio} setPortfolio={setClusterPortfolio} /> : <TechnologyRiskRegister result={technologyRisks} />}
      </div>
    </section>
  </div>;
}

function TechnologyRiskRegister({ result }: { result: ObsoleteTechnologyResponse | null }) {
  if (!result) return <p className="message message-info">Loading technology risk evidence…</p>;
  const rows = result.indicators.map((indicator) => [
    `${indicator.application_name} (${indicator.application_code || "Application Code unavailable"})`,
    indicator.portfolio || "Unassigned",
    indicator.severity,
    indicator.indicator || "Technology lifecycle concern",
    `${indicator.field}: ${indicator.value}`,
    indicator.reason,
  ]);
  return <section>
    <Heading title="Technology Risk Register" text="Technology concerns identified from available technology age, stack, functionality, framework, version, and lifecycle evidence in the current CMDB." />
    <p className="technology-scope-summary">{result.obsolete_indicator_count.toLocaleString()} technology concerns with available evidence.</p>
    {result.warnings.map((warning) => <p key={warning} className="message message-info">{warning}</p>)}
    {rows.length ? <Table headers={["Application", "Portfolio", "Severity", "Technology Concern", "Evidence", "Reason"]} rows={rows} /> : <p className="message message-info">No technology risks were identified by the available lifecycle and technology evidence.</p>}
  </section>;
}

function IntegrationView({ options, applications, allIntegrations, result, applicationCode, setApplicationCode, portfolio, setPortfolio, integrationType, setIntegrationType, onSearch }: { options: TechnologyOptionsResponse; applications: TechnologyOptionsResponse["applications"]; allIntegrations: TechnologyIntegrationsResponse | null; result: IntegrationNeighborhoodResponse | null; applicationCode: string; setApplicationCode: (value: string) => void; portfolio: string; setPortfolio: (value: string) => void; integrationType: string; setIntegrationType: (value: string) => void; onSearch: () => void }) {
  const applicationPortfolio = new Map(applications.map((app) => [(app.application_code || "").toLocaleLowerCase(), (app.portfolio || "").toLocaleLowerCase()]));
  const portfolioFolded = portfolio.trim().toLocaleLowerCase();
  const filteredIntegrations = (allIntegrations?.integrations ?? []).filter((item) => {
    if (integrationType && item.integration_type !== integrationType) return false;
    if (!portfolioFolded) return true;
    const sourcePortfolio = applicationPortfolio.get((item.source_application_code || "").toLocaleLowerCase());
    const targetPortfolio = applicationPortfolio.get((item.target_application_code || "").toLocaleLowerCase());
    return sourcePortfolio === portfolioFolded || targetPortfolio === portfolioFolded;
  });
  return <section>
    <Heading title="Integration Map" text="The selected application is centered between inbound and outbound relationships found across the full CMDB. Relationships without established direction are shown separately." />
    <div className="technology-filter-grid technology-map-filters">
      <SearchableTechnologyApplication applications={applications} value={applicationCode} onChange={setApplicationCode} />
      <FilterSelect label="Portfolio" value={portfolio} onChange={setPortfolio} options={pairs(options.portfolios)} all="All Portfolios" />
      <FilterSelect label="Integration Type" value={integrationType} onChange={setIntegrationType} options={pairs(options.integration_types)} all="All Types" /><button className="button button-primary" type="button" onClick={onSearch}>Search</button>
    </div>
    {!applicationCode ? <><div className="technology-detail-heading"><h4>Portfolio integration results</h4><span>{filteredIntegrations.length} of {allIntegrations?.total_integration_count ?? 0} relationships</span></div>{filteredIntegrations.length ? <Table headers={["Source Application", "Target Application", "Integration Type", "Confidence", "Evidence Field", "Evidence"]} rows={filteredIntegrations.map((item) => [`${item.source_application_name} (${item.source_application_code || "Not Available"})`, item.target_application_name ? `${item.target_application_name} (${item.target_application_code || "Not Available"})` : "Unidentified", item.integration_type, item.confidence, item.evidence_field, item.evidence_value])} /> : <p className="message message-info">No integration relationships match this portfolio and type. The CMDB may not contain explicit integration evidence.</p>}</> : result && !result.total_integration_count ? <p className="message message-info">No detected integrations match the selected application and filters.</p> : result && <><IntegrationFlow result={result} /><div className="technology-detail-heading"><h4>Integration evidence</h4><span>{result.total_integration_count} observations</span></div><Table headers={["Source Application", "Target Application", "Direction", "Integration Type", "Evidence Field", "Evidence"]} rows={result.integrations.map((item) => [`${item.source_application_name} (${item.source_application_code || "Not Available"})`, item.target_application_name ? `${item.target_application_name} (${item.target_application_code || "Not Available"})` : "Unidentified", directionLabel(item.direction), item.integration_type, item.evidence_field, item.evidence_value])} /></>}
  </section>;
}

function IntegrationFlow({ result }: { result: IntegrationNeighborhoodResponse }) {
  const groups = useMemo(() => {
    const anchor = result.selected_application.application_code.toLowerCase();
    const unique = (items: TechnologyIntegration[]) => Array.from(new Map(items.map((item) => {
      const sourceIsAnchor = (item.source_application_code || "").toLowerCase() === anchor;
      const name = sourceIsAnchor ? item.target_application_name : item.source_application_name;
      const code = sourceIsAnchor ? item.target_application_code : item.source_application_code;
      return [`${code || name || "unidentified"}-${item.integration_type}`, { name: name || "Unidentified application", code, type: item.integration_type }];
    })).values());
    return {
      upstream: unique(result.integrations.filter((item) => item.direction === "incoming")),
      downstream: unique(result.integrations.filter((item) => item.direction === "outgoing")),
      related: unique(result.integrations.filter((item) => item.direction === "unknown")),
    };
  }, [result]);
  const nodes = (items: Array<{ name: string; code: string | null; type: string }>) => <div className="integration-flow-nodes">{items.map((item, index) => <div className="integration-flow-node" key={`${item.code || item.name}-${item.type}-${index}`}><strong>{item.name}</strong><span>{item.code || "Not Available"}</span><small>{item.type || "Not Available"}</small></div>)}</div>;
  return <div className="integration-flow" aria-label={`Integration flow for ${result.selected_application.application_name}`}>
    <section><h4>Upstream applications</h4>{groups.upstream.length ? nodes(groups.upstream) : <p className="muted">None detected</p>}</section>
    <div className="integration-flow-arrow" aria-hidden="true">↓</div>
    <div className="integration-flow-anchor"><strong>{result.selected_application.application_name}</strong><span>{result.selected_application.application_code}</span></div>
    <div className="integration-flow-arrow" aria-hidden="true">↓</div>
    <section><h4>Downstream applications</h4>{groups.downstream.length ? nodes(groups.downstream) : <p className="muted">None detected</p>}</section>
    <section className="integration-flow-related"><h4>Related / technical integrations — direction not established</h4>{groups.related.length ? nodes(groups.related) : <p className="muted">None detected</p>}</section>
  </div>;
}

function TechnologyStackView({ options, result, portfolio, setPortfolio }: { options: TechnologyOptionsResponse; result: TechnologyClustersResponse | null; portfolio: string; setPortfolio: (value: string) => void }) {
  const [stack, setStack] = useState("");
  const [applicationCount, setApplicationCount] = useState("");
  const [risk, setRisk] = useState("");
  const [status, setStatus] = useState("");
  const statusOptions = useMemo(
    () => [...new Set((result?.clusters ?? []).map((cluster) => cluster.lifecycle_status || "Not Available"))].sort((left, right) => left.localeCompare(right)),
    [result],
  );
  const filteredClusters = useMemo(() => (result?.clusters ?? []).filter((cluster) => {
    if (stack && cluster.cluster_key !== stack) return false;
    if (applicationCount === "1" && cluster.application_count !== 1) return false;
    if (applicationCount === "2-5" && (cluster.application_count < 2 || cluster.application_count > 5)) return false;
    if (applicationCount === "6-10" && (cluster.application_count < 6 || cluster.application_count > 10)) return false;
    if (applicationCount === "11+" && cluster.application_count < 11) return false;
    if (risk === "risky" && cluster.risky_application_count === 0) return false;
    if (risk === "clear" && cluster.risky_application_count > 0) return false;
    if (status && (cluster.lifecycle_status || "Not Available") !== status) return false;
    return true;
  }), [applicationCount, result, risk, stack, status]);
  const displayedApplications = useMemo(() => new Set(filteredClusters.flatMap((cluster) => cluster.applications.map((application) => application.application_code || application.application_name))).size, [filteredClusters]);
  return <section>
    <Heading title="Technology Stack Analysis & Visualization" text="Technology clusters use CMDB technology and lifecycle evidence, analyzed across the current application inventory." />
    <div className="technology-filter-grid technology-stack-filters">
      <FilterSelect label="Portfolio" value={portfolio} onChange={(value) => { setPortfolio(value); setStack(""); }} options={pairs(options.portfolios)} all="All Portfolios" />
      <FilterSelect label="Technology Stack" value={stack} onChange={setStack} options={uniqueOptions((result?.clusters ?? []).map((cluster) => [cluster.cluster_key, `${technologyTypeLabel(cluster.technology_type)} — ${cluster.label}`]))} all="All Technology Stacks" />
      <FilterSelect label="Application Count" value={applicationCount} onChange={setApplicationCount} options={[["1", "1 application"], ["2-5", "2–5 applications"], ["6-10", "6–10 applications"], ["11+", "11+ applications"]]} all="All Counts" />
      <FilterSelect label="Potentially Risky Applications" value={risk} onChange={setRisk} options={[["risky", "Has potential concerns"], ["clear", "No detected concerns"]]} all="All Risk Results" />
      <FilterSelect label="Technology Status Concerns" value={status} onChange={setStatus} options={pairs(statusOptions)} all="All Statuses" />
    </div>
    {result && <p className="technology-scope-summary">Portfolio scope: <strong>{result.portfolio || "All Portfolios"}</strong> — <strong>{result.scope_application_count.toLocaleString()}</strong> applications. Current filters display <strong>{filteredClusters.length.toLocaleString()}</strong> clusters across <strong>{displayedApplications.toLocaleString()}</strong> contributing applications.</p>}
    {result && !filteredClusters.length ? <p className="message message-info">No technology clusters match the selected filters.</p> : result && <div className="technology-cluster-list">{filteredClusters.map((cluster, index) => <details className="technology-cluster-card" key={cluster.cluster_key}><summary>Cluster {index + 1} · {cluster.application_count} applications · {cluster.lifecycle_status || "Status not available"}</summary><Table headers={["Application Count", "Contributing Applications", "Why Clustered", "Lifecycle / Technology Status", "Evidence"]} rows={[[String(cluster.application_count), cluster.applications.map((application) => `${application.application_name} (${application.application_code || "Application Code unavailable"})`).join("; "), cluster.cluster_reason, cluster.lifecycle_status || "Not Available", cluster.concern_evidence.length ? cluster.concern_evidence.map((evidence) => `${evidence.application_name} — ${evidence.source_field}: ${evidence.evidence_value}. ${evidence.reason}`).join(" ") : "No configured technology concern detected."]]}/></details>)}</div>}
  </section>;
}

function Heading({ title, text }: { title: string; text: string }) { return <div className="technology-section-heading"><h3>{title}</h3><p>{text}</p></div>; }
function FilterSelect({ label, value, onChange, options, all }: { label: string; value: string; onChange: (value: string) => void; options: string[][]; all?: string }) { const stableOptions = uniqueOptions(options); return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}>{all && <option value="">{all}</option>}{stableOptions.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
function SearchableTechnologyApplication({ applications, value, onChange }: { applications: TechnologyOptionsResponse["applications"]; value: string; onChange: (value: string) => void }) { const [query, setQuery] = useState(""); const listId = useId(); const selected = applications.find((application) => application.application_code === value); useEffect(() => { setQuery(selected ? technologyApplicationLabel(selected) : ""); }, [value]); return <div className="searchable-application-control"><label>Application<input type="search" list={listId} value={query} placeholder="Type application name or code" onChange={(event) => { const next = event.target.value; const match = applications.find((application) => technologyApplicationLabel(application).toLocaleLowerCase() === next.trim().toLocaleLowerCase()); setQuery(next); onChange(match?.application_code ?? ""); }} /><datalist id={listId}>{applications.map((application) => <option key={technologyApplicationIdentity(application)} value={technologyApplicationLabel(application)} />)}</datalist></label><label>Choose from list<select value={value} onChange={(event) => { const application = applications.find((candidate) => candidate.application_code === event.target.value); onChange(event.target.value); setQuery(application ? technologyApplicationLabel(application) : ""); }}><option value="">All applications</option>{applications.map((application) => <option key={technologyApplicationIdentity(application)} value={application.application_code || ""}>{technologyApplicationLabel(application)}</option>)}</select></label></div>; }
function Table({ headers, rows }: { headers: string[]; rows: string[][] }) { return <div className="table-scroll technology-results-table"><table className="simple-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>)}</tbody></table></div>; }
function pairs(values: string[]) { return values.map((item) => [item, item]); }
function uniqueOptions(options: string[][]) { const seen = new Set<string>(); return options.filter(([key]) => { if (seen.has(key)) return false; seen.add(key); return true; }); }
function technologyApplicationIdentity(app: TechnologyOptionsResponse["applications"][number]) { return `${(app.application_code || "").toLocaleLowerCase()}\u0000${app.application_name.toLocaleLowerCase()}`; }
function technologyApplicationLabel(app: TechnologyOptionsResponse["applications"][number]) { return `${app.application_name} (${app.application_code || "Application Code unavailable"})`; }
function deduplicateApplications(applications: TechnologyOptionsResponse["applications"]) { const seen = new Set<string>(); return applications.filter((app) => { const identity = technologyApplicationIdentity(app); if (seen.has(identity)) return false; seen.add(identity); return true; }).sort((left, right) => technologyApplicationLabel(left).localeCompare(technologyApplicationLabel(right))); }
function title(value: string) { return value ? value.charAt(0).toUpperCase() + value.slice(1) : value; }
function directionLabel(value: string) { return value === "unknown" ? "Unknown / not established" : title(value); }
function technologyTypeLabel(value: string) { return value.split("_").map(title).join(" "); }
