/* ==========================================================================
   PaperMind — Flask-backed frontend
   Tabs: Chat | Summary (coming soon) | Insights (difficulty score) |
         Prerequisites (Gemini roadmap) | Comparison (coming soon)
   ========================================================================== */

const API_BASE = "http://127.0.0.1:5000";
const STORAGE_KEYS = {
  darkMode:      "papermind_darkMode",
  pdfPanelWidth: "papermind_pdfPanelWidth",
  activePaperId: "papermind_activePaperId",
};

const state = {
  isDark:        false,
  thinking:      false,
  currentPage:   0,
  totalPages:    0,
  papers:        [],
  activePaperId: null,
  loadingPaperId: null,
};

/* ── helpers ──────────────────────────────────────────────────────────────── */

function apiUrl(path) { return `${API_BASE}${path}`; }

async function fetchJson(path, options = {}) {
  const response = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) { try { data = JSON.parse(text); } catch { data = { raw: text }; } }
  if (!response.ok) {
    throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function getPaperId(p)    { return p.id || p.path || p.paperId || p.filename || p.title; }
function getPaperTitle(p) { return p.title || p.filename || p.path || "Untitled paper"; }
function getPaperPath(p)  { return p?.path || p?.id || p?.paperId || ""; }

function formatScore(score) {
  if (typeof score !== "number" || Number.isNaN(score)) return null;
  return score.toFixed(1);
}
function getPaperScore(p) {
  const s = p?.analysis?.final_score ?? p?.final_score ?? p?.score;
  return typeof s === "number" ? s : null;
}
function getPaperLabel(p) {
  return p?.analysis?.difficulty_label || p?.difficulty_label || "";
}

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

/* ── Coming-soon box builder ──────────────────────────────────────────────── */

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

/* ── Sidebar paper list ───────────────────────────────────────────────────── */

function renderPapers() {
  const list = document.getElementById("paperList");
  if (!list) return;
  clearElement(list);

  if (!state.papers.length) {
    const empty = document.createElement("div");
    empty.style.cssText = "padding:16px;text-align:center;color:var(--text3);font-size:12px;";
    empty.textContent = "No papers available";
    list.appendChild(empty);
    return;
  }

  state.papers.forEach(paper => {
    const paperId = getPaperId(paper);
    const item = document.createElement("div");
    item.className = `paper-item${paper.active ? " active" : ""}`;

    const dot = document.createElement("div");
    dot.className = `paper-dot ${paper.status === "ready" ? "ready" : "indexing"}`;

    const info = document.createElement("div");
    info.className = "paper-info";

    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = getPaperTitle(paper);

    const meta = document.createElement("div");
    meta.className = "paper-meta";
    const score = getPaperScore(paper);
    const label = getPaperLabel(paper);
    const parts = [];
    if (score !== null) parts.push(`Score ${formatScore(score)}/10`);
    if (label) parts.push(label);
    if (!parts.length) parts.push(paper.status === "ready" ? "Ready" : "Indexing...");
    meta.textContent = parts.join(" · ");

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
  if (!paper) { el.textContent = "Select a paper to view"; return; }
  const score = getPaperScore(paper);
  const label = getPaperLabel(paper);
  const parts = [getPaperTitle(paper)];
  if (score !== null) parts.push(`${formatScore(score)}/10`);
  if (label) parts.push(label);
  el.textContent = parts.join(" · ");
}

/* ── INSIGHTS TAB ─────────────────────────────────────────────────────────── */

function renderInsights(paper) {
  const panel = document.getElementById("insightsContent");
  if (!panel) return;
  clearElement(panel);

  if (!paper) {
    panel.appendChild(makeComingSoonBox("📄", "No Paper Selected",
      "Upload or select a paper from the sidebar to view its difficulty analysis."));
    return;
  }

  const analysis = paper.analysis;
  if (!analysis) {
    panel.appendChild(makeComingSoonBox("⏳", "Analyzing...",
      "Difficulty analysis is being computed. Please wait."));
    return;
  }

  const score  = getPaperScore(paper);
  const label  = getPaperLabel(paper);
  const scores    = analysis.scores    || {};
  const breakdown = analysis.breakdown || {};

  const labelColors = { Easy: "var(--green)", Medium: "var(--amber)", Hard: "var(--red)" };
  const labelColor  = labelColors[label] || "var(--accent)";

  function makeBar(value, max = 10) {
    const pct  = Math.round((value / max) * 100);
    const wrap = document.createElement("div");
    wrap.style.cssText = "background:var(--surface2);border-radius:99px;height:6px;width:100%;margin-top:4px;";
    const fill = document.createElement("div");
    fill.style.cssText = `height:6px;border-radius:99px;width:${pct}%;background:var(--accent);transition:width 0.4s;`;
    wrap.appendChild(fill);
    return wrap;
  }

  /* hero */
  const hero = document.createElement("div");
  hero.style.cssText = `background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius-lg);padding:24px;margin-bottom:16px;
    display:flex;align-items:center;justify-content:space-between;`;

  const heroLeft = document.createElement("div");
  heroLeft.innerHTML = `
    <div style="font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">Difficulty Score</div>
    <div style="font-size:42px;font-weight:700;color:var(--text);line-height:1;">
      ${formatScore(score) ?? "N/A"}<span style="font-size:18px;color:var(--text2);"> / 10</span>
    </div>
    <div style="margin-top:10px;">
      <span style="background:${labelColor}20;color:${labelColor};border:1px solid ${labelColor}40;
        padding:4px 12px;border-radius:99px;font-size:12px;font-weight:600;">${label || "Unknown"}</span>
    </div>`;

  const pct = score !== null ? Math.round((score / 10) * 100) : 0;
  const circ   = 2 * Math.PI * 36;
  const offset = circ - (pct / 100) * circ;
  const heroRight = document.createElement("div");
  heroRight.innerHTML = `
    <svg width="90" height="90" viewBox="0 0 90 90">
      <circle cx="45" cy="45" r="36" fill="none" stroke="var(--surface2)" stroke-width="8"/>
      <circle cx="45" cy="45" r="36" fill="none" stroke="var(--accent)" stroke-width="8"
        stroke-dasharray="${circ.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
        stroke-linecap="round" transform="rotate(-90 45 45)" style="transition:stroke-dashoffset 0.6s;"/>
      <text x="45" y="50" text-anchor="middle" font-size="16" font-weight="700" fill="var(--text)">${pct}%</text>
    </svg>`;

  hero.appendChild(heroLeft);
  hero.appendChild(heroRight);
  panel.appendChild(hero);

  /* component scores */
  const components = [
    { key: "readability",     label: "Readability",     weight: "10%", icon: "📖" },
    { key: "uncommon_words",  label: "Uncommon Words",  weight: "10%", icon: "🔤" },
    { key: "technical_terms", label: "Technical Terms", weight: "10%", icon: "🔬" },
    { key: "llm_perception",  label: "LLM Perception",  weight: "70%", icon: "🤖" },
  ];

  const compCard = document.createElement("div");
  compCard.style.cssText = `background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius-lg);padding:18px;margin-bottom:16px;`;
  const compTitle = document.createElement("div");
  compTitle.style.cssText = "font-size:13px;font-weight:600;margin-bottom:16px;color:var(--text);";
  compTitle.textContent = "Component Scores";
  compCard.appendChild(compTitle);

  components.forEach(({ key, label: lbl, weight, icon }) => {
    const val        = scores[key];
    const displayVal = val !== undefined ? Number(val).toFixed(1) : "N/A";
    const row        = document.createElement("div");
    row.style.cssText = "margin-bottom:14px;";
    row.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
        <span style="font-size:12px;color:var(--text2);">
          ${icon} ${lbl} <span style="color:var(--text3);font-size:10px;">(weight ${weight})</span>
        </span>
        <span style="font-size:12px;font-weight:600;color:var(--text);">${displayVal} / 10</span>
      </div>`;
    if (val !== undefined) row.appendChild(makeBar(Number(val)));
    compCard.appendChild(row);
  });
  panel.appendChild(compCard);

  /* paper stats */
  const statsCard = document.createElement("div");
  statsCard.style.cssText = `background:var(--surface);border:1px solid var(--border);
    border-radius:var(--radius-lg);padding:18px;`;
  const statsTitle = document.createElement("div");
  statsTitle.style.cssText = "font-size:13px;font-weight:600;margin-bottom:14px;color:var(--text);";
  statsTitle.textContent = "Paper Statistics";
  statsCard.appendChild(statsTitle);

  const stats = [
    ["Total Sentences",      breakdown.total_sentences    ?? "N/A"],
    ["Total Words",          breakdown.total_words         ?? "N/A"],
    ["Uncommon Word %",      breakdown.uncommon_word_pct  != null ? `${breakdown.uncommon_word_pct}%`  : "N/A"],
    ["Technical Term %",     breakdown.technical_term_pct != null ? `${breakdown.technical_term_pct}%` : "N/A"],
    ["Flesch-Kincaid Grade", breakdown.flesch_kincaid_grade ?? "N/A"],
    ["Flesch Reading Ease",  breakdown.flesch_reading_ease  ?? "N/A"],
  ];

  const grid = document.createElement("div");
  grid.style.cssText = "display:grid;grid-template-columns:1fr 1fr;gap:10px;";
  stats.forEach(([statLabel, statVal]) => {
    const cell = document.createElement("div");
    cell.style.cssText = "background:var(--surface2);border-radius:var(--radius);padding:10px 12px;";
    cell.innerHTML = `
      <div style="font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:0.4px;">${statLabel}</div>
      <div style="font-size:15px;font-weight:600;color:var(--text);margin-top:2px;">${statVal}</div>`;
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
    panel.appendChild(makeComingSoonBox("⚠️", "No Prerequisites Found",
      "The model returned an empty response. Try again."));
    return;
  }

  /* info banner */
  const banner = document.createElement("div");
  banner.style.cssText = `background:var(--accent-soft);border:1px solid var(--accent-border);
    border-radius:var(--radius-lg);padding:14px 18px;margin-bottom:16px;
    display:flex;align-items:center;gap:10px;`;
  banner.innerHTML = `
    <span style="font-size:20px;">🎓</span>
    <div>
      <div style="font-size:13px;font-weight:600;color:var(--accent);">Learning Roadmap</div>
      <div style="font-size:11px;color:var(--text2);margin-top:2px;">
        Minimum prerequisites to fully understand this paper — fundamental to advanced.
      </div>
    </div>`;
  panel.appendChild(banner);

  /* parse Gemini numbered list */
  const lines = text.trim().split("\n").filter(l => l.trim());
  const items = [];
  lines.forEach(line => {
    const m = line.match(/^\s*(\d+)[.)]\s*(.+)/);
    if (!m) return;
    const content  = m[2].trim();
    const colonIdx = content.indexOf(":");
    items.push(colonIdx !== -1
      ? { number: m[1], concept: content.slice(0, colonIdx).trim(), explanation: content.slice(colonIdx + 1).trim() }
      : { number: m[1], concept: content, explanation: "" }
    );
  });

  if (!items.length) {
    /* fallback: raw text */
    const raw = document.createElement("div");
    raw.style.cssText = `background:var(--surface);border:1px solid var(--border);
      border-radius:var(--radius-lg);padding:18px;white-space:pre-wrap;
      font-size:12.5px;color:var(--text2);line-height:1.8;`;
    raw.textContent = text;
    panel.appendChild(raw);
    return;
  }

  items.forEach((item, index) => {
    const card = document.createElement("div");
    card.style.cssText = `background:var(--surface);border:1px solid var(--border);
      border-radius:var(--radius-lg);padding:14px 16px;margin-bottom:10px;
      display:flex;align-items:flex-start;gap:14px;
      transition:border-color 0.15s,box-shadow 0.15s;`;

    const progressColor = index < items.length * 0.33
      ? "var(--green)"
      : index < items.length * 0.66
      ? "var(--amber)"
      : "var(--red)";
    card.style.borderLeft = `3px solid ${progressColor}`;

    card.addEventListener("mouseenter", () => {
      card.style.borderColor = "var(--accent-border)";
      card.style.boxShadow   = "var(--shadow-sm)";
    });
    card.addEventListener("mouseleave", () => {
      card.style.borderColor = "var(--border)";
      card.style.boxShadow   = "none";
    });

    const badge = document.createElement("div");
    badge.style.cssText = `min-width:28px;height:28px;border-radius:50%;
      background:var(--accent);color:white;
      display:flex;align-items:center;justify-content:center;
      font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px;`;
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

  /* legend */
  const legend = document.createElement("div");
  legend.style.cssText = "display:flex;gap:16px;margin-top:6px;padding:10px 4px;";
  legend.innerHTML = `
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;">
      <span style="width:10px;height:10px;border-radius:2px;background:var(--green);display:inline-block;"></span>Foundational
    </span>
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;">
      <span style="width:10px;height:10px;border-radius:2px;background:var(--amber);display:inline-block;"></span>Intermediate
    </span>
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;">
      <span style="width:10px;height:10px;border-radius:2px;background:var(--red);display:inline-block;"></span>Advanced
    </span>`;
  panel.appendChild(legend);
}

/* ── SUMMARY coming soon ──────────────────────────────────────────────────── */

function renderSummaryComingSoon() {
  const panel = document.getElementById("summaryAccordion");
  if (!panel) return;
  clearElement(panel);
  panel.appendChild(makeComingSoonBox(
    "📝",
    "Summary — Coming Soon",
    "The AI-powered paper summary feature is currently under development.<br>It will automatically generate a concise summary of any uploaded research paper.",
    "In Development"
  ));
}

/* ── COMPARISON coming soon ───────────────────────────────────────────────── */

function renderComparisonComingSoon() {
  const panel = document.getElementById("comparisonContent");
  if (!panel) return;
  clearElement(panel);
  panel.appendChild(makeComingSoonBox(
    "⚖️",
    "Comparison — Coming Soon",
    "The multi-paper comparison feature is currently under development.<br>It will let you compare difficulty scores and insights across multiple papers side by side.",
    "In Development"
  ));
}

/* ── Tab switching ────────────────────────────────────────────────────────── */

function switchTab(name) {
  const validTabs = ["chat", "summary", "insights", "prerequisites", "comparison"];

  validTabs.forEach(tabName => {
    const tabEl   = document.getElementById(`tab-${tabName}`);
    const panelEl = document.getElementById(`panel-${tabName}`);
    if (tabEl)   tabEl.classList.toggle("active",   tabName === name);
    if (panelEl) panelEl.classList.toggle("active", tabName === name);
  });

  if (name === "summary") {
    renderSummaryComingSoon();

  } else if (name === "comparison") {
    renderComparisonComingSoon();

  } else if (name === "insights") {
    const paper = ensureActivePaper();
    if (!paper) { renderInsights(null); return; }

    const panel = document.getElementById("insightsContent");
    if (panel) {
      clearElement(panel);
      panel.appendChild(makeComingSoonBox("⏳", "Analyzing Paper...",
        "Running difficulty analysis. This may take a few seconds while Gemini evaluates the paper."));
    }

    fetchJson("/api/analyze", {
      method: "POST",
      body: JSON.stringify({ paper_path: getPaperPath(paper) }),
    })
      .then(data => {
        const analysis   = data.analysis  || {};
        const paperInfo  = data.paper     || paper;
        const updated    = { ...paper, ...paperInfo, analysis, status: "ready" };
        setPaperState(updated);
        renderPapers();
        updatePdfHeader(updated);
        renderInsights(updated);
      })
      .catch(error => {
        const panel = document.getElementById("insightsContent");
        if (panel) {
          clearElement(panel);
          panel.appendChild(makeComingSoonBox("❌", "Analysis Failed",
            error.message || "Could not run difficulty analysis. Check your API key and try again."));
        }
      });

  } else if (name === "prerequisites") {
    const paper = ensureActivePaper();
    if (!paper) {
      const panel = document.getElementById("prerequisitesContent");
      if (panel) {
        clearElement(panel);
        panel.appendChild(makeComingSoonBox("📚", "No Paper Selected",
          "Upload or select a paper to extract its prerequisite knowledge roadmap."));
      }
      return;
    }

    const panel = document.getElementById("prerequisitesContent");
    if (panel) {
      clearElement(panel);
      panel.appendChild(makeComingSoonBox("⏳", "Extracting Prerequisites...",
        "Gemini is analyzing the paper and building a learning roadmap. This may take 10–20 seconds."));
    }

    fetchJson("/api/prerequisites", {
      method: "POST",
      body: JSON.stringify({ paper_path: getPaperPath(paper) }),
    })
      .then(data => { renderPrerequisites(data.prerequisites || ""); })
      .catch(error => {
        const panel = document.getElementById("prerequisitesContent");
        if (panel) {
          clearElement(panel);
          panel.appendChild(makeComingSoonBox("❌", "Extraction Failed",
            error.message || "Could not extract prerequisites. Check your API key and try again."));
        }
      });
  }
}

/* ── Paper loading ────────────────────────────────────────────────────────── */

async function loadPapers() {
  const data   = await fetchJson("/api/papers", { method: "GET" });
  const papers = Array.isArray(data.papers) ? data.papers : [];

  state.papers = papers.map(p => ({ ...p, active: false, status: "ready" }));

  const savedId = localStorage.getItem(STORAGE_KEYS.activePaperId);
  if (savedId && state.papers.some(p => getPaperId(p) === savedId)) {
    state.activePaperId = savedId;
  } else if (state.papers.length > 0) {
    state.activePaperId = getPaperId(state.papers[0]);
  } else {
    state.activePaperId = null;
  }

  state.papers = state.papers.map(p => ({
    ...p, active: getPaperId(p) === state.activePaperId,
  }));

  renderPapers();
  updatePdfHeader(ensureActivePaper());
}

async function selectPaper(paperId) {
  setActivePaper(paperId);

  // If a content tab is active, refresh it for the new paper
  const activeTab = document.querySelector(".tab.active");
  if (activeTab) {
    const name = activeTab.id.replace("tab-", "");
    if (["insights", "prerequisites"].includes(name)) switchTab(name);
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
      showToast(`Uploading ${file.name}...`);
      const response = await fetch(apiUrl("/api/upload"), { method: "POST", body: formData });
      const text     = await response.text();
      let data = {};
      if (text) { try { data = JSON.parse(text); } catch { data = {}; } }
      if (!response.ok) throw new Error(data.error || "Upload failed");

      const paper    = data.paper    || {};
      const analysis = data.analysis || {};
      const newPaper = { ...paper, analysis, status: "ready", active: true };

      state.papers = [newPaper, ...state.papers.map(p => ({ ...p, active: false }))];
      state.activePaperId = getPaperId(newPaper);
      localStorage.setItem(STORAGE_KEYS.activePaperId, state.activePaperId);

      renderPapers();
      updatePdfHeader(newPaper);
      showToast(`Uploaded: ${file.name}`);
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

  const userMsg = document.createElement("div");
  userMsg.className = "msg user";
  const body   = document.createElement("div");  body.className = "msg-body";
  const bubble = document.createElement("div");  bubble.className = "msg-bubble";
  bubble.textContent = message;
  body.appendChild(bubble);
  const avatar = document.createElement("div");  avatar.className = "msg-avatar";
  avatar.textContent = "U";
  userMsg.appendChild(body);
  userMsg.appendChild(avatar);
  chatArea.insertBefore(userMsg, thinkEl);

  input.value = "";
  input.style.height = "auto";
  thinkEl.style.display = "flex";
  chatArea.scrollTop = chatArea.scrollHeight;
  state.thinking = true;

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, paper_path: getPaperPath(paper) }),
    });
    thinkEl.style.display = "none";

    const aiMsg    = document.createElement("div");   aiMsg.className = "msg assistant";
    const aiAvatar = document.createElement("div");   aiAvatar.className = "msg-avatar";
    aiAvatar.textContent = "PM";
    const aiBody   = document.createElement("div");   aiBody.className = "msg-body";
    const aiBubble = document.createElement("div");   aiBubble.className = "msg-bubble";
    aiBubble.textContent = data.reply || "No response returned.";

    const actions    = document.createElement("div");   actions.className = "msg-actions";
    const copyButton = document.createElement("button"); copyButton.className = "msg-action-btn";
    copyButton.type = "button"; copyButton.textContent = "Copy";
    copyButton.addEventListener("click", () => copyText(data.reply || ""));
    actions.appendChild(copyButton);

    aiBody.appendChild(aiBubble);
    aiBody.appendChild(actions);
    aiMsg.appendChild(aiAvatar);
    aiMsg.appendChild(aiBody);
    chatArea.insertBefore(aiMsg, thinkEl);
    chatArea.scrollTop = chatArea.scrollHeight;
  } catch (error) {
    thinkEl.style.display = "none";
    const aiMsg    = document.createElement("div");   aiMsg.className = "msg assistant";
    const aiAvatar = document.createElement("div");   aiAvatar.className = "msg-avatar";
    aiAvatar.textContent = "PM";
    const aiBody   = document.createElement("div");   aiBody.className = "msg-body";
    const aiBubble = document.createElement("div");   aiBubble.className = "msg-bubble";
    aiBubble.textContent = error.message || "Error: Could not get response";
    aiBody.appendChild(aiBubble);
    aiMsg.appendChild(aiAvatar);
    aiMsg.appendChild(aiBody);
    chatArea.insertBefore(aiMsg, thinkEl);
    chatArea.scrollTop = chatArea.scrollHeight;
  } finally {
    state.thinking = false;
  }
}

function handleKey(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    void sendMessage();
  }
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
    navigator.clipboard.writeText(text)
      .then(() => showToast("Copied!"))
      .catch(() => showToast("Failed to copy"));
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
  showToast("Copied!");
}

function setupResizeHandle() {
  const handle   = document.getElementById("resizeHandle");
  const pdfPanel = document.getElementById("pdfPanel");
  if (!handle || !pdfPanel) return;

  let isResizing = false, startX = 0, startWidth = 0;

  handle.addEventListener("mousedown", e => {
    isResizing = true; startX = e.clientX; startWidth = pdfPanel.offsetWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", e => {
    if (!isResizing) return;
    const newWidth = Math.max(280, Math.min(700, startWidth + (startX - e.clientX)));
    pdfPanel.style.width = pdfPanel.style.minWidth = `${newWidth}px`;
  });
  document.addEventListener("mouseup", () => {
    if (!isResizing) return;
    isResizing = false;
    document.body.style.cursor = document.body.style.userSelect = "";
    localStorage.setItem(STORAGE_KEYS.pdfPanelWidth, String(pdfPanel.offsetWidth));
  });

  const saved = localStorage.getItem(STORAGE_KEYS.pdfPanelWidth);
  if (saved) pdfPanel.style.width = pdfPanel.style.minWidth = `${saved}px`;
}

function setupUiBindings() {
  const fileInput  = document.getElementById("fileInput");
  const dropZone   = document.getElementById("dropZone");
  const pdfClose   = document.getElementById("pdfCloseBtn");
  const compareBtn = document.querySelector(".compare-btn");

  if (fileInput) {
    fileInput.addEventListener("change", e => {
      void handleFiles(Array.from(e.target.files || []));
      e.target.value = "";
    });
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

  if (compareBtn) compareBtn.addEventListener("click", () => switchTab("comparison"));

  if (pdfClose) {
    pdfClose.addEventListener("click", () => {
      const pdfPanel     = document.getElementById("pdfPanel");
      const resizeHandle = document.getElementById("resizeHandle");
      if (pdfPanel)     pdfPanel.style.display     = "none";
      if (resizeHandle) resizeHandle.style.display = "none";
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

window.toggleDark  = toggleDark;
window.switchTab   = switchTab;
window.handleKey   = handleKey;
window.sendMessage = sendMessage;
window.changePage  = changePage;