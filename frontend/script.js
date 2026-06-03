/* ==========================================================================
   PaperMind — Flask-backed frontend
   ========================================================================== */

const API_BASE = "http://127.0.0.1:5000";
const STORAGE_KEYS = {
  darkMode:      "papermind_darkMode",
  pdfPanelWidth: "papermind_pdfPanelWidth",
  activePaperId: "papermind_activePaperId",
};

const state = {
  isDark:         false,
  thinking:       false,
  currentPage:    0,
  totalPages:     0,
  papers:         [],
  activePaperId:  null,
  // per-paper tab cache: paperId -> { analysis, prerequisites }
  _tabCache:      {},
  // polling timers: collectionName -> intervalId
  _pollingTimers: {},
};

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function apiUrl(path) { return `${API_BASE}${path}`; }

async function fetchJson(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) { try { data = JSON.parse(text); } catch { data = { raw: text }; } }
  if (!response.ok) throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  return data;
}

function getPaperId(p)    { return p.id || p.path || p.paperId || p.filename || p.title; }
function getPaperTitle(p) { return p.title || p.filename || p.path || "Untitled"; }
function getPaperPath(p)  { return p?.path || p?.id || p?.paperId || ""; }

function formatScore(score) {
  if (typeof score !== "number" || Number.isNaN(score)) return null;
  return score.toFixed(1);
}
function getPaperScore(p)  { const s = p?.analysis?.final_score ?? p?.final_score ?? p?.score; return typeof s === "number" ? s : null; }
function getPaperLabel(p)  { return p?.analysis?.difficulty_label || p?.difficulty_label || ""; }

function setPaperState(updated) {
  const id = getPaperId(updated);
  state.papers = state.papers.map(p =>
    getPaperId(p) !== id ? p : { ...p, ...updated, analysis: updated.analysis || p.analysis }
  );
}

function ensureActivePaper() {
  if (state.activePaperId)
    return state.papers.find(p => getPaperId(p) === state.activePaperId) || null;
  return state.papers[0] || null;
}

function setActivePaper(paperId) {
  state.activePaperId = paperId;
  localStorage.setItem(STORAGE_KEYS.activePaperId, paperId);
  state.papers = state.papers.map(p => ({ ...p, active: getPaperId(p) === paperId }));
  renderPapers();
  updatePdfHeader(ensureActivePaper());
}

function showToast(message) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function clearElement(el) { while (el.firstChild) el.removeChild(el.firstChild); }

/* ── Tab cache helpers ────────────────────────────────────────────────────── */

function getCachedTab(paperId, tabName) {
  return state._tabCache[paperId]?.[tabName] ?? null;
}

function setCachedTab(paperId, tabName, data) {
  if (!state._tabCache[paperId]) state._tabCache[paperId] = {};
  state._tabCache[paperId][tabName] = data;
}

function clearCacheForPaper(paperId) {
  delete state._tabCache[paperId];
}

/* ── Progress bar ─────────────────────────────────────────────────────────── */

function showProgressBar(pct, message) {
  let bar = document.getElementById("indexProgressBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "indexProgressBar";
    bar.className = "index-progress-bar";
    bar.innerHTML = `
      <div class="ipb-track">
        <div class="ipb-fill" id="ipbFill"></div>
      </div>
      <div class="ipb-label" id="ipbLabel"></div>`;
    // Insert just above the paper list
    const list = document.getElementById("paperList");
    if (list && list.parentNode) list.parentNode.insertBefore(bar, list);
  }
  bar.style.display = "block";
  const fill = document.getElementById("ipbFill");
  const label = document.getElementById("ipbLabel");
  if (fill) fill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
  if (label) label.textContent = message || "";
}

function hideProgressBar() {
  const bar = document.getElementById("indexProgressBar");
  if (bar) bar.style.display = "none";
}

/* ── Coming-soon box ──────────────────────────────────────────────────────── */

function makeComingSoonBox(icon, title, text, badge) {
  const box = document.createElement("div");
  box.className = "coming-soon-box";
  box.innerHTML = `
    <div class="coming-soon-icon">${icon}</div>
    <div class="coming-soon-title">${title}</div>
    <div class="coming-soon-text">${text}</div>
    ${badge ? `<div class="coming-soon-badge">${badge}</div>` : ""}`;
  return box;
}

/* ── Indexing status polling ──────────────────────────────────────────────── */

function startIndexPolling(paper) {
  const paperId        = getPaperId(paper);
  const collectionName = paper.collectionName;
  if (state._pollingTimers[collectionName]) return;

  const timer = setInterval(async () => {
    try {
      const res = await fetch(apiUrl(`/api/status/${getPaperPath(paper)}`));
      if (!res.ok) return;
      const data = await res.json();
      const { status, pct, step, message } = data;

      // Update paper in state
      state.papers = state.papers.map(p =>
        getPaperId(p) !== paperId ? p
          : { ...p, indexStatus: status, indexPct: pct, indexStep: step, indexMessage: message }
      );
      renderPapers();

      // Show progress bar only for the active paper
      if (state.activePaperId === paperId && status === "indexing") {
        showProgressBar(pct, message || step);
      }

      if (status === "ready") {
        clearInterval(timer);
        delete state._pollingTimers[collectionName];
        hideProgressBar();
        showToast(`"${getPaperTitle(paper)}" is ready!`);
      } else if (status === "error") {
        clearInterval(timer);
        delete state._pollingTimers[collectionName];
        hideProgressBar();
        showToast(`Indexing failed for "${getPaperTitle(paper)}". Try re-uploading.`);
      }
    } catch { /* network blip — keep polling */ }
  }, 2000);

  state._pollingTimers[collectionName] = timer;
}

/* ── Sidebar ──────────────────────────────────────────────────────────────── */

function renderPapers() {
  const list = document.getElementById("paperList");
  if (!list) return;
  clearElement(list);

  if (!state.papers.length) {
    const empty = document.createElement("div");
    empty.style.cssText = "padding:16px;text-align:center;color:var(--text3);font-size:12px;";
    empty.textContent = "No papers yet — upload one to get started";
    list.appendChild(empty);
    return;
  }

  state.papers.forEach(paper => {
    const paperId   = getPaperId(paper);
    const idxStatus = paper.indexStatus || "ready";
    const pct       = paper.indexPct ?? 100;

    const item = document.createElement("div");
    item.className = `paper-item${paper.active ? " active" : ""}`;

    const dot = document.createElement("div");
    dot.className = idxStatus === "indexing" ? "paper-dot indexing"
                  : idxStatus === "error"    ? "paper-dot error"
                  : "paper-dot ready";

    const info = document.createElement("div");
    info.className = "paper-info";

    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = getPaperTitle(paper);

    const meta = document.createElement("div");
    meta.className = "paper-meta";

    if (idxStatus === "indexing") {
      // Mini progress bar inside sidebar item
      meta.innerHTML = `
        <span style="color:var(--amber);">${paper.indexStep || "Indexing…"}</span>
        <div class="sidebar-mini-bar">
          <div class="sidebar-mini-fill" style="width:${pct}%"></div>
        </div>`;
    } else if (idxStatus === "error") {
      meta.textContent = "Index failed";
      meta.style.color = "var(--red)";
    } else {
      meta.textContent = "";
    }

    info.appendChild(title);
    info.appendChild(meta);
    item.appendChild(dot);
    item.appendChild(info);
    item.addEventListener("click", () => { void selectPaper(paperId); });
    list.appendChild(item);
  });
}

function updatePdfHeader(paper) {
  const el = document.getElementById("pdfTitle");
  if (!el) return;
  el.textContent = paper ? getPaperTitle(paper) : "Select a paper to view";
}

/* ── LOGOUT ───────────────────────────────────────────────────────────────── */

async function logout() {
  try { await fetch(apiUrl("/api/logout"), { method: "POST" }); } finally {
    window.location.href = "/auth";
  }
}

/* ── INSIGHTS TAB ─────────────────────────────────────────────────────────── */

function renderInsights(paper) {
  const panel = document.getElementById("insightsContent");
  if (!panel) return;
  clearElement(panel);

  if (!paper) {
    panel.appendChild(makeComingSoonBox("📄", "No Paper Selected",
      "Upload or select a paper to view its difficulty analysis.")); return;
  }
  const analysis = paper.analysis;
  if (!analysis) {
    panel.appendChild(makeComingSoonBox("⏳", "Analyzing…", "Computing difficulty analysis.")); return;
  }

  const score  = getPaperScore(paper);
  const label  = getPaperLabel(paper);
  const scores = analysis.scores    || {};
  const brk    = analysis.breakdown || {};
  const lc = { Easy: "var(--green)", Medium: "var(--amber)", Hard: "var(--red)" };
  const labelColor = lc[label] || "var(--accent)";

  function makeBar(v, max = 10) {
    const pct = Math.round((v / max) * 100);
    const w = document.createElement("div");
    w.style.cssText = "background:var(--surface2);border-radius:99px;height:6px;width:100%;margin-top:4px;";
    const f = document.createElement("div");
    f.style.cssText = `height:6px;border-radius:99px;width:${pct}%;background:var(--accent);transition:width 0.4s;`;
    w.appendChild(f); return w;
  }

  const hero = document.createElement("div");
  hero.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;";
  const pct = score !== null ? Math.round((score / 10) * 100) : 0;
  const circ = 2 * Math.PI * 36;
  const offset = circ - (pct / 100) * circ;
  hero.innerHTML = `
    <div>
      <div style="font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">Difficulty Score</div>
      <div style="font-size:42px;font-weight:700;color:var(--text);line-height:1;">${formatScore(score) ?? "N/A"}<span style="font-size:18px;color:var(--text2);"> / 10</span></div>
      <div style="margin-top:10px;"><span style="background:${labelColor}20;color:${labelColor};border:1px solid ${labelColor}40;padding:4px 12px;border-radius:99px;font-size:12px;font-weight:600;">${label || "Unknown"}</span></div>
    </div>
    <svg width="90" height="90" viewBox="0 0 90 90">
      <circle cx="45" cy="45" r="36" fill="none" stroke="var(--surface2)" stroke-width="8"/>
      <circle cx="45" cy="45" r="36" fill="none" stroke="var(--accent)" stroke-width="8"
        stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 45 45)" style="transition:stroke-dashoffset 0.6s;"/>
      <text x="45" y="50" text-anchor="middle" font-size="16" font-weight="700" fill="var(--text)">${pct}%</text>
    </svg>`;
  panel.appendChild(hero);

  const components = [
    { key: "readability",     label: "Readability",     weight: "10%", icon: "📖" },
    { key: "uncommon_words",  label: "Uncommon Words",  weight: "10%", icon: "🔤" },
    { key: "technical_terms", label: "Technical Terms", weight: "10%", icon: "🔬" },
    { key: "llm_perception",  label: "LLM Perception",  weight: "70%", icon: "🤖" },
  ];
  const compCard = document.createElement("div");
  compCard.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;margin-bottom:16px;";
  const ct = document.createElement("div");
  ct.style.cssText = "font-size:13px;font-weight:600;margin-bottom:16px;color:var(--text);";
  ct.textContent = "Component Scores";
  compCard.appendChild(ct);
  components.forEach(({ key, label: lbl, weight, icon }) => {
    const val = scores[key];
    const dv  = val !== undefined ? Number(val).toFixed(1) : "N/A";
    const row = document.createElement("div");
    row.style.cssText = "margin-bottom:14px;";
    row.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;"><span style="font-size:12px;color:var(--text2);">${icon} ${lbl} <span style="color:var(--text3);font-size:10px;">(weight ${weight})</span></span><span style="font-size:12px;font-weight:600;color:var(--text);">${dv} / 10</span></div>`;
    if (val !== undefined) row.appendChild(makeBar(Number(val)));
    compCard.appendChild(row);
  });
  panel.appendChild(compCard);

  const statsCard = document.createElement("div");
  statsCard.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;";
  const st = document.createElement("div");
  st.style.cssText = "font-size:13px;font-weight:600;margin-bottom:14px;color:var(--text);";
  st.textContent = "Paper Statistics";
  statsCard.appendChild(st);
  const stats = [
    ["Total Sentences", brk.total_sentences ?? "N/A"],
    ["Total Words",     brk.total_words     ?? "N/A"],
    ["Uncommon Word %", brk.uncommon_word_pct != null ? `${brk.uncommon_word_pct}%` : "N/A"],
    ["Tech Keyphrases", brk.technical_keyphrases  ?? "N/A"],
    ["FK Grade",        brk.flesch_kincaid_grade  ?? "N/A"],
    ["Reading Ease",    brk.flesch_reading_ease   ?? "N/A"],
  ];
  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:10px;";
  stats.forEach(([sl, sv]) => {
    const cell = document.createElement("div");
    cell.style.cssText = "background:var(--surface2);border-radius:var(--radius);padding:10px 12px;";
    cell.innerHTML = `<div style="font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:0.4px;">${sl}</div><div style="font-size:15px;font-weight:600;color:var(--text);margin-top:2px;">${sv}</div>`;
    grid.appendChild(cell);
  });
  statsCard.appendChild(grid);
  panel.appendChild(statsCard);
}

/* ── PREREQUISITES TAB ────────────────────────────────────────────────────── */

function renderPrerequisites(text) {
  const panel = document.getElementById("prerequisitesContent");
  if (!panel) return;
  clearElement(panel);

  if (!text || !text.trim()) {
    panel.appendChild(makeComingSoonBox("⚠️", "No Prerequisites Found", "The model returned an empty response.")); return;
  }

  const banner = document.createElement("div");
  banner.style.cssText = "background:var(--accent-soft);border:1px solid var(--accent-border);border-radius:var(--radius-lg);padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:10px;";
  banner.innerHTML = `<span style="font-size:20px;">🎓</span><div><div style="font-size:13px;font-weight:600;color:var(--accent);">Learning Roadmap</div><div style="font-size:11px;color:var(--text2);margin-top:2px;">Minimum prerequisites — fundamental to advanced.</div></div>`;
  panel.appendChild(banner);

  const lines = text.trim().split("\n").filter(l => l.trim());
  const items = [];
  lines.forEach(line => {
    const m = line.match(/^\s*(\d+)[.)]\s*(.+)/);
    if (!m) return;
    const content = m[2].trim();
    const ci = content.indexOf(":");
    items.push(ci !== -1
      ? { number: m[1], concept: content.slice(0, ci).trim(), explanation: content.slice(ci + 1).trim() }
      : { number: m[1], concept: content, explanation: "" });
  });

  if (!items.length) {
    const raw = document.createElement("div");
    raw.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px;white-space:pre-wrap;font-size:12.5px;color:var(--text2);line-height:1.8;";
    raw.textContent = text;
    panel.appendChild(raw); return;
  }

  items.forEach((item, idx) => {
    const card = document.createElement("div");
    const progressColor = idx < items.length * 0.33 ? "var(--green)" : idx < items.length * 0.66 ? "var(--amber)" : "var(--red)";
    card.style.cssText = `background:var(--surface);border:1px solid var(--border);border-left:3px solid ${progressColor};border-radius:var(--radius-lg);padding:14px 16px;margin-bottom:10px;display:flex;align-items:flex-start;gap:14px;transition:border-color 0.15s,box-shadow 0.15s;`;
    card.addEventListener("mouseenter", () => { card.style.borderColor = "var(--accent-border)"; card.style.boxShadow = "var(--shadow-sm)"; });
    card.addEventListener("mouseleave", () => { card.style.borderColor = "var(--border)"; card.style.boxShadow = "none"; });

    const badge = document.createElement("div");
    badge.style.cssText = "min-width:28px;height:28px;border-radius:50%;background:var(--accent);color:white;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px;";
    badge.textContent = item.number;

    const content = document.createElement("div");
    content.style.cssText = "flex:1;min-width:0;";
    const conceptEl = document.createElement("div");
    conceptEl.style.cssText = "font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px;";
    conceptEl.textContent = item.concept;
    content.appendChild(conceptEl);
    if (item.explanation) {
      const explEl = document.createElement("div");
      explEl.style.cssText = "font-size:12px;color:var(--text2);line-height:1.6;";
      explEl.textContent = item.explanation;
      content.appendChild(explEl);
    }

    card.appendChild(badge);
    card.appendChild(content);
    panel.appendChild(card);
  });

  const legend = document.createElement("div");
  legend.style.cssText = "display:flex;gap:16px;margin-top:6px;padding:10px 4px;";
  legend.innerHTML = `
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--green);display:inline-block;"></span>Foundational</span>
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--amber);display:inline-block;"></span>Intermediate</span>
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--red);display:inline-block;"></span>Advanced</span>`;
  panel.appendChild(legend);
}

/* ── EXPLAIN TAB ──────────────────────────────────────────────────────────── */

async function explainTerm() {
  const input = document.getElementById("explainInput");
  const panel = document.getElementById("explainContent");
  const paper = ensureActivePaper();
  if (!input || !panel) return;
  const term = input.value.trim();
  if (!term) { showToast("Please type a term to explain"); return; }
  if (!paper) { showToast("Upload or select a paper first"); return; }
  if ((paper.indexStatus || "ready") === "indexing") { showToast("Paper is still being indexed."); return; }

  clearElement(panel);
  panel.appendChild(makeComingSoonBox("🔍", "Looking up term…", `Generating explanation for "${term}"…`));

  try {
    const data = await fetchJson("/api/explain", {
      method: "POST",
      body: JSON.stringify({ term, paper_path: getPaperPath(paper) }),
    });
    renderExplainResult(data);
  } catch (error) {
    clearElement(panel);
    panel.appendChild(makeComingSoonBox("❌", "Explanation Failed", error.message || "Check your API key."));
  }
}

function renderExplainResult(data) {
  const panel = document.getElementById("explainContent");
  if (!panel) return;
  clearElement(panel);
  const { term, from_paper, simple_explanation, chunks_used, found_in_paper } = data;

  const badge = document.createElement("div");
  badge.style.cssText = `display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:99px;font-size:11px;font-weight:600;margin-bottom:16px;${found_in_paper ? "background:var(--green-soft);color:var(--green);border:1px solid var(--green);" : "background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber);"}`;
  badge.textContent = found_in_paper ? `Found in paper (${chunks_used} section${chunks_used !== 1 ? "s" : ""})` : "Not in paper — using general knowledge";
  panel.appendChild(badge);

  const heading = document.createElement("div");
  heading.style.cssText = "font-size:22px;font-weight:700;color:var(--text);margin-bottom:20px;letter-spacing:-0.3px;";
  heading.textContent = term.charAt(0).toUpperCase() + term.slice(1);
  panel.appendChild(heading);

  function makeCard(icon, title, content, accentColor) {
    const card = document.createElement("div");
    card.style.cssText = `background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:18px 20px;margin-bottom:14px;border-left:3px solid ${accentColor};`;
    card.innerHTML = `<div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;"><span style="font-size:16px;">${icon}</span>${title}</div><div style="font-size:13.5px;color:var(--text);line-height:1.75;">${content}</div>`;
    return card;
  }
  panel.appendChild(makeCard("📄", "From This Paper", from_paper, "var(--accent)"));
  panel.appendChild(makeCard("💡", "In Simple Words", simple_explanation, "var(--green)"));
  const hint = document.createElement("div");
  hint.style.cssText = "text-align:center;font-size:11.5px;color:var(--text3);margin-top:8px;padding:10px;";
  hint.textContent = "Try another term above";
  panel.appendChild(hint);
}

function handleExplainKey(event) {
  if (event.key === "Enter") { event.preventDefault(); void explainTerm(); }
}

/* ── Summary / Comparison placeholders ───────────────────────────────────── */

function renderSummaryComingSoon() {
  const panel = document.getElementById("summaryAccordion");
  if (!panel) return;
  clearElement(panel);
  panel.appendChild(makeComingSoonBox("📝", "Summary — Coming Soon", "Auto-generated paper summaries are in development.", "In Development"));
}

function renderComparisonComingSoon() {
  const panel = document.getElementById("comparisonContent");
  if (!panel) return;
  clearElement(panel);
  panel.appendChild(makeComingSoonBox("⚖️", "Comparison — Coming Soon", "Multi-paper comparison is in development.", "In Development"));
}

/* ── Tab switching (with caching) ────────────────────────────────────────── */

function switchTab(name) {
  const validTabs = ["chat", "summary", "insights", "prerequisites", "explain", "comparison"];
  validTabs.forEach(t => {
    document.getElementById(`tab-${t}`)?.classList.toggle("active", t === name);
    document.getElementById(`panel-${t}`)?.classList.toggle("active", t === name);
  });

  if (name === "summary")    { renderSummaryComingSoon(); return; }
  if (name === "comparison") { renderComparisonComingSoon(); return; }

  const paper = ensureActivePaper();

  // ── INSIGHTS ────────────────────────────────────────────
  if (name === "insights") {
    const panel = document.getElementById("insightsContent");
    if (!paper) { renderInsights(null); return; }
    if ((paper.indexStatus || "ready") === "indexing") {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Indexing in progress…", "Wait for the green dot, then click Insights again.")); }
      return;
    }

    // Return cached result instantly
    const paperId = getPaperId(paper);
    const cached  = getCachedTab(paperId, "insights");
    if (cached) { renderInsights(cached); return; }

    // First time — fetch from server
    if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Analyzing paper…", "Running difficulty analysis via Gemini. First time only — result will be cached after this.")); }

    fetchJson("/api/analyze", { method: "POST", body: JSON.stringify({ paper_path: getPaperPath(paper) }) })
      .then(data => {
        const analysis  = data.analysis || {};
        const paperInfo = data.paper    || paper;
        const updated   = { ...paper, ...paperInfo, analysis };
        setPaperState(updated);
        renderPapers();
        setCachedTab(paperId, "insights", updated);
        renderInsights(updated);
      })
      .catch(error => {
        if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("❌", "Analysis Failed", error.message || "Check your API key.")); }
      });
    return;
  }

  // ── PREREQUISITES ────────────────────────────────────────
  if (name === "prerequisites") {
    const panel = document.getElementById("prerequisitesContent");
    if (!paper) {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("📚", "No Paper Selected", "Upload or select a paper.")); }
      return;
    }
    if ((paper.indexStatus || "ready") === "indexing") {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Indexing in progress…", "Wait for the green dot, then click Prerequisites again.")); }
      return;
    }

    // Return cached result instantly
    const paperId = getPaperId(paper);
    const cached  = getCachedTab(paperId, "prerequisites");
    if (cached) { renderPrerequisites(cached); return; }

    // First time — fetch from server
    if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Extracting Prerequisites…", "Gemini is building a learning roadmap. First time only — result will be cached after this.")); }

    fetchJson("/api/prerequisites", { method: "POST", body: JSON.stringify({ paper_path: getPaperPath(paper) }) })
      .then(data => {
        const result = data.prerequisites || "";
        setCachedTab(paperId, "prerequisites", result);
        renderPrerequisites(result);
      })
      .catch(error => {
        if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("❌", "Extraction Failed", error.message || "Check your API key.")); }
      });
    return;
  }
}

/* ── Paper loading ────────────────────────────────────────────────────────── */

async function loadPapers() {
  const data   = await fetchJson("/api/papers", { method: "GET" });
  const papers = Array.isArray(data.papers) ? data.papers : [];

  state.papers = papers.map(p => ({ ...p, active: false }));

  const savedId = localStorage.getItem(STORAGE_KEYS.activePaperId);
  if (savedId && state.papers.some(p => getPaperId(p) === savedId)) {
    state.activePaperId = savedId;
  } else if (state.papers.length > 0) {
    state.activePaperId = getPaperId(state.papers[0]);
  } else {
    state.activePaperId = null;
  }

  state.papers = state.papers.map(p => ({ ...p, active: getPaperId(p) === state.activePaperId }));

  // Resume polling for any papers still mid-index
  state.papers.forEach(p => {
    if ((p.indexStatus || "ready") === "indexing") startIndexPolling(p);
  });

  renderPapers();
  updatePdfHeader(ensureActivePaper());
}

async function selectPaper(paperId) {
  setActivePaper(paperId);
  // Re-render the currently active tab for the new paper
  const activeTab = document.querySelector(".tab.active");
  if (activeTab) {
    const name = activeTab.id.replace("tab-", "");
    if (["insights", "prerequisites"].includes(name)) switchTab(name);
  }
  // Show/hide progress bar based on new paper's index state
  const paper = ensureActivePaper();
  if (paper && (paper.indexStatus || "ready") === "indexing") {
    showProgressBar(paper.indexPct ?? 0, paper.indexMessage || paper.indexStep || "Indexing…");
  } else {
    hideProgressBar();
  }
}

/* ── File upload ──────────────────────────────────────────────────────────── */

async function handleFiles(files) {
  const pdfs = files.filter(f => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) { showToast("Please upload PDF files only"); return; }

  for (const file of pdfs) {
    const formData = new FormData();
    formData.append("file", file);
    try {
      showToast(`Uploading ${file.name}…`);
      const response = await fetch(apiUrl("/api/upload"), { method: "POST", body: formData });
      const text     = await response.text();
      let data = {};
      if (text) { try { data = JSON.parse(text); } catch { data = {}; } }
      if (!response.ok) throw new Error(data.error || "Upload failed");

      const paper    = data.paper    || {};
      const newPaper = { ...paper, analysis: {}, indexStatus: "indexing", indexPct: 5, active: true };
      state.papers        = [newPaper, ...state.papers.map(p => ({ ...p, active: false }))];
      state.activePaperId = getPaperId(newPaper);
      localStorage.setItem(STORAGE_KEYS.activePaperId, state.activePaperId);

      renderPapers();
      updatePdfHeader(newPaper);
      showProgressBar(5, "Starting…");
      showToast(`Uploaded ${file.name} — indexing in background…`);
      startIndexPolling(newPaper);
    } catch (error) {
      console.error("Upload error:", error);
      showToast(error.message || "Upload failed");
    }
  }
}

/* ── Chat ─────────────────────────────────────────────────────────────────── */

async function sendMessage() {
  if (state.thinking) return;
  const input    = document.getElementById("chatInput");
  const chatArea = document.getElementById("chatArea");
  const thinkEl  = document.getElementById("thinkingMsg");
  const paper    = ensureActivePaper();
  if (!input || !chatArea || !thinkEl) return;
  const message = input.value.trim();
  if (!message) return;
  if (!paper) { showToast("Upload or select a paper first"); return; }
  if ((paper.indexStatus || "ready") === "indexing") { showToast("Paper is still being indexed. Please wait."); return; }

  const userMsg = document.createElement("div"); userMsg.className = "msg user";
  const body    = document.createElement("div"); body.className    = "msg-body";
  const bubble  = document.createElement("div"); bubble.className  = "msg-bubble";
  bubble.textContent = message;
  body.appendChild(bubble);
  const avatar = document.createElement("div"); avatar.className = "msg-avatar"; avatar.textContent = "U";
  userMsg.appendChild(body); userMsg.appendChild(avatar);
  chatArea.insertBefore(userMsg, thinkEl);
  input.value = ""; input.style.height = "auto";
  thinkEl.style.display = "flex"; chatArea.scrollTop = chatArea.scrollHeight;
  state.thinking = true;

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, paper_path: getPaperPath(paper) }),
    });
    thinkEl.style.display = "none";
    const aiMsg    = document.createElement("div"); aiMsg.className    = "msg assistant";
    const aiAvatar = document.createElement("div"); aiAvatar.className = "msg-avatar"; aiAvatar.textContent = "PM";
    const aiBody   = document.createElement("div"); aiBody.className   = "msg-body";
    const aiBubble = document.createElement("div"); aiBubble.className = "msg-bubble";
    aiBubble.textContent = data.reply || "No response returned.";
    const actions  = document.createElement("div"); actions.className = "msg-actions";
    const copyBtn  = document.createElement("button"); copyBtn.className = "msg-action-btn";
    copyBtn.type = "button"; copyBtn.textContent = "Copy";
    copyBtn.addEventListener("click", () => copyText(data.reply || ""));
    actions.appendChild(copyBtn);
    aiBody.appendChild(aiBubble); aiBody.appendChild(actions);
    aiMsg.appendChild(aiAvatar); aiMsg.appendChild(aiBody);
    chatArea.insertBefore(aiMsg, thinkEl); chatArea.scrollTop = chatArea.scrollHeight;
  } catch (error) {
    thinkEl.style.display = "none";
    const aiMsg    = document.createElement("div"); aiMsg.className    = "msg assistant";
    const aiAvatar = document.createElement("div"); aiAvatar.className = "msg-avatar"; aiAvatar.textContent = "PM";
    const aiBody   = document.createElement("div"); aiBody.className   = "msg-body";
    const aiBubble = document.createElement("div"); aiBubble.className = "msg-bubble";
    aiBubble.textContent = error.message || "Error: Could not get response";
    aiBody.appendChild(aiBubble); aiMsg.appendChild(aiAvatar); aiMsg.appendChild(aiBody);
    chatArea.insertBefore(aiMsg, thinkEl); chatArea.scrollTop = chatArea.scrollHeight;
  } finally {
    state.thinking = false;
  }
}

function handleKey(event) {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
}

/* ── Utilities ────────────────────────────────────────────────────────────── */

function toggleDark() {
  state.isDark = !state.isDark;
  document.body.classList.toggle("dark", state.isDark);
  const btn = document.getElementById("darkBtn");
  if (btn) btn.textContent = state.isDark ? "☀️" : "🌙";
  localStorage.setItem(STORAGE_KEYS.darkMode, String(state.isDark));
}

function changePage(delta) {
  if (!state.totalPages) { showToast("No PDF loaded"); return; }
  state.currentPage = Math.max(1, Math.min(state.totalPages, state.currentPage + delta));
  const info = document.getElementById("pageInfo");
  if (info) info.textContent = `${state.currentPage} / ${state.totalPages}`;
  showToast(`Page ${state.currentPage}`);
}

function copyText(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(() => showToast("Copied!")).catch(() => showToast("Failed to copy"));
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text; document.body.appendChild(ta); ta.select();
  document.execCommand("copy"); document.body.removeChild(ta); showToast("Copied!");
}

function setupResizeHandle() {
  const handle   = document.getElementById("resizeHandle");
  const pdfPanel = document.getElementById("pdfPanel");
  if (!handle || !pdfPanel) return;
  let isResizing = false, startX = 0, startWidth = 0;
  handle.addEventListener("mousedown", e => { isResizing = true; startX = e.clientX; startWidth = pdfPanel.offsetWidth; document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none"; });
  document.addEventListener("mousemove", e => { if (!isResizing) return; const nw = Math.max(280, Math.min(700, startWidth + (startX - e.clientX))); pdfPanel.style.width = pdfPanel.style.minWidth = `${nw}px`; });
  document.addEventListener("mouseup", () => { if (!isResizing) return; isResizing = false; document.body.style.cursor = document.body.style.userSelect = ""; localStorage.setItem(STORAGE_KEYS.pdfPanelWidth, String(pdfPanel.offsetWidth)); });
  const saved = localStorage.getItem(STORAGE_KEYS.pdfPanelWidth);
  if (saved) pdfPanel.style.width = pdfPanel.style.minWidth = `${saved}px`;
}

function setupUiBindings() {
  const fileInput = document.getElementById("fileInput");
  const dropZone  = document.getElementById("dropZone");
  const pdfClose  = document.getElementById("pdfCloseBtn");

  if (fileInput) {
    fileInput.addEventListener("change", e => { void handleFiles(Array.from(e.target.files || [])); e.target.value = ""; });
  }
  if (dropZone) {
    dropZone.addEventListener("dragover",  e => { e.preventDefault(); dropZone.style.opacity = "0.7"; });
    dropZone.addEventListener("dragleave", ()  => { dropZone.style.opacity = "1"; });
    dropZone.addEventListener("drop", e => {
      e.preventDefault(); dropZone.style.opacity = "1";
      const files = Array.from(e.dataTransfer.files || []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
      if (!files.length) { showToast("Please drop PDF files only"); return; }
      void handleFiles(files);
    });
    dropZone.addEventListener("click", () => fileInput?.click());
  }
  document.querySelector(".compare-btn")?.addEventListener("click", () => switchTab("comparison"));
  if (pdfClose) {
    pdfClose.addEventListener("click", () => {
      document.getElementById("pdfPanel")?.style.setProperty("display", "none");
      document.getElementById("resizeHandle")?.style.setProperty("display", "none");
      showToast("PDF panel hidden");
    });
  }
}

/* ── Init ─────────────────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", async () => {
  const savedDark = localStorage.getItem(STORAGE_KEYS.darkMode);
  if (savedDark === "true") {
    state.isDark = true;
    document.body.classList.add("dark");
    const btn = document.getElementById("darkBtn");
    if (btn) btn.textContent = "☀️";
  }
  setupUiBindings();
  setupResizeHandle();
  renderSummaryComingSoon();
  renderComparisonComingSoon();
  try {
    await loadPapers();
  } catch (error) {
    console.error("Init failed:", error);
    showToast(error.message || "Failed to load papers");
    renderPapers();
  }
});

/* ── Global exposure ──────────────────────────────────────────────────────── */
window.toggleDark       = toggleDark;
window.switchTab        = switchTab;
window.handleKey        = handleKey;
window.sendMessage      = sendMessage;
window.changePage       = changePage;
window.explainTerm      = explainTerm;
window.handleExplainKey = handleExplainKey;
window.logout           = logout;