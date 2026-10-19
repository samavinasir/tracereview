const root = document.body;
const content = document.querySelector("#workspace-content");
const errorBox = document.querySelector("#workspace-error");
const runStatus = document.querySelector("#workspace-status");
const runStatusLabel = document.querySelector("#run-status-label");
const runIndicator = document.querySelector("#run-status-indicator");
const id = encodeURIComponent(root.dataset.researchId);
const csrfToken = document.querySelector(".csrf-source [name=csrfmiddlewaretoken]").value;
const page = root.dataset.page;
const view = root.dataset.view;
const state = { research: null, plan: null, sources: [], evidence: [], report: null, audit: [], timer: null, sourceFilter: "all", textFilter: "", sort: "relevance", pendingNotes: new Map(), noteTimers: new Map() };
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const pretty = (value) => escapeHtml(value || "").replaceAll("_", " ");
const statusPill = (status) => `<span class="status status-${escapeHtml(status).replaceAll("_", "-")}">${pretty(status)}</span>`;
const list = (items, renderer, empty = "Nothing available yet.") => items?.length ? items.map(renderer).join("") : `<div class="empty">${escapeHtml(empty)}</div>`;

async function getJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

function showError(message) { errorBox.hidden = !message; errorBox.textContent = message || ""; }

function activityLabel(research) {
  const status = research?.status || "queued";
  const progress = research?.progress || {};
  if (status === "completed") return "Research complete · Results are ready";
  if (status === "failed") return "Research run stopped · Open run details";
  if (status === "queued") return "Preparing your search…";
  const node = String(progress.current_node || "").toLowerCase();
  if (node.includes("digest") || node.includes("paper")) return `Summarizing papers: ${progress.paper_count || 0} of ${Math.max(progress.source_count || 0, 1)}`;
  if (node.includes("retriev") || node.includes("search")) return "Searching scholarly sources…";
  if (node.includes("select") || node.includes("screen")) return `Screening records: ${progress.source_count || 0} found`;
  if (node.includes("report")) return "Preparing research results…";
  return "Research in progress…";
}

function updateStatus() {
  const status = state.research?.status || "queued";
  const label = activityLabel(state.research);
  runStatus.className = `status status-${status.replaceAll("_", "-")}`;
  runStatus.textContent = status === "completed" ? "Complete" : status === "failed" ? "Stopped" : status;
  runStatusLabel.textContent = label;
  runIndicator.classList.toggle("is-running", !["completed", "failed"].includes(status));
  const navViews = page === "results" ? ["results", "papers", "export"] : ["overview", "plan", "audit"];
  document.querySelectorAll("[data-view-link]").forEach((link) => link.classList.toggle("active", navViews.includes(link.dataset.viewLink) && link.dataset.viewLink === view));
  document.querySelector(".primary-research-nav").hidden = page !== "results";
  document.querySelector(".run-details-nav").hidden = page !== "run";
  document.querySelector("#workspace-kicker").textContent = page === "run" ? "RUN DETAILS" : ({ papers: "PAPER LIBRARY", evidence: "SOURCE EVIDENCE", synthesis: "RESEARCH SYNTHESIS", export: "EXPORT", results: "RESEARCH RESULTS" }[view] || "RESEARCH RESULTS");
}

async function refresh() {
  const settled = await Promise.allSettled([
    getJson(`/research/${id}`), getJson(`/research/${id}/plan`), getJson(`/research/${id}/sources`),
    getJson(`/research/${id}/evidence`), getJson(`/research/${id}/report`), getJson(`/research/${id}/audit`),
  ]);
  if (settled[0].status === "fulfilled") state.research = settled[0].value;
  if (settled[1].status === "fulfilled") state.plan = settled[1].value;
  if (settled[2].status === "fulfilled") state.sources = settled[2].value.map((source) => state.pendingNotes.has(source.source_id) ? { ...source, review_note: state.pendingNotes.get(source.source_id) } : source);
  if (settled[3].status === "fulfilled") state.evidence = settled[3].value;
  if (settled[4].status === "fulfilled") state.report = settled[4].value;
  if (settled[5].status === "fulfilled") state.audit = settled[5].value;
  if (settled[0].status === "rejected") showError(settled[0].reason.message);
  else showError("");
  render();
  if (["completed", "failed"].includes(state.research?.status) && state.timer) { clearInterval(state.timer); state.timer = null; }
}

async function saveDecision(source, decision) {
  const response = await fetch(`/research/${id}/sources/decision`, {
    method: "POST", headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken, Accept: "application/json" },
    body: JSON.stringify({ source_id: source.source_id, decision, note: source.review_note || "" }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Could not save decision (${response.status})`);
  source.review_decision = decision;
  state.pendingNotes.delete(source.source_id);
  render();
}

function sourceDecision(source) { return source.review_decision || (source.selected_for_review || source.paper_digest ? "include" : "unreviewed"); }

function paperCard(source, index, compact = false) {
  const digest = source.paper_digest;
  const links = [source.url, ...(source.alternate_sources || []).map((item) => item.url)].filter(Boolean);
  const authors = (source.authors || []).slice(0, 6).join(", ") + (source.authors?.length > 6 ? " et al." : "");
  const snippets = state.evidence.filter((item) => item.source?.source_id === source.source_id);
  const matches = source.matched_terms?.length ? `<span>Matched: ${escapeHtml(source.matched_terms.join(", "))}</span>` : "";
  return `<article class="data-card paper-card">
    <div class="card-heading"><strong class="paper-number">${String(index + 1).padStart(2, "0")}</strong><span class="provider">${pretty(digest?.study_type || "summary pending")}</span><span class="provider relevance-chip">${escapeHtml(source.relevance_level || "Unrated")} relevance</span><span class="muted">${escapeHtml(source.publication_year || "Year unavailable")} · ${escapeHtml(source.provider)}</span></div>
    <h3>${escapeHtml(source.title)}</h3><p class="muted paper-authors">${escapeHtml(authors)}</p>
    <p class="match-reason">${escapeHtml(source.relevance_reason || source.exclusion_reason || "Relevance has not been assessed yet.")} ${matches}</p>
    ${digest ? `<div class="summary-box"><strong>Paper at a glance <span>AI reading aid · indexed record</span></strong><p>${escapeHtml(digest.what_study_did || "Not reported in the accessible record.")}</p></div>
      ${compact ? "" : `<div class="paper-match"><strong>Why it matches</strong><p>${escapeHtml(digest.why_it_matches || "See the question-term match above.")}</p></div>
      <h4>Source excerpts · checked against the record</h4>${list(digest.key_findings, (quote) => `<blockquote>${escapeHtml(quote.text)}<small>${escapeHtml(quote.source_part)}</small></blockquote>`, "No checked excerpt is available for this record.")}`}` : `<div class="notice info">A paper summary is not available. Open the record to inspect the source directly.</div>`}
    ${source.exclusion_reason ? `<p class="muted">Automatic screening: ${escapeHtml(source.exclusion_reason)}</p>` : ""}
    ${compact ? "" : `<label class="decision-note">Review note<input data-note="${escapeHtml(source.source_id)}" maxlength="1000" value="${escapeHtml(source.review_note || "")}" placeholder="Add a note about this paper"></label>
      <div class="decision-actions"><button type="button" data-decision="include" data-source="${escapeHtml(source.source_id)}" class="${sourceDecision(source) === "include" ? "selected" : ""}">Include</button><button type="button" data-decision="exclude" data-source="${escapeHtml(source.source_id)}" class="${sourceDecision(source) === "exclude" ? "selected" : ""}">Exclude</button><button type="button" data-decision="unreviewed" data-source="${escapeHtml(source.source_id)}">Clear</button></div>
      ${source.abstract ? `<details><summary>Read indexed abstract</summary><p>${escapeHtml(source.abstract)}</p></details>` : ""}
      ${snippets.length ? `<details><summary>${snippets.length} linked evidence excerpt(s)</summary>${snippets.map((item) => `<blockquote>${escapeHtml(item.text)}<small>${escapeHtml(item.source_part)} · ${escapeHtml(item.evidence_level)}</small></blockquote>`).join("")}</details>` : ""}`}
    <div class="paper-source-links">${links.map((url, linkIndex) => `<a class="external-link" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${linkIndex ? `Alternate source ${linkIndex}` : "Open original paper"} ↗</a>`).join("")}</div>
  </article>`;
}

function selectedSources() { return state.sources.filter((source) => source.selected_for_review || source.paper_digest); }

function renderResults() {
  const papers = selectedSources().sort((a, b) => (a.paper_digest?.rank || 999) - (b.paper_digest?.rank || 999));
  const status = state.research?.status;
  return `<section class="results-intro"><div><div class="eyebrow">RESULTS OVERVIEW</div><h2>Your research, ready to review</h2><p>Review papers matched to your question, inspect their summaries, and open the linked records.</p></div><a class="secondary-button" href="/research/${id}/run">View run details <span aria-hidden="true">↗</span></a></section>
    ${status !== "completed" && status !== "failed" ? `<section class="workspace-loading"><span class="loading-spinner"></span><div><strong>Results are building</strong><p>Paper cards will appear here as retrieval and summarization progress.</p></div></section>` : ""}
    <section class="results-metrics results-overview-metrics"><div><strong>${state.sources.length}</strong><span>Records found</span></div><div><strong>${papers.length}</strong><span>Paper cards</span></div></section>
    <section class="panel selected-papers"><div class="section-heading"><div><div class="eyebrow">START WITH THESE PAPERS</div><h3>${papers.length} selected paper${papers.length === 1 ? "" : "s"}</h3><p>Ranked by overlap with your question. Summaries reflect only the accessible source record.</p></div><a class="secondary-button" href="/research/${id}/results?view=papers">All papers <span aria-hidden="true">→</span></a></div><div class="card-list">${list(papers.slice(0, 3), (source, index) => paperCard(source, index, true), status === "failed" ? state.research?.error || "This run stopped before it created paper cards." : "Paper cards will appear when retrieval and summarization finish.")}</div></section>`;
}

function renderPapers() {
  const query = state.textFilter.trim().toLocaleLowerCase();
  let papers = state.sources.filter((source) => {
    const decision = sourceDecision(source);
    const matchesFilter = state.sourceFilter === "all" || (state.sourceFilter === "selected" ? source.selected_for_review || source.paper_digest : state.sourceFilter === "unreviewed" ? decision === "unreviewed" : decision === "exclude" || source.exclusion_reason);
    return matchesFilter && (!query || `${source.title} ${source.abstract} ${source.authors?.join(" ")}`.toLocaleLowerCase().includes(query));
  });
  papers.sort((a, b) => state.sort === "year" ? (b.publication_year || 0) - (a.publication_year || 0) : (b.relevance_score || 0) - (a.relevance_score || 0));
  return `<section class="panel"><div class="section-heading"><div><div class="eyebrow">PAPER LIBRARY</div><h2>${state.sources.length} retrieved records</h2><p>Inspect relevance, source metadata, the indexed abstract, and your screening decision.</p></div></div>
    <div class="paper-controls"><input data-paper-search type="search" value="${escapeHtml(state.textFilter)}" placeholder="Search titles, authors, abstracts"><select data-paper-filter><option value="all" ${state.sourceFilter === "all" ? "selected" : ""}>All records</option><option value="selected" ${state.sourceFilter === "selected" ? "selected" : ""}>Selected for summary</option><option value="unreviewed" ${state.sourceFilter === "unreviewed" ? "selected" : ""}>Unreviewed</option><option value="excluded" ${state.sourceFilter === "excluded" ? "selected" : ""}>Excluded</option></select><select data-paper-sort><option value="relevance" ${state.sort === "relevance" ? "selected" : ""}>Sort by relevance</option><option value="year" ${state.sort === "year" ? "selected" : ""}>Sort by newest year</option></select></div>
    <div class="card-list">${list(papers, paperCard, ["running", "queued"].includes(state.research?.status) ? "Records appear as retrieval completes." : "No papers match these filters. Try All records or clear the search.")}</div></section>`;
}

function renderEvidence() {
  if (!state.evidence.length) return `<section class="empty-evidence evidence-empty"><div class="empty-evidence-icon" aria-hidden="true">“</div><div><div class="eyebrow">EVIDENCE INSPECTOR</div><h2>No extracted evidence records yet</h2><p>${state.research?.status === "completed" ? "This run did not create structured evidence excerpts. The paper-first review currently summarizes accessible records; evidence extraction requires passages that can be checked against the source text. You can still read each indexed abstract and open the original source from Papers." : "Evidence excerpts are added only after source passages are retrieved and checked. They may not be available while this run is still searching."}</p><a href="/research/${id}/results?view=papers">Go to papers →</a></div></section>`;
  return `<section class="panel"><div class="section-heading"><div><div class="eyebrow">EVIDENCE INSPECTOR</div><h2>${state.evidence.length} source-linked excerpts</h2><p>Each excerpt stays connected to the record and passage from which it came.</p></div></div><div class="card-list">${list(state.evidence, (item) => `<article class="data-card evidence-card"><div class="card-heading"><span class="provider">${escapeHtml(item.source_part || "source")}</span><span class="provider">${pretty(item.evidence_level)}</span><span class="muted">${escapeHtml(item.evidence_type)}</span></div><blockquote>${escapeHtml(item.text)}</blockquote><a class="external-link" href="${escapeHtml(item.source?.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.source?.title || item.source?.source_id || "Open source")} ↗</a><p class="muted">Question: ${escapeHtml(item.subquestion || "")}</p></article>`)}</div></section>`;
}

function renderSynthesis() {
  const papers = state.report?.report?.papers || [];
  const conclusions = papers.filter((paper) => paper.digest?.authors_conclusion);
  return `<section class="panel synthesis-panel"><div class="eyebrow">SOURCE-BY-SOURCE SYNTHESIS</div><h2>What the selected records report</h2><div class="notice info">This view groups each paper’s abstract conclusion separately. It does not combine the papers into a claim about what is true. Read the full linked sources and consider their methods and limitations.</div>
    <div class="card-list">${list(conclusions, (paper) => `<article class="data-card synthesis-card"><div class="card-heading"><span class="provider">${escapeHtml(paper.source?.publication_year || "Year unavailable")}</span><span class="muted">${escapeHtml(paper.source?.authors?.[0] || "Author unavailable")}</span></div><h3>${escapeHtml(paper.source?.title || "Untitled paper")}</h3><blockquote>${escapeHtml(paper.digest.authors_conclusion)}<small>Final sentence of indexed abstract · source wording</small></blockquote><a href="${escapeHtml(paper.source?.url || "#")}" target="_blank" rel="noopener noreferrer">Open source ↗</a></article>`, state.research?.status === "completed" ? "The selected records did not provide an abstract final sentence." : "Conclusions will appear after paper summaries finish.")}</div></section>`;
}

function renderExport() {
  return `<section class="panel export-panel"><div class="eyebrow">TAKE YOUR REVIEW WITH YOU</div><h2>Export research results</h2><p>Download a Markdown digest containing the research question, paper summaries, source-linked excerpts, and search method.</p><div class="export-actions"><a class="primary-button ${state.report?.markdown ? "" : "disabled"}" ${state.report?.markdown ? `href="/research/${id}/report?format=markdown" download` : "aria-disabled=\"true\""}>Download Markdown <span aria-hidden="true">↓</span></a><a class="secondary-button" href="/research/${id}/report" target="_blank" rel="noopener noreferrer">Open report JSON ↗</a></div>${state.report?.markdown ? `<p class="muted">Includes ${selectedSources().length} selected record${selectedSources().length === 1 ? "" : "s"}. Your manual screening notes are saved in the workspace.</p>` : `<p class="muted">The export becomes available when the report is ready.</p>`}</section>`;
}

function renderRunOverview() {
  const research = state.research || {}, progress = research.progress || {};
  return `<section class="panel run-overview"><div class="eyebrow">LIVE WORKFLOW</div><h2>${escapeHtml(activityLabel(research))}</h2><p>${research.status === "completed" ? "The research run is complete. Review the results whenever you are ready." : research.status === "failed" ? "The run stopped. See the message below, then return to Results to review any records already found." : "The search, retrieval, and paper-summary steps are running in the background."}</p>${research.error ? `<div class="notice error">${escapeHtml(research.error)}</div>` : ""}<div class="results-metrics"><div><strong>${progress.source_count || 0}</strong><span>Records retrieved</span></div><div><strong>${progress.paper_count || 0}</strong><span>Paper summaries</span></div><div><strong>${progress.event_count || state.audit.length}</strong><span>Run events</span></div></div><a class="primary-button" href="/research/${id}/results">Open results <span aria-hidden="true">→</span></a><details class="run-details"><summary>Run warnings and errors</summary>${list([...(progress.warnings || []), ...(progress.errors || [])], (warning) => `<p>${escapeHtml(warning)}</p>`, "No warnings recorded.")}</details></section>`;
}

function renderPlan() {
  const plan = state.plan || {};
  return `<section class="panel"><div class="eyebrow">SEARCH PLAN</div><h2>${escapeHtml(plan.objective || "Search plan is being prepared")}</h2><p class="lead">${escapeHtml(plan.search_strategy || "The search strategy will appear here when planning finishes.")}</p><div class="source-chips">${(plan.source_types || []).map((source) => `<span>${escapeHtml(source)}</span>`).join("")}</div><h3>Search questions</h3><ol class="question-list">${(plan.subquestions || []).map((item, index) => `<li><span>${String(index + 1).padStart(2, "0")}</span>${escapeHtml(item.text)}</li>`).join("")}</ol><h3>Queries and providers</h3><div class="card-list">${list(plan.search_queries, (query) => `<article class="data-card"><div class="card-heading"><strong>${escapeHtml(query.query_id)}</strong><div class="source-chips">${(query.source_names || []).map((source) => `<span>${escapeHtml(source)}</span>`).join("")}</div></div><p>${escapeHtml(query.query)}</p></article>`, "Queries appear after planning finishes.")}</div></section>`;
}

function renderAudit() {
  return `<section class="panel"><div class="eyebrow">RUN OBSERVABILITY</div><h2>${state.audit.length} workflow events</h2><p class="muted">Provider activity, timings, and structured workflow events. No chain-of-thought is stored.</p><div class="timeline">${list(state.audit, (event) => `<article class="timeline-event"><span class="timeline-marker"></span><div class="timeline-header"><div><strong>${escapeHtml(event.node)}</strong><span>${escapeHtml(event.action)}</span></div><time>${escapeHtml(event.timestamp ? new Date(event.timestamp).toLocaleString() : "")}</time></div><div class="event-metrics">${event.latency_ms != null ? `<span>${Math.round(event.latency_ms)} ms</span>` : ""}${event.prompt_tokens != null ? `<span>${event.prompt_tokens} input tokens</span>` : ""}${event.completion_tokens != null ? `<span>${event.completion_tokens} output tokens</span>` : ""}</div><details><summary>Provider and event details</summary><pre>${escapeHtml(JSON.stringify(event.details, null, 2))}</pre><div class="event-refs"><span>Inputs: ${escapeHtml(event.input_refs?.join(", ") || "—")}</span><span>Outputs: ${escapeHtml(event.output_refs?.slice(0, 12).join(", ") || "—")}</span></div></details></article>`, "Run events will appear as the workflow progresses.")}</div></section>`;
}

function render() {
  if (!state.research) return;
  document.querySelector("#workspace-question").textContent = state.research.question || "Research run";
  document.title = `${state.research.question || "Research"} · TraceReview`;
  updateStatus();
  const renderers = { results: renderResults, papers: renderPapers, evidence: renderEvidence, synthesis: renderSynthesis, export: renderExport, overview: renderRunOverview, plan: renderPlan, audit: renderAudit };
  content.innerHTML = (renderers[view] || renderResults)();
}

content.addEventListener("input", (event) => {
  if (event.target.matches("[data-paper-search]")) {
    state.textFilter = event.target.value;
    const caret = event.target.selectionStart;
    render();
    const input = content.querySelector("[data-paper-search]");
    input?.focus(); input?.setSelectionRange(caret, caret);
  }
  if (event.target.matches("[data-note]")) {
    const source = state.sources.find((item) => item.source_id === event.target.dataset.note);
    if (!source) return;
    source.review_note = event.target.value;
    state.pendingNotes.set(source.source_id, source.review_note);
    clearTimeout(state.noteTimers.get(source.source_id));
    state.noteTimers.set(source.source_id, setTimeout(async () => {
      try { await saveDecision(source, sourceDecision(source)); showError(""); }
      catch (error) { showError(`Review note not saved: ${error.message}`); }
      finally { state.noteTimers.delete(source.source_id); }
    }, 800));
  }
});

content.addEventListener("change", (event) => {
  if (event.target.matches("[data-paper-filter]")) { state.sourceFilter = event.target.value; render(); }
  if (event.target.matches("[data-paper-sort]")) { state.sort = event.target.value; render(); }
});

content.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-decision]");
  if (!button) return;
  const source = state.sources.find((item) => item.source_id === button.dataset.source);
  if (!source) return;
  clearTimeout(state.noteTimers.get(source.source_id)); state.noteTimers.delete(source.source_id);
  button.disabled = true;
  try { await saveDecision(source, button.dataset.decision); showError(""); }
  catch (error) { showError(error.message); }
  finally { button.disabled = false; }
});

refresh().then(() => {
  if (!["completed", "failed"].includes(state.research?.status)) state.timer = setInterval(() => refresh().catch((error) => showError(error.message)), 2500);
}).catch((error) => showError(error.message));
