import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Activity, BookOpen, CircleAlert, Download, FileSearch, GitBranch, Search, type LucideIcon } from "lucide-react";

const API = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_LABEL = new URL(API, window.location.origin).host;
type Tab = "overview" | "plan" | "papers" | "audit";
type AnyRecord = Record<string, any>;
const tabs: { id: Tab; label: string; icon: typeof Activity }[] = [
  { id: "overview", label: "Overview", icon: Activity },
  { id: "plan", label: "Search plan", icon: GitBranch },
  { id: "papers", label: "Paper cards", icon: BookOpen },
  { id: "audit", label: "Audit trail", icon: FileSearch },
];

async function request<T>(path: string): Promise<T> {
  const response = await fetch(API + path);
  if (!response.ok) throw new Error((await response.text()) || "Request failed (" + response.status + ")");
  return response.json() as Promise<T>;
}

function StatusPill({ status }: { status: string }) { return <span className={"status status-" + status.replaceAll("_", "-")}>{status.replaceAll("_", " ")}</span>; }

function runNotices(progress: AnyRecord, currentError = "") {
  const unique = [...new Set([...(progress.warnings || []), ...(progress.errors || [])].map(String))]
    .filter((item) => item !== currentError && !item.startsWith("Workflow failed:") && !/^[a-z_]+ search failed for /i.test(item));
  const warnings = unique.filter((item) => /review incomplete/i.test(item));
  const fallbackNotes = unique.filter((item) => /paper summaries (continued with fallback|could not use)/i.test(item));
  const notes = unique.filter((item) => !warnings.includes(item) && !fallbackNotes.includes(item));
  if (fallbackNotes.length === 1) notes.push(fallbackNotes[0]);
  if (fallbackNotes.length > 1) notes.push("Model fallback had issues during paper summaries; see the audit trail for batch details.");
  return { warnings, notes };
}

function organismFromPlan(plan: AnyRecord | null, question: string) {
  const text = [plan?.objective || "", ...(plan?.subquestions || []).map((item: AnyRecord) => item.text || ""), question].join(" ");
  const known = [
    ["Klebsiella pneumoniae", /\b(?:k\.?\s+|Klebsiella\s+)pneumoniae\b/i],
    ["Escherichia coli", /\b(?:e\.?\s*coli|Escherichia\s+coli)\b/i],
    ["Klebsiella aerogenes", /\b(?:k\.?\s*aerogenes|Klebsiella\s+aerogenes)\b/i],
    ["Pseudomonas aeruginosa", /\b(?:p\.?\s*aeruginosa|Pseudomonas\s+aeruginosa)\b/i],
    ["Staphylococcus aureus", /\b(?:s\.?\s*aureus|Staphylococcus\s+aureus)\b/i],
  ] as const;
  const match = known.find(([, pattern]) => pattern.test(text));
  if (match) return match[0];
  const generic = text.match(/\b([A-Z][a-z]+)\s+([a-z]{4,})\b/);
  return generic ? generic[1] + " " + generic[2] : "";
}

function organismDiffers(source: AnyRecord, target: string) {
  if (!target) return false;
  const text = (source.title + " " + source.abstract).toLowerCase();
  if (target === "Klebsiella pneumoniae") return !/klebsiella\s+pneumoniae|\bk\.?\s*pneumoniae\b/i.test(text);
  if (target === "Escherichia coli") return !/escherichia\s+coli|\be\.?\s*coli\b/i.test(text);
  if (target === "Klebsiella aerogenes") return !/klebsiella\s+aerogenes|\bk\.?\s*aerogenes\b/i.test(text);
  if (target === "Pseudomonas aeruginosa") return !/pseudomonas\s+aeruginosa|\bp\.?\s*aeruginosa\b/i.test(text);
  return !/staphylococcus\s+aureus|\bs\.?\s*aureus\b/i.test(text);
}

function PaperCard({ source, index, targetOrganism }: { source: AnyRecord; index: number; targetOrganism: string }) {
  const digest = source.paper_digest;
  if (!digest) return <article className="data-card paper-card">
    <div className="card-heading"><strong>[{index}]</strong><span className="provider">summary unavailable</span><span className={`provider relevance-chip relevance-${String(source.relevance_level || "Low").toLowerCase()}`}>{source.relevance_level || "Low"} relevance</span>{organismDiffers(source, targetOrganism) && <span className="provider organism-chip">Organism differs</span>}<span className="muted">{source.publication_year || "Year unavailable"} · {source.provider}</span></div>
    <h3>{source.title}</h3>
    <p className="muted">{source.authors?.slice(0, 8).join(", ")}{source.authors?.length > 8 ? " et al." : ""}</p>
    <div className="notice warning"><CircleAlert size={16} />No AI summary was generated for this selected record. The source text below is provided for manual review; this record does not count as summarized.</div>
    <details open><summary>Read source abstract</summary><p>{source.abstract || "No abstract supplied."}</p></details>
    <a className="external-link" href={source.url} target="_blank" rel="noreferrer">Open original paper ↗</a>{source.alternate_sources?.map((link: AnyRecord) => <a className="external-link alternate-link" href={link.url} target="_blank" rel="noreferrer" key={link.source_id}>Also indexed by {link.provider} ↗</a>)}
  </article>;
  return <article className="data-card paper-card">
    <div className="card-heading"><strong>[{index}]</strong><span className="provider">{digest.study_type?.replaceAll("_", " ") || "study type unclear"}</span><span className={`provider relevance-chip relevance-${String(source.relevance_level || "Low").toLowerCase()}`}>{source.relevance_level || "Low"} relevance</span>{organismDiffers(source, targetOrganism) && <span className="provider organism-chip">Organism differs</span>}<span className="muted">{source.publication_year || "Year unavailable"} · {source.provider}</span></div>
    <h3>{source.title}</h3>
    <p className="muted">{source.authors?.slice(0, 8).join(", ")}{source.authors?.length > 8 ? " et al." : ""}</p>
    <div className="summary-box"><strong>What this study did · AI summary of abstract</strong><p>{digest.what_study_did || "The supplied record does not provide enough detail for a study summary."}</p></div>
    <div className="paper-match"><strong>Why it matches · retrieval note</strong><p>{digest.why_it_matches || "Selected by local relevance ranking."}</p></div>
    <h4>Key findings · verbatim, checked excerpts</h4>
    {digest.key_findings?.length ? digest.key_findings.map((quote: AnyRecord, quoteIndex: number) => <blockquote key={quoteIndex}>{quote.text}<small>{quote.source_part}</small></blockquote>) : <p className="muted">No abstract text was available for a verbatim excerpt.</p>}
    <h4>Abstract’s final sentence · verbatim</h4>
    {digest.authors_conclusion ? <blockquote>{digest.authors_conclusion}<small>Copied verbatim from the abstract · read in context; TraceReview does not interpret it.</small></blockquote> : <p className="muted">No abstract final sentence is available in this record.</p>}
    <details><summary>Read full abstract</summary><p>{source.abstract || "No abstract supplied."}</p></details>
    <a className="external-link" href={source.url} target="_blank" rel="noreferrer">Open original paper ↗</a>{source.alternate_sources?.map((link: AnyRecord) => <a className="external-link alternate-link" href={link.url} target="_blank" rel="noreferrer" key={link.source_id}>Also indexed by {link.provider} ↗</a>)}
  </article>;
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [researchId, setResearchId] = useState("");
  const [research, setResearch] = useState<AnyRecord | null>(null);
  const [plan, setPlan] = useState<AnyRecord | null>(null);
  const [sources, setSources] = useState<AnyRecord[]>([]);
  const [report, setReport] = useState<AnyRecord | null>(null);
  const [audit, setAudit] = useState<AnyRecord[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const papers = useMemo(() => sources.filter((source) => source.paper_digest).sort((left, right) => (left.paper_digest.rank || 999) - (right.paper_digest.rank || 999)), [sources]);
  const selectedPapers = useMemo(() => sources.filter((source) => source.selected_for_review || source.paper_digest).sort((left, right) => (left.paper_digest?.rank || 999) - (right.paper_digest?.rank || 999)), [sources]);
  const reportPapers = (report?.report?.papers || []) as AnyRecord[];

  const refresh = useCallback(async (id: string) => {
    const root = await request<AnyRecord>("/research/" + id);
    setResearch(root);
    const settled = await Promise.allSettled([
      request<AnyRecord>("/research/" + id + "/plan"),
      request<AnyRecord[]>("/research/" + id + "/sources"),
      request<AnyRecord>("/research/" + id + "/report"),
      request<AnyRecord[]>("/research/" + id + "/audit"),
    ]);
    if (settled[0].status === "fulfilled") setPlan(settled[0].value);
    if (settled[1].status === "fulfilled") setSources(settled[1].value);
    if (settled[2].status === "fulfilled") setReport(settled[2].value);
    if (settled[3].status === "fulfilled") setAudit(settled[3].value);
    return root;
  }, []);

  useEffect(() => {
    if (!researchId || (research?.status && ["completed", "failed"].includes(research.status))) return;
    const timer = window.setInterval(() => { refresh(researchId).catch((reason) => setError(String(reason))); }, 2500);
    return () => window.clearInterval(timer);
  }, [researchId, research?.status, refresh]);

  const startResearch = async (event: FormEvent) => {
    event.preventDefault();
    if (question.trim().length < 10 || busy) return;
    setBusy(true); setError(""); setResearch(null); setPlan(null); setSources([]); setReport(null); setAudit([]);
    try {
      const response = await fetch(API + "/research", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: question.trim() }) });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "Request failed (" + response.status + ")");
      setResearchId(body.research_id || body.run_id);
      setResearch({ status: body.status, question: question.trim(), progress: { current_node: "queued" } });
      setTab("overview");
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };

  const downloadReport = async () => {
    if (!researchId) return;
    try {
      const response = await fetch(API + "/research/" + researchId + "/report?format=markdown");
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = "tracereview-" + researchId + ".md"; anchor.click(); URL.revokeObjectURL(url);
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
  };

  const status = research?.status || "idle";
  const progress = research?.progress || {};
  const notices = runNotices(progress, research?.error || "");
  const targetOrganism = organismFromPlan(plan, research?.question || question);

  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark"><FileSearch size={18} /></span><span>TraceReview<small>Literature review you can trace</small></span></a><div className="topbar-right"><span className="api-dot" /> API <code>{API_LABEL}</code></div></header>
    <main id="top" className="layout">
      <section className="hero"><div className="eyebrow">PAPER FIRST · SOURCE WORDING</div><h1>Literature review you can trace</h1><p>Find a focused set of relevant papers. Read concise study summaries, checked excerpts, and each abstract’s final sentence. You decide what the evidence means.</p></section>
      <form className="question-card" onSubmit={startResearch}><label htmlFor="research-question">Research question</label><textarea id="research-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What experimental evidence supports antimicrobial resistance mechanisms in Klebsiella pneumoniae?" minLength={10} maxLength={4000} required /><div className="form-footer"><span>TraceReview returns up to 10 paper cards; it does not judge whether authors’ claims are true.</span><button type="submit" disabled={busy || question.trim().length < 10}><Search size={16} />{busy ? "Starting…" : "Start research"}</button></div></form>
      {error && <div className="notice error"><CircleAlert size={17} />{error}</div>}
      {researchId && research && <>
        <section className="run-banner"><div><div className="run-label">CURRENT RESEARCH RUN</div><strong>{research.question || question}</strong><code>{researchId}</code></div><StatusPill status={status} /></section>
        <nav className="tabs" aria-label="Research sections">{tabs.map(({ id, label, icon: Icon }) => <button type="button" key={id} className={tab === id ? "tab active" : "tab"} onClick={() => setTab(id)}><Icon size={16} />{label}<span className="tab-count">{id === "papers" ? selectedPapers.length : id === "audit" ? audit.length : ""}</span></button>)}</nav>
        {tab === "overview" && <section className="panel"><div className="panel-title"><div><div className="eyebrow">RUN OVERVIEW</div><h2>Progress</h2></div></div><div className="progress-line"><span className={"progress-dot " + status} /><div><strong>{progress.last_action || progress.current_node || status}</strong><small>{status === "completed" ? (report?.report?.coverage?.unreviewed_selected_records ? "Paper cards are ready; some selected sources could not be summarized." : "All selected paper summaries and the executive summary are ready.") : status === "failed" ? "Run stopped without any completed paper cards; inspect the run notes." : "The state refreshes as each agent completes."}</small></div><StatusPill status={status} /></div>{research.error && <div className="notice error"><CircleAlert size={16} />{research.error}</div>}{notices.warnings.map((notice: string) => <div className="notice warning" key={notice}><CircleAlert size={16} />{notice}</div>)}{notices.notes.length > 0 && <details className="run-notes"><summary>Run notes ({notices.notes.length})</summary><ul>{notices.notes.map((notice: string) => <li key={notice}>{notice}</li>)}</ul></details>}<div className="stat-grid paper-stat-grid"><Stat icon={Search} label="Retrieved records" value={sources.length} /><Stat icon={BookOpen} label="Summaries completed" value={papers.length} /><Stat icon={FileSearch} label="Audit events" value={audit.length} /></div><div className="summary-box"><div className="eyebrow">WHAT THIS RUN DOES</div><p>It ranks unique papers, selects up to 10 with abstracts of at least 200 characters, and creates reading summaries. Source wording is cleaned of HTML/XML markup before excerpts are checked. You decide what each paper means.</p></div>{reportPapers.length > 0 && <div className="report-summary"><div className="eyebrow">AUTHORS’ CONCLUSIONS AT A GLANCE</div><div className="conclusion-list">{reportPapers.map((paper: AnyRecord) => <p key={paper.source.source_id}>[{paper.reference_number}] {paper.source.publication_year || "Year unavailable"} · {paper.source.authors?.[0]?.split(" ").slice(-1)[0] || "Author unavailable"}{paper.source.authors?.length > 1 ? " et al." : ""} — “{paper.digest.authors_conclusion || "No final abstract sentence available."}”</p>)}</div></div>}{selectedPapers.length > 0 && <div className="paper-index"><div className="eyebrow">PAPER INDEX</div><div className="table-wrap"><table><thead><tr><th>#</th><th>Title</th><th>Year</th><th>Study type</th><th>Organism</th></tr></thead><tbody>{selectedPapers.map((source, index) => <tr key={source.source_id}><td>{index + 1}</td><td><a href={source.url} target="_blank" rel="noreferrer">{source.title}</a></td><td>{source.publication_year || "—"}</td><td>{source.paper_digest?.study_type?.replaceAll("_", " ") || "Summary unavailable"}</td><td>{organismDiffers(source, targetOrganism) ? <span className="organism-chip">Different</span> : targetOrganism || "Not identified"}</td></tr>)}</tbody></table></div></div>}{report?.report?.coverage && <p className="muted">Review coverage: {report.report.coverage.reviewed_records} paper cards completed from {report.report.coverage.selected_records} selected records. {report.report.coverage.unreviewed_selected_records} selected records were not summarized.</p>}{selectedPapers.length > 0 && <button className="secondary-button" type="button" onClick={() => setTab("papers")}>View {selectedPapers.length} selected paper records</button>}</section>}
        {tab === "plan" && <section className="panel"><PanelTitle eyebrow="SEARCH PLAN" title="Question and search strategy" /><p className="lead">{plan?.objective || "The planner has not completed yet."}</p>{plan?.search_strategy && <div className="strategy"><strong>Search strategy</strong><p>{plan.search_strategy}</p><div className="source-chips">{plan.source_types?.map((source: string) => <span key={source}>{source}</span>)}</div></div>}<ol className="question-list">{plan?.subquestions?.map((item: AnyRecord) => <li key={item.id || item.position}><span>{String((item.position || 0) + 1).padStart(2, "0")}</span>{item.text}</li>)}</ol><h3>Search queries</h3><div className="card-list">{plan?.search_queries?.map((query: AnyRecord) => <article className="data-card" key={query.query_id}><div className="card-heading"><strong>{query.query_id}</strong><div className="source-chips">{query.source_names?.map((source: string) => <span key={source}>{source}</span>)}</div></div><p>{query.query}</p></article>)}</div></section>}
        {tab === "papers" && <section className="panel"><div className="panel-title"><PanelTitle eyebrow="PAPER DIGEST" title={papers.length + " summaries · " + selectedPapers.length + " selected records"} /><button className="secondary-button" type="button" onClick={downloadReport} disabled={!report?.markdown}><Download size={16} />Download digest</button></div><p className="muted">AI summaries and match notes are reading aids, not scientific verdicts. A selected source without a summary is shown with its abstract and clearly marked as unreviewed.</p><div className="card-list">{selectedPapers.map((source, index) => <PaperCard source={source} index={index + 1} targetOrganism={targetOrganism} key={source.source_id} />)}</div>{selectedPapers.length === 0 && <Empty loading={status === "running" || status === "queued"} text="Selected paper records appear here as retrieval completes." />}</section>}
        {tab === "audit" && <section className="panel"><PanelTitle eyebrow="OBSERVABILITY" title="Research run trace" /><p className="muted">Structured execution trace. No chain-of-thought is stored.</p><div className="timeline">{audit.map((event) => <article className="timeline-event" key={event.event_id}><span className="timeline-marker" /><div className="timeline-header"><div><strong>{event.node}</strong><span>{event.action}</span></div><time>{new Date(event.timestamp).toLocaleString()}</time></div><div className="event-metrics">{event.latency_ms != null && <span>{Math.round(event.latency_ms)} ms</span>}{event.prompt_tokens != null && <span>{event.prompt_tokens} input tokens</span>}{event.completion_tokens != null && <span>{event.completion_tokens} output tokens</span>}</div><details><summary>Event details</summary><pre>{JSON.stringify(event.details, null, 2)}</pre><div className="event-refs"><span>In: {event.input_refs?.join(", ") || "—"}</span><span>Out: {event.output_refs?.slice(0, 12).join(", ") || "—"}</span></div></details></article>)}</div>{audit.length === 0 && <Empty loading={status === "running" || status === "queued"} text="Events will appear as the workflow progresses." />}</section>}
      </>}
    </main><footer>TraceReview <span>·</span> Paper summaries with source wording for researchers to interpret.</footer>
  </div>;
}

function Stat({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: number }) { return <div className="stat"><span className="stat-icon"><Icon size={17} /></span><strong>{value}</strong><span>{label}</span></div>; }
function PanelTitle({ eyebrow, title }: { eyebrow: string; title: string }) { return <div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div>; }
function Empty({ text, loading = false }: { text: string; loading?: boolean }) { return loading ? <div className="empty-state" role="status" aria-live="polite"><div className="skeleton-list" aria-hidden="true"><span /><span /><span /></div><p>{text}</p></div> : <div className="empty">{text}</div>; }
