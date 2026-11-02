"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";

import { useJob } from "@/context/job-context";
import { ApiError, downloadOutputWorkbook, getApplicationOutputMapping, getJson, getOutputMvpResults, getUploadStatus, runOutputFamilyAnalysis } from "@/lib/api";
import type { ApplicationOutputMappingRow, OutputFamiliesConfigResponse, OutputFamilyMatrixRow, OutputMvpResults, UploadStatusResponse } from "@/types/api";

const show = (value: string | number) => String(value || "Not Available");

interface OutputViewData {
  results: OutputMvpResults;
  applications: ApplicationOutputMappingRow[];
  taxonomy: OutputFamiliesConfigResponse;
}

export default function OutputFamiliesPage() {
  const { jobId, hydrated } = useJob();
  const [status, setStatus] = useState<UploadStatusResponse | null>(null);
  const [viewData, setViewData] = useState<OutputViewData | null>(null);
  const [checking, setChecking] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);

  const loadResults = useCallback(async (currentJobId: string) => {
    const encodedJobId = encodeURIComponent(currentJobId);
    const [results, mapping, taxonomy] = await Promise.all([
      getOutputMvpResults(currentJobId),
      getApplicationOutputMapping(currentJobId, { portfolio: "", outputFamily: "", confidence: "", classificationStatus: "", search: "", displaySize: "all" }),
      getJson<OutputFamiliesConfigResponse>(`/api/jobs/${encodedJobId}/config/output-families`),
    ]);
    return { results, applications: mapping.applications, taxonomy };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    let cancelled = false;
    setChecking(true); setStatus(null); setViewData(null); setMessage(null); setError(null);
    if (!jobId) { setChecking(false); return; }
    void getUploadStatus(jobId).then(async (currentStatus) => {
      if (cancelled) return;
      setStatus(currentStatus);
      if (!currentStatus.cmdb_ready || !currentStatus.output_family_config_ready) return;
      try {
        const loaded = await loadResults(jobId);
        if (!cancelled) setViewData(loaded);
      }
      catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) {
          await runOutputFamilyAnalysis(jobId);
          const generated = await loadResults(jobId);
          if (!cancelled) { setViewData(generated); setMessage("Output results were generated for this CMDB and configuration."); }
        } else throw caught;
      }
    }).catch((caught) => { if (!cancelled) setError(caught instanceof Error ? caught.message : "Could not load Application Outputs Analysis."); })
      .finally(() => { if (!cancelled) setChecking(false); });
    return () => { cancelled = true; };
  }, [hydrated, jobId, loadResults]);

  const run = async () => {
    if (!jobId || !status?.cmdb_ready || !status.output_family_config_ready || running) return;
    setRunning(true); setError(null); setMessage("Running output analysis...");
    try {
      await runOutputFamilyAnalysis(jobId);
      setViewData(await loadResults(jobId));
      setMessage("Output analysis completed.");
    } catch (caught) {
      setMessage(null); setError(caught instanceof Error ? caught.message : "Output analysis failed.");
    } finally { setRunning(false); }
  };

  const missingConfiguration = hydrated && Boolean(jobId) && status?.cmdb_ready && !status.output_family_config_ready;
  const noCmdb = hydrated && (!jobId || (status && !status.cmdb_ready));

  return <div className="page-stack output-family-page">
    <section className="page-heading"><div><h2>4. Application Outputs Analysis</h2><p>Classification uses the uploaded output-family list and assigns Others when no configured family clearly matches.</p></div></section>
    {checking && <p className="muted">Checking current-session inputs…</p>}
    {!checking && noCmdb && <p className="message message-info">A current-session CMDB is required for Application Outputs Analysis.</p>}
    {!checking && missingConfiguration && <p className="message message-info">Output Family configuration is required for Application Outputs Analysis.</p>}
    <section className="output-family-run panel"><div><h3>Application outputs analysis</h3></div><div className="output-family-actions"><button className="button button-secondary" type="button" disabled={!viewData || downloading} onClick={() => { if (!jobId) return; setDownloading(true); void downloadOutputWorkbook(jobId).catch((caught) => setError(caught instanceof Error ? caught.message : "Workbook download failed.")).finally(() => setDownloading(false)); }}>{downloading ? "Preparing Excel…" : "Download Excel"}</button><button className="button button-primary" type="button" disabled={!status?.cmdb_ready || !status.output_family_config_ready || running} onClick={() => void run()}>{running ? "Running output analysis..." : "Run output analysis"}</button></div></section>
    {message && <p className="message message-success" role="status">{message}</p>}
    {error && <p className="message message-error" role="alert">{error}</p>}
    {!viewData && !checking && <p className="message message-info">Preparing output-family results…</p>}
    {viewData && <section className="panel output-matrix-panel" aria-labelledby="output-matrix-title">
      <div className="output-matrix-heading">
        <h3 id="output-matrix-title">App vs Output Family Matrix</h3>
        <p>Configured family keywords and evidence-derived clusters are shown across applications. Yes marks a supported assignment.</p>
      </div>
      <Matrix results={viewData.results} applications={viewData.applications} taxonomy={viewData.taxonomy} />
    </section>}
  </div>;
}

function familyColors(family: string, hue: number, matched: boolean) {
  void hue;
  if (family.trim().toLowerCase().startsWith("others /")) {
    return matched
      ? { backgroundColor: "#1d4ed8", color: "#fff" }
      : { backgroundColor: "#eff6ff", color: "#334155" };
  }
  return matched
    ? { backgroundColor: "#2563eb", color: "#fff" }
    : { backgroundColor: "#dbeafe", color: "#334155" };
}

type MatrixRenderRow = OutputFamilyMatrixRow & { renderKey: string };
type FilterableMatrixRow = MatrixRenderRow & {
  applicationCode: string | null;
  portfolio: string | null;
  matchedEvidence: string[];
  fieldsUsed: string[];
  rationale: string;
  assignments: ApplicationOutputMappingRow["assignments"];
  confidence: ApplicationOutputMappingRow["confidence"];
};
type FamilyMemberOption = {
  value: string;
  family: string;
  label: string;
  evidence: string;
};

const normalizeIdentityValue = (value: string) => value.normalize("NFKC").trim().toLocaleLowerCase();
const matrixIdentity = (applicationKey: string, applicationName: string) => `${normalizeIdentityValue(applicationKey)}\u0000${normalizeIdentityValue(applicationName)}`;

function mergeMatrixRows(rows: OutputFamilyMatrixRow[], families: string[]): OutputFamilyMatrixRow {
  const first = rows[0];
  return {
    application_key: first.application_key,
    application_name: first.application_name,
    values: Object.fromEntries(families.map((family) => [family, rows.some((row) => row.values[family] === "Yes") ? "Yes" : "No"])),
  };
}

function matrixRows(results: OutputMvpResults): MatrixRenderRow[] {
  const { output_families: families, rows } = results.family_matrix;
  // Output details are emitted once per CMDB row, so they distinguish source duplicates
  // from surplus matrix records produced by one application matching several families.
  const sourceCounts = new Map<string, number>();
  for (const detail of results.output_details) {
    const identity = matrixIdentity(detail.application_key, detail.application_name);
    sourceCounts.set(identity, (sourceCounts.get(identity) ?? 0) + 1);
  }

  const grouped = new Map<string, OutputFamilyMatrixRow[]>();
  for (const row of rows) {
    const identity = matrixIdentity(row.application_key, row.application_name);
    grouped.set(identity, [...(grouped.get(identity) ?? []), row]);
  }

  const aggregated: OutputFamilyMatrixRow[] = [];
  for (const [identity, matchingRows] of grouped) {
    const sourceRowCount = Math.max(1, sourceCounts.get(identity) ?? 1);
    if (matchingRows.length <= sourceRowCount) {
      aggregated.push(...matchingRows);
      continue;
    }

    const merged = mergeMatrixRows(matchingRows, families);
    for (let sourceOccurrence = 0; sourceOccurrence < sourceRowCount; sourceOccurrence += 1) {
      aggregated.push({ ...merged, values: { ...merged.values } });
    }
  }

  const codeCounts = new Map<string, number>();
  for (const row of aggregated) codeCounts.set(row.application_key, (codeCounts.get(row.application_key) ?? 0) + 1);
  const compositeFor = (row: OutputFamilyMatrixRow) => {
    const matchedFamilies = families.filter((family) => row.values[family] === "Yes").join("\u0000");
    return `${matrixIdentity(row.application_key, row.application_name)}\u0000${matchedFamilies}`;
  };
  const compositeCounts = new Map<string, number>();
  for (const row of aggregated) {
    const composite = compositeFor(row);
    compositeCounts.set(composite, (compositeCounts.get(composite) ?? 0) + 1);
  }
  const compositeOccurrences = new Map<string, number>();
  return aggregated.map((row) => {
    if (codeCounts.get(row.application_key) === 1) return { ...row, renderKey: row.application_key };
    // Preserve genuine duplicate CMDB rows without changing their underlying application identity.
    const composite = compositeFor(row);
    if (compositeCounts.get(composite) === 1) return { ...row, renderKey: composite };
    const occurrence = (compositeOccurrences.get(composite) ?? 0) + 1;
    compositeOccurrences.set(composite, occurrence);
    return { ...row, renderKey: `${composite}\u0000source-occurrence-${occurrence}` };
  });
}

const normalizeFilterValue = (value: string | null | undefined) => String(value ?? "").trim().toLocaleLowerCase();

function attachApplicationData(rows: MatrixRenderRow[], applications: ApplicationOutputMappingRow[]): FilterableMatrixRow[] {
  const exactBuckets = new Map<string, ApplicationOutputMappingRow[]>();
  const missingCodeBuckets = new Map<string, ApplicationOutputMappingRow[]>();
  for (const application of applications) {
    const bucket = application.application_code
      ? exactBuckets
      : missingCodeBuckets;
    const identity = application.application_code
      ? matrixIdentity(application.application_code, application.application_name)
      : normalizeIdentityValue(application.application_name);
    bucket.set(identity, [...(bucket.get(identity) ?? []), application]);
  }

  return rows.map((row) => {
    const exact = exactBuckets.get(matrixIdentity(row.application_key, row.application_name));
    const fallback = missingCodeBuckets.get(normalizeIdentityValue(row.application_name));
    const application = exact?.[0] ?? fallback?.shift();
    const matchedEvidence = exact
      ? [...new Set(exact.flatMap((item) => item.matched_evidence))]
      : application?.matched_evidence ?? [];
    return {
      ...row,
      applicationCode: application?.application_code ?? null,
      portfolio: application?.portfolio ?? null,
      matchedEvidence,
      fieldsUsed: exact
        ? [...new Set(exact.flatMap((item) => item.fields_used))]
        : application?.fields_used ?? [],
      rationale: application?.classification_rationale ?? "",
      assignments: application?.assignments ?? [],
      confidence: application?.confidence ?? "Low",
    };
  });
}

function familyMemberOptions(taxonomy: OutputFamiliesConfigResponse, applications: ApplicationOutputMappingRow[]): FamilyMemberOption[] {
  const options: FamilyMemberOption[] = [];
  const seen = new Set<string>();
  for (const family of taxonomy.families) {
    for (const member of family.members) {
      const memberValue = member.member_value?.trim();
      const applicationName = member.application_name?.trim();
      const applicationCode = member.application_code?.trim();
      const evidence = memberValue || applicationName || applicationCode;
      if (!evidence) continue;
      const label = applicationName && applicationCode ? `${applicationName} (${applicationCode})` : evidence;
      const identity = `${normalizeFilterValue(family.name)}\u0000${normalizeFilterValue(evidence)}`;
      if (seen.has(identity)) continue;
      seen.add(identity);
      options.push({ value: identity, family: family.name, label, evidence });
    }
  }
  for (const application of applications) {
    for (const assignment of application.assignments) {
      for (const evidence of assignment.evidence ?? []) {
        const family = assignment.output_cluster || assignment.output_family;
        const identity = `${normalizeFilterValue(family)}\u0000${normalizeFilterValue(evidence)}`;
        if (!evidence || seen.has(identity)) continue;
        seen.add(identity);
        options.push({ value: identity, family, label: evidence, evidence });
      }
    }
  }
  return options.sort((left, right) => left.family.localeCompare(right.family) || left.label.localeCompare(right.label));
}

function applicationIdentity(row: FilterableMatrixRow) {
  return normalizeIdentityValue(row.applicationCode || row.application_key);
}

function applicationLabel(row: FilterableMatrixRow) {
  return row.applicationCode ? `${row.application_name} (${row.applicationCode})` : row.application_name;
}

function Matrix({ results, applications, taxonomy }: { results: OutputMvpResults; applications: ApplicationOutputMappingRow[]; taxonomy: OutputFamiliesConfigResponse }) {
  const [outputFamily, setOutputFamily] = useState("");
  const [familyMember, setFamilyMember] = useState("");
  const [portfolio, setPortfolio] = useState("");
  const [application, setApplication] = useState("");
  const families = results.family_matrix.output_families;
  const allRows = useMemo(() => attachApplicationData(matrixRows(results), applications), [applications, results]);
  const allMemberOptions = useMemo(() => familyMemberOptions(taxonomy, applications), [applications, taxonomy]);
  const selectedMember = useMemo(() => allMemberOptions.find((member) => member.value === familyMember), [allMemberOptions, familyMember]);
  const rowMatches = (row: FilterableMatrixRow, ignored: "family" | "member" | "portfolio" | "application" | null = null) => {
    if (ignored !== "family" && outputFamily && row.values[outputFamily] !== "Yes") return false;
    if (ignored !== "member" && selectedMember) {
      if (row.values[selectedMember.family] !== "Yes") return false;
      const evidence = normalizeFilterValue(selectedMember.evidence);
      const assignmentEvidence = row.assignments.filter((assignment) => assignment.output_cluster === selectedMember.family || assignment.output_family === selectedMember.family).flatMap((assignment) => assignment.evidence ?? []);
      if (![...row.matchedEvidence, ...assignmentEvidence].some((value) => normalizeFilterValue(value) === evidence)) return false;
    }
    if (ignored !== "portfolio" && portfolio && row.portfolio !== portfolio) return false;
    if (ignored !== "application" && application && applicationIdentity(row) !== application) return false;
    return true;
  };
  const familyOptions = useMemo(() => families.filter((family) => allRows.some((row) => row.values[family] === "Yes" && rowMatches(row, "family"))), [allRows, application, families, portfolio, selectedMember]);
  const memberOptions = useMemo(() => allMemberOptions.filter((member) => {
    if (outputFamily && member.family !== outputFamily) return false;
    return allRows.some((row) => {
      if (!rowMatches(row, "member") || row.values[member.family] !== "Yes") return false;
      const evidence = normalizeFilterValue(member.evidence);
      return [...row.matchedEvidence, ...row.assignments.filter((assignment) => assignment.output_cluster === member.family || assignment.output_family === member.family).flatMap((assignment) => assignment.evidence ?? [])].some((value) => normalizeFilterValue(value) === evidence);
    });
  }), [allMemberOptions, allRows, application, outputFamily, portfolio]);
  const portfolios = useMemo(
    () => [...new Set(allRows.filter((row) => rowMatches(row, "portfolio")).map((row) => row.portfolio).filter((value): value is string => Boolean(value)))].sort((left, right) => left.localeCompare(right)),
    [allRows, application, outputFamily, selectedMember],
  );
  const applicationOptions = useMemo(() => {
    const seen = new Set<string>();
    return allRows
      .filter((row) => rowMatches(row, "application"))
      .filter((row) => {
        const identity = applicationIdentity(row);
        if (seen.has(identity)) return false;
        seen.add(identity);
        return true;
      })
      .sort((left, right) => applicationLabel(left).localeCompare(applicationLabel(right)));
  }, [allRows, outputFamily, portfolio, selectedMember]);
  const rows = useMemo(() => allRows.filter((row) => rowMatches(row)), [allRows, application, outputFamily, portfolio, selectedMember]);
  const configuredFamilies = results.family_matrix.configured_families ?? families.filter((family) => !family.startsWith("Others /"));
  const otherClusters = results.family_matrix.other_clusters ?? families.filter((family) => family.startsWith("Others /"));
  const familyHues = useMemo(() => new Map(configuredFamilies.map((family, index) => [family, (index * 137.508) % 360])), [configuredFamilies]);
  return <div className="output-matrix-stack">
    <div className="output-family-filter-grid matrix-filters" aria-label="Output matrix filters">
      <label>Output Family / Cluster<select value={outputFamily} onChange={(event) => { setOutputFamily(event.target.value); if (selectedMember && selectedMember.family !== event.target.value) setFamilyMember(""); }}><option value="">All</option>{familyOptions.map((family) => <option key={family} value={family}>{family}</option>)}</select></label>
      <label>Family Member<select value={familyMember} onChange={(event) => setFamilyMember(event.target.value)}><option value="">All</option>{memberOptions.map((member) => <option key={member.value} value={member.value}>{outputFamily ? member.label : `${member.label} — ${member.family}`}</option>)}</select></label>
      <label>Portfolio<select value={portfolio} onChange={(event) => setPortfolio(event.target.value)}><option value="">All</option>{portfolios.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
      <SearchableOutputApplication rows={applicationOptions} value={application} onChange={setApplication} />
    </div>
    <section className="output-cluster-map" aria-label="Output family and evidence cluster map"><h4>Output family cluster map</h4><div className="output-cluster-list">{families.filter((family) => rows.some((row) => row.values[family] === "Yes")).map((family) => { const members = rows.filter((row) => row.values[family] === "Yes"); const evidenceCluster = family.startsWith("Others /"); return <details className="output-cluster-card" key={family}><summary>{family} · {members.length} applications</summary><p>{evidenceCluster ? "Evidence-derived keyword cluster from CMDB output fields." : "Configured output-family keyword match."}</p><ul>{members.map((row) => <li key={row.renderKey}>{applicationLabel(row)}</li>)}</ul></details>; })}</div></section>
    <Table headers={["Application", "Confidence", "Matching Evidence", ...families]} rows={rows.map((row) => ({ key: row.renderKey, cells: [applicationLabel(row), row.confidence, row.matchedEvidence.join(", ") || "Insufficient evidence", ...families.map((family) => row.values[family])] }))} empty="No applications match the selected filters." />
    {rows.length > 0 && <div className="output-heatmap" style={{ minHeight: Math.max(400, rows.length * 42 + 90) }} aria-label="App vs Output Family heatmap" data-aspect="auto" data-zmin="0" data-zmax="1">
      <div className="heatmap-grid" style={{ gridTemplateColumns: `minmax(180px, 1.4fr) repeat(${families.length}, minmax(90px, 1fr))` }}>
        <div className="heatmap-group-corner" />
        {configuredFamilies.length > 0 && <div className="heatmap-column-group" style={{ gridColumn: `span ${configuredFamilies.length}` }}>Configured Output Families</div>}
        {otherClusters.length > 0 && <div className="heatmap-column-group heatmap-column-group-others" style={{ gridColumn: `span ${otherClusters.length}` }}>Others — evidence-derived clusters</div>}
        <div className="heatmap-axis-corner">Applications</div>
        {families.map((family) => <div className="heatmap-x-label" key={family} style={familyColors(family, familyHues.get(family) ?? 0, false)}>{family}</div>)}
        {rows.map((row) => <div className="heatmap-row" key={row.renderKey} style={{ display: "contents" }}>
          <div className="heatmap-y-label" title={`${row.rationale} Confidence: ${row.confidence}.${row.fieldsUsed.length ? ` Fields: ${row.fieldsUsed.join(", ")}.` : ""}${row.matchedEvidence.length ? ` Evidence: ${row.matchedEvidence.join(", ")}.` : ""}`}>{applicationLabel(row)}</div>
          {families.map((family) => {
            const matched = row.values[family] === "Yes";
            return <div key={family} className="heatmap-cell" style={familyColors(family, familyHues.get(family) ?? 0, matched)} title={`${applicationLabel(row)} / ${family}: ${row.values[family]}${matched && row.matchedEvidence.length ? `. Evidence: ${row.matchedEvidence.join(", ")}` : ""}`}>{row.values[family]}</div>;
          })}
        </div>)}
      </div>
    </div>}
  </div>;
}

function SearchableOutputApplication({ rows, value, onChange }: { rows: FilterableMatrixRow[]; value: string; onChange: (value: string) => void }) { const listId = useId(); const selected = rows.find((row) => applicationIdentity(row) === value); const [query, setQuery] = useState(selected ? applicationLabel(selected) : ""); useEffect(() => { if (!value) setQuery(""); }, [value]); return <label>Application<input type="search" list={listId} value={query} placeholder="Type application name or code" onChange={(event) => { const next = event.target.value; const matched = rows.find((row) => applicationLabel(row).toLocaleLowerCase() === next.trim().toLocaleLowerCase()); setQuery(next); onChange(matched ? applicationIdentity(matched) : ""); }} /><datalist id={listId}>{rows.map((row) => <option key={applicationIdentity(row)} value={applicationLabel(row)} />)}</datalist></label>; }

function Table({ headers, rows, empty }: { headers: string[]; rows: Array<{ key: string; cells: Array<string | number> }>; empty: string }) {
  if (!rows.length) return <p className="message message-info">{empty}</p>;
  return <div className="table-scroll output-family-table"><table className="simple-table"><thead><tr>{headers.map((header) => <th key={header}>{header}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.key}>{row.cells.map((cell, cellIndex) => <td key={headers[cellIndex]}>{show(cell)}</td>)}</tr>)}</tbody></table></div>;
}
