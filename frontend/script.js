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
  _tabCache:      {},   // paperId -> { insights: data, prerequisites: text }
  _explainCache:  {},   // "paperId::term_lowercase" -> explain result dict
  _pollingTimers: {},   // collectionName -> intervalId
  _chatHistory:   {},   // paperId -> [{ role: "user"|"assistant", text: string }]
  _chatLoaded:    {},   // paperId -> true once history has been fetched from server
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
  el.className   = "toast";
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

function clearElement(el) { while (el.firstChild) el.removeChild(el.firstChild); }

/* ── Tab cache ────────────────────────────────────────────────────────────── */

function getCachedTab(paperId, tabName) {
  return state._tabCache[paperId]?.[tabName] ?? null;
}

function setCachedTab(paperId, tabName, data) {
  if (!state._tabCache[paperId]) state._tabCache[paperId] = {};
  state._tabCache[paperId][tabName] = data;
}

/* ── Chat history (per paper, backed by server disk cache) ──────────────── */

function getChatHistory(paperId) {
  if (!state._chatHistory[paperId]) state._chatHistory[paperId] = [];
  return state._chatHistory[paperId];
}

function pushChatMessage(paperId, role, text) {
  getChatHistory(paperId).push({ role, text });
}

/**
 * Rebuilds the #chatArea DOM from the in-memory history of the given paper.
 */
function renderChatHistory(paperId) {
  const chatArea = document.getElementById("chatArea");
  const thinkEl  = document.getElementById("thinkingMsg");
  if (!chatArea || !thinkEl) return;

  Array.from(chatArea.children).forEach(child => {
    if (child !== thinkEl) chatArea.removeChild(child);
  });
  thinkEl.style.display = "none";

  const history = paperId ? getChatHistory(paperId) : [];

  history.forEach(({ role, text }) => {
    if (role === "user") {
      const userMsg = document.createElement("div"); userMsg.className = "msg user";
      const body    = document.createElement("div"); body.className   = "msg-body";
      const bubble  = document.createElement("div"); bubble.className = "msg-bubble";
      bubble.textContent = text;
      body.appendChild(bubble);
      const avatar = document.createElement("div"); avatar.className = "msg-avatar"; avatar.textContent = "U";
      userMsg.appendChild(body); userMsg.appendChild(avatar);
      chatArea.insertBefore(userMsg, thinkEl);
    } else {
      const aiMsg    = document.createElement("div"); aiMsg.className    = "msg assistant";
      const aiAvatar = document.createElement("div"); aiAvatar.className = "msg-avatar"; aiAvatar.textContent = "PM";
      const aiBody   = document.createElement("div"); aiBody.className   = "msg-body";
      const aiBubble = document.createElement("div"); aiBubble.className = "msg-bubble";
      aiBubble.textContent = text;
      const actions  = document.createElement("div"); actions.className = "msg-actions";
      const copyBtn  = document.createElement("button"); copyBtn.className = "msg-action-btn"; copyBtn.type = "button"; copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => copyText(text));
      actions.appendChild(copyBtn);
      aiBody.appendChild(aiBubble); aiBody.appendChild(actions);
      aiMsg.appendChild(aiAvatar); aiMsg.appendChild(aiBody);
      chatArea.insertBefore(aiMsg, thinkEl);
    }
  });

  chatArea.scrollTop = chatArea.scrollHeight;
}

/**
 * Loads chat history for a paper from the server (if not already loaded),
 * stores it locally, then renders it. This is what makes chat survive
 * page refreshes and server restarts.
 */
async function loadAndRenderChatHistory(paper) {
  if (!paper) { renderChatHistory(null); return; }
  const paperId = getPaperId(paper);

  if (state._chatLoaded[paperId]) {
    renderChatHistory(paperId);
    return;
  }

  // Show nothing while fetching (usually instant — it's a small JSON file)
  renderChatHistory(null);

  try {
    const data = await fetchJson(`/api/chat-history/${getPaperPath(paper)}`, { method: "GET" });
    state._chatHistory[paperId] = Array.isArray(data.history) ? data.history : [];
  } catch {
    state._chatHistory[paperId] = [];
  }
  state._chatLoaded[paperId] = true;
  renderChatHistory(paperId);
}

/* ── Progress bar ─────────────────────────────────────────────────────────── */

function showProgressBar(pct, message) {
  let bar = document.getElementById("indexProgressBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id        = "indexProgressBar";
    bar.className = "index-progress-bar";
    bar.innerHTML = `<div class="ipb-track"><div class="ipb-fill" id="ipbFill"></div></div><div class="ipb-label" id="ipbLabel"></div>`;
    const list = document.getElementById("paperList");
    if (list && list.parentNode) list.parentNode.insertBefore(bar, list);
  }
  bar.style.display = "block";
  const fill = document.getElementById("ipbFill");
  const label = document.getElementById("ipbLabel");
  if (fill)  fill.style.width   = `${Math.min(100, Math.max(0, pct))}%`;
  if (label) label.textContent  = message || "";
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

      state.papers = state.papers.map(p =>
        getPaperId(p) !== paperId ? p
          : { ...p, indexStatus: status, indexPct: pct, indexStep: step, indexMessage: message }
      );
      renderPapers();

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
    } catch { /* network blip */ }
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
    empty.textContent   = "No papers yet — upload one to get started";
    list.appendChild(empty);
    return;
  }

  state.papers.forEach(paper => {
    const paperId   = getPaperId(paper);
    const idxStatus = paper.indexStatus || "ready";
    const pct       = paper.indexPct ?? 100;

    const item = document.createElement("div");
    item.className = `paper-item${paper.active ? " active" : ""}`;

    const dot  = document.createElement("div");
    dot.className = idxStatus === "indexing" ? "paper-dot indexing"
                  : idxStatus === "error"    ? "paper-dot error"
                  : "paper-dot ready";

    const info  = document.createElement("div");
    info.className = "paper-info";

    const title = document.createElement("div");
    title.className   = "paper-title";
    title.textContent = getPaperTitle(paper);

    const meta = document.createElement("div");
    meta.className = "paper-meta";

    if (idxStatus === "indexing") {
      meta.innerHTML = `<span style="color:var(--amber);">${paper.indexStep || "Indexing..."}</span>
        <div class="sidebar-mini-bar"><div class="sidebar-mini-fill" style="width:${pct}%"></div></div>`;
    } else if (idxStatus === "error") {
      meta.textContent = "Index failed";
      meta.style.color = "var(--red)";
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
  if (el) el.textContent = paper ? getPaperTitle(paper) : "Select a paper to view";
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

  if (!paper) { panel.appendChild(makeComingSoonBox("📄", "No Paper Selected", "Upload or select a paper.")); return; }
  const analysis = paper.analysis;
  if (!analysis || !analysis.final_score) { panel.appendChild(makeComingSoonBox("⏳", "Analyzing...", "Computing difficulty analysis.")); return; }

  const score  = getPaperScore(paper);
  const label  = getPaperLabel(paper);
  const scores = analysis.scores    || {};
  const brk    = analysis.breakdown || {};
  const lc     = { Easy: "var(--green)", Medium: "var(--amber)", Hard: "var(--red)" };
  const labelColor = lc[label] || "var(--accent)";

  function makeBar(v, max = 10) {
    const pct = Math.round((v / max) * 100);
    const w   = document.createElement("div");
    w.style.cssText = "background:var(--surface2);border-radius:99px;height:6px;width:100%;margin-top:4px;";
    const f = document.createElement("div");
    f.style.cssText = `height:6px;border-radius:99px;width:${pct}%;background:var(--accent);transition:width 0.4s;`;
    w.appendChild(f); return w;
  }

  const hero   = document.createElement("div");
  const pct    = score !== null ? Math.round((score / 10) * 100) : 0;
  const circ   = 2 * Math.PI * 36;
  const offset = circ - (pct / 100) * circ;
  hero.style.cssText = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:24px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;";
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
  ct.style.cssText   = "font-size:13px;font-weight:600;margin-bottom:16px;color:var(--text);";
  ct.textContent     = "Component Scores";
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
  st.textContent   = "Paper Statistics";
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

function explainPrerequisite(concept) {
  switchTab("explain");

  setTimeout(() => {
    const input = document.getElementById("explainInput");
    if (input) {
      input.value = concept;
      input.style.transition = "box-shadow 0.3s";
      input.style.boxShadow  = "0 0 0 3px rgba(45, 91, 227, 0.35)";
      setTimeout(() => { input.style.boxShadow = ""; }, 1200);
    }
    void explainTerm();
  }, 80);
}

function renderPrerequisites(text) {
  const panel = document.getElementById("prerequisitesContent");
  if (!panel) return;
  clearElement(panel);

  if (!text || !text.trim()) {
    panel.appendChild(makeComingSoonBox("⚠️", "No Prerequisites Found", "The model returned an empty response.")); return;
  }

  const banner = document.createElement("div");
  banner.style.cssText = "background:var(--accent-soft);border:1px solid var(--accent-border);border-radius:var(--radius-lg);padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:10px;";
  banner.innerHTML = `
    <span style="font-size:20px;">🎓</span>
    <div>
      <div style="font-size:13px;font-weight:600;color:var(--accent);">Learning Roadmap</div>
      <div style="font-size:11px;color:var(--text2);margin-top:2px;">
        Click any topic to get an instant explanation in simple words.
      </div>
    </div>`;
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
    const card          = document.createElement("div");
    const progressColor = idx < items.length * 0.33 ? "var(--green)" : idx < items.length * 0.66 ? "var(--amber)" : "var(--red)";

    card.style.cssText  = [
      `background:var(--surface)`,
      `border:1px solid var(--border)`,
      `border-left:3px solid ${progressColor}`,
      `border-radius:var(--radius-lg)`,
      `padding:14px 16px`,
      `margin-bottom:10px`,
      `display:flex`,
      `align-items:flex-start`,
      `gap:14px`,
      `cursor:pointer`,
      `transition:background 0.15s, box-shadow 0.15s, transform 0.1s`,
    ].join(";");

    card.addEventListener("mouseenter", () => {
      card.style.background  = "var(--accent-soft)";
      card.style.boxShadow   = "0 2px 10px rgba(45,91,227,0.12)";
      card.style.transform   = "translateY(-1px)";
      card.style.borderColor = "var(--accent-border)";
    });
    card.addEventListener("mouseleave", () => {
      card.style.background  = "var(--surface)";
      card.style.boxShadow   = "";
      card.style.transform   = "";
      card.style.borderColor = "";
    });

    card.addEventListener("click", () => {
      explainPrerequisite(item.concept);
    });

    const badge = document.createElement("div");
    badge.style.cssText = "min-width:28px;height:28px;border-radius:50%;background:var(--accent);color:white;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px;";
    badge.textContent = item.number;

    const content    = document.createElement("div");
    content.style.cssText = "flex:1;min-width:0;";

    const conceptRow = document.createElement("div");
    conceptRow.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:8px;";

    const conceptEl  = document.createElement("div");
    conceptEl.style.cssText = "font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px;";
    conceptEl.textContent   = item.concept;

    const chip = document.createElement("span");
    chip.style.cssText = [
      "font-size:10px",
      "color:var(--accent)",
      "background:var(--accent-soft)",
      "border:1px solid var(--accent-border)",
      "border-radius:99px",
      "padding:2px 8px",
      "white-space:nowrap",
      "flex-shrink:0",
      "opacity:0",
      "transition:opacity 0.2s",
    ].join(";");
    chip.textContent = "Explain →";

    card.addEventListener("mouseenter", () => { chip.style.opacity = "1"; });
    card.addEventListener("mouseleave", () => { chip.style.opacity = "0"; });

    conceptRow.appendChild(conceptEl);
    conceptRow.appendChild(chip);
    content.appendChild(conceptRow);

    if (item.explanation) {
      const explEl = document.createElement("div");
      explEl.style.cssText = "font-size:12px;color:var(--text2);line-height:1.6;";
      explEl.textContent   = item.explanation;
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
    <span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--red);display:inline-block;"></span>Advanced</span>
    <span style="font-size:11px;color:var(--text3);margin-left:auto;display:flex;align-items:center;gap:4px;">
      <span style="font-size:13px;">👆</span> Click any topic to explain it
    </span>`;
  panel.appendChild(legend);
}

/* ── EXPLAIN TAB ──────────────────────────────────────────────────────────── */

function _explainCacheKey(paperId, term) {
  return `${paperId}::${term.toLowerCase().trim()}`;
}

function getExplainCache(paperId, term) {
  return state._explainCache[_explainCacheKey(paperId, term)] ?? null;
}

function setExplainCache(paperId, term, data) {
  state._explainCache[_explainCacheKey(paperId, term)] = data;
}

const _EXPLAIN_STEPS = [
  [15,  "Retrieving relevant sections from paper…",  400],
  [35,  "Sending context to Gemini…",                1200],
  [55,  "Gemini is reading the paper…",              3000],
  [75,  "Generating explanation…",                   6000],
  [90,  "Preparing your answer…",                    10000],
  [95,  "Waiting for Gemini response…",              0],
];

function makeExplainLoadingCard(term) {
  if (!document.getElementById("explainAnimStyles")) {
    const style = document.createElement("style");
    style.id = "explainAnimStyles";
    style.textContent = `
      @keyframes shimmer {
        0%,100% { opacity:0.35; }
        50%      { opacity:0.75; }
      }
      #explainProgressFill {
        transition: width 0.6s ease;
      }`;
    document.head.appendChild(style);
  }

  const wrap = document.createElement("div");
  wrap.id = "explainLoadingCard";
  wrap.style.cssText = [
    "background:var(--surface)",
    "border:1px solid var(--border)",
    "border-radius:var(--radius-lg)",
    "padding:28px 24px",
    "margin-top:8px",
  ].join(";");

  wrap.innerHTML = `
    <div style="margin-bottom:18px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
        <div style="font-size:13px;font-weight:600;color:var(--text);">
          Explaining <span style="color:var(--accent);">"${term}"</span>
        </div>
        <div id="explainProgressPct" style="font-size:12px;font-weight:600;color:var(--accent);">0%</div>
      </div>
      <div style="background:var(--surface2);border-radius:99px;height:7px;width:100%;overflow:hidden;">
        <div id="explainProgressFill"
             style="height:7px;border-radius:99px;background:var(--accent);width:0%;"></div>
      </div>
      <div id="explainProgressLabel"
           style="font-size:11px;color:var(--text3);margin-top:8px;">
        Starting…
      </div>
    </div>

    <div style="display:flex;flex-direction:column;gap:10px;">
      ${["📄 From This Paper", "💡 In Simple Words", "🌍 Real-World Example"].map(label => `
        <div style="border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;opacity:0.5;">
          <div style="font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:9px;">${label}</div>
          <div style="background:var(--surface2);border-radius:5px;height:9px;width:82%;margin-bottom:6px;animation:shimmer 1.6s ease-in-out infinite;"></div>
          <div style="background:var(--surface2);border-radius:5px;height:9px;width:65%;margin-bottom:6px;animation:shimmer 1.6s ease-in-out infinite 0.2s;"></div>
          <div style="background:var(--surface2);border-radius:5px;height:9px;width:50%;animation:shimmer 1.6s ease-in-out infinite 0.4s;"></div>
        </div>`).join("")}
    </div>`;

  return wrap;
}

function startExplainProgress() {
  let currentStep = 0;
  let stopped = false;

  function setProgress(pct, label) {
    const fill  = document.getElementById("explainProgressFill");
    const pctEl = document.getElementById("explainProgressPct");
    const lblEl = document.getElementById("explainProgressLabel");
    if (fill)  fill.style.width    = `${pct}%`;
    if (pctEl) pctEl.textContent   = `${pct}%`;
    if (lblEl) lblEl.textContent   = label;
  }

  function advance() {
    if (stopped || currentStep >= _EXPLAIN_STEPS.length) return;
    const [pct, label, delay] = _EXPLAIN_STEPS[currentStep];
    setProgress(pct, label);
    currentStep++;
    if (currentStep < _EXPLAIN_STEPS.length - 1 && delay > 0) {
      setTimeout(advance, delay);
    }
  }

  advance();

  return function stop() {
    stopped = true;
    setProgress(100, "Done!");
  };
}

async function explainTerm() {
  const input = document.getElementById("explainInput");
  const panel = document.getElementById("explainContent");
  const paper = ensureActivePaper();
  if (!input || !panel) return;
  const term = input.value.trim();
  if (!term) { showToast("Please type a term to explain"); return; }
  if (!paper) { showToast("Upload or select a paper first"); return; }
  if ((paper.indexStatus || "ready") === "indexing") { showToast("Paper is still being indexed."); return; }

  const paperId = getPaperId(paper);

  const cached = getExplainCache(paperId, term);
  if (cached) {
    renderExplainResult(cached);
    return;
  }

  clearElement(panel);
  panel.appendChild(makeExplainLoadingCard(term));
  const stopProgress = startExplainProgress();

  try {
    const data = await fetchJson("/api/explain", {
      method: "POST",
      body: JSON.stringify({ term, paper_path: getPaperPath(paper) }),
    });
    stopProgress();
    setExplainCache(paperId, term, data);
    renderExplainResult(data);
  } catch (error) {
    stopProgress();
    clearElement(panel);
    panel.appendChild(makeComingSoonBox("❌", "Explanation Failed", error.message || "Check your API key."));
  }
}

function renderExplainResult(data) {
  const panel = document.getElementById("explainContent");
  if (!panel) return;
  clearElement(panel);

  const {
    term,
    from_paper,
    simple_explanation,
    real_world_example,
    chunks_used,
    found_in_paper,
  } = data;

  const badge = document.createElement("div");
  badge.style.cssText = [
    "display:inline-flex",
    "align-items:center",
    "gap:6px",
    "padding:4px 12px",
    "border-radius:99px",
    "font-size:11px",
    "font-weight:600",
    "margin-bottom:16px",
    found_in_paper
      ? "background:var(--green-soft);color:var(--green);border:1px solid var(--green);"
      : "background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber);",
  ].join(";");
  badge.textContent = found_in_paper
    ? `Found in paper (${chunks_used} section${chunks_used !== 1 ? "s" : ""})`
    : "Not in paper — using general knowledge";
  panel.appendChild(badge);

  const heading = document.createElement("div");
  heading.style.cssText = "font-size:22px;font-weight:700;color:var(--text);margin-bottom:20px;letter-spacing:-0.3px;";
  heading.textContent   = term.charAt(0).toUpperCase() + term.slice(1);
  panel.appendChild(heading);

  function makeCard(icon, title, content, accentColor) {
    const card = document.createElement("div");
    card.style.cssText = [
      "background:var(--surface)",
      "border:1px solid var(--border)",
      "border-radius:var(--radius-lg)",
      "padding:18px 20px",
      "margin-bottom:14px",
      `border-left:3px solid ${accentColor}`,
    ].join(";");
    card.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">
        <span style="font-size:16px;">${icon}</span>${title}
      </div>
      <div style="font-size:13.5px;color:var(--text);line-height:1.75;">${content}</div>`;
    return card;
  }

  panel.appendChild(makeCard("📄", "From This Paper", from_paper, "var(--accent)"));
  panel.appendChild(makeCard("💡", "In Simple Words", simple_explanation, "var(--green)"));

  if (real_world_example) {
    const exCard = document.createElement("div");
    exCard.style.cssText = [
      "background:var(--amber-soft)",
      "border:1px solid var(--amber)",
      "border-radius:var(--radius-lg)",
      "padding:18px 20px",
      "margin-bottom:14px",
      "border-left:3px solid var(--amber)",
    ].join(";");

    const exText = real_world_example.replace(/^example\s*:\s*/i, "").trim();

    exCard.innerHTML = `
      <div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--amber);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;">
        <span style="font-size:16px;">🌍</span>Real-World Example
      </div>
      <div style="display:flex;gap:10px;align-items:flex-start;">
        <span style="font-size:24px;line-height:1;flex-shrink:0;margin-top:2px;">💬</span>
        <div style="font-size:13.5px;color:var(--text);line-height:1.75;font-style:italic;">"${exText}"</div>
      </div>`;
    panel.appendChild(exCard);
  }

  const hint = document.createElement("div");
  hint.style.cssText = "font-size:11px;color:var(--text3);margin-top:4px;text-align:center;";
  hint.textContent   = "Type another term above and click Explain to look it up.";
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

/* ── Tab switching ────────────────────────────────────────────────────────── */

function switchTab(name) {
  const validTabs = ["chat", "summary", "insights", "prerequisites", "explain", "comparison"];
  validTabs.forEach(t => {
    document.getElementById(`tab-${t}`)?.classList.toggle("active", t === name);
    document.getElementById(`panel-${t}`)?.classList.toggle("active", t === name);
  });

  if (name === "summary")    { renderSummaryComingSoon(); return; }
  if (name === "comparison") { renderComparisonComingSoon(); return; }

  const paper = ensureActivePaper();

  if (name === "insights") {
    const panel   = document.getElementById("insightsContent");
    if (!paper) { renderInsights(null); return; }

    const paperId = getPaperId(paper);

    const cached = getCachedTab(paperId, "insights");
    if (cached) { renderInsights(cached); return; }

    if (paper.analysis && paper.analysis.final_score) {
      setCachedTab(paperId, "insights", paper);
      renderInsights(paper);
      return;
    }

    if ((paper.indexStatus || "ready") === "indexing") {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Indexing in progress...", "Wait for the green dot, then click Insights again.")); }
      return;
    }

    if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Analyzing paper...", "Running difficulty analysis via Gemini. This runs once and is cached forever after.")); }

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

  if (name === "prerequisites") {
    const panel = document.getElementById("prerequisitesContent");
    if (!paper) {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("📚", "No Paper Selected", "Upload or select a paper.")); }
      return;
    }

    const paperId = getPaperId(paper);

    const cached = getCachedTab(paperId, "prerequisites");
    if (cached) { renderPrerequisites(cached); return; }

    if ((paper.indexStatus || "ready") === "indexing") {
      if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Indexing in progress...", "Wait for the green dot, then click Prerequisites again.")); }
      return;
    }

    if (panel) { clearElement(panel); panel.appendChild(makeComingSoonBox("⏳", "Extracting Prerequisites...", "Gemini is building a learning roadmap. This runs once and is cached forever after.")); }

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

  /* ── EXPLAIN — just switch, don't clear existing results ─────────────── */
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

  state.papers.forEach(p => {
    if ((p.indexStatus || "ready") === "indexing") startIndexPolling(p);
  });

  renderPapers();
  updatePdfHeader(ensureActivePaper());
  await loadAndRenderChatHistory(ensureActivePaper());   // ← fetch this paper's saved chat from the server
}

async function selectPaper(paperId) {
  setActivePaper(paperId);
  await loadAndRenderChatHistory(ensureActivePaper());   // ← swap to this paper's saved chat

  const activeTab = document.querySelector(".tab.active");
  if (activeTab) {
    const name = activeTab.id.replace("tab-", "");
    if (["insights", "prerequisites"].includes(name)) switchTab(name);
  }
  const paper = ensureActivePaper();
  if (paper && (paper.indexStatus || "ready") === "indexing") {
    showProgressBar(paper.indexPct ?? 0, paper.indexMessage || paper.indexStep || "Indexing...");
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
      showToast(`Uploading ${file.name}...`);
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
      state._chatLoaded[state.activePaperId] = true;   // brand-new paper — no history to fetch
      state._chatHistory[state.activePaperId] = [];
      renderChatHistory(state.activePaperId);
      showProgressBar(5, "Starting...");
      showToast(`Uploaded ${file.name} — indexing in background...`);
      startIndexPolling(newPaper);
    } catch (error) {
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

  const paperId = getPaperId(paper);

  const userMsg  = document.createElement("div"); userMsg.className  = "msg user";
  const body     = document.createElement("div"); body.className     = "msg-body";
  const bubble   = document.createElement("div"); bubble.className   = "msg-bubble";
  bubble.textContent = message;
  body.appendChild(bubble);
  const avatar = document.createElement("div"); avatar.className = "msg-avatar"; avatar.textContent = "U";
  userMsg.appendChild(body); userMsg.appendChild(avatar);
  chatArea.insertBefore(userMsg, thinkEl);
  pushChatMessage(paperId, "user", message);   // local copy for instant render

  input.value = ""; input.style.height = "auto";
  thinkEl.style.display = "flex"; chatArea.scrollTop = chatArea.scrollHeight;
  state.thinking = true;

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, paper_path: getPaperPath(paper) }),
    });
    thinkEl.style.display = "none";

    // The backend has already persisted both messages to disk (cache/<collection>_chat.json)
    // by this point, so a refresh from here on will bring this exchange back.
    const replyText = data.reply || "No response returned.";
    pushChatMessage(paperId, "assistant", replyText);

    if (state.activePaperId === paperId) {
      const aiMsg    = document.createElement("div"); aiMsg.className    = "msg assistant";
      const aiAvatar = document.createElement("div"); aiAvatar.className = "msg-avatar"; aiAvatar.textContent = "PM";
      const aiBody   = document.createElement("div"); aiBody.className   = "msg-body";
      const aiBubble = document.createElement("div"); aiBubble.className = "msg-bubble";
      aiBubble.textContent = replyText;
      const actions  = document.createElement("div"); actions.className = "msg-actions";
      const copyBtn  = document.createElement("button"); copyBtn.className = "msg-action-btn"; copyBtn.type = "button"; copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", () => copyText(replyText));
      actions.appendChild(copyBtn);
      aiBody.appendChild(aiBubble); aiBody.appendChild(actions);
      aiMsg.appendChild(aiAvatar); aiMsg.appendChild(aiBody);
      chatArea.insertBefore(aiMsg, thinkEl); chatArea.scrollTop = chatArea.scrollHeight;
    }
  } catch (error) {
    thinkEl.style.display = "none";
    const errorText = error.message || "Error: Could not get response";
    // Note: failed requests are NOT persisted server-side (api_chat only saves on success),
    // so we only keep this in local memory for the current session.
    pushChatMessage(paperId, "assistant", errorText);

    if (state.activePaperId === paperId) {
      const aiMsg    = document.createElement("div"); aiMsg.className    = "msg assistant";
      const aiAvatar = document.createElement("div"); aiAvatar.className = "msg-avatar"; aiAvatar.textContent = "PM";
      const aiBody   = document.createElement("div"); aiBody.className   = "msg-body";
      const aiBubble = document.createElement("div"); aiBubble.className = "msg-bubble";
      aiBubble.textContent = errorText;
      aiBody.appendChild(aiBubble); aiMsg.appendChild(aiAvatar); aiMsg.appendChild(aiBody);
      chatArea.insertBefore(aiMsg, thinkEl); chatArea.scrollTop = chatArea.scrollHeight;
    }
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
    dropZone.addEventListener("dragleave", () => { dropZone.style.opacity = "1"; });
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
    showToast(error.message || "Failed to load papers");
    renderPapers();
  }
});

/* ── Global exposure ──────────────────────────────────────────────────────── */
window.toggleDark          = toggleDark;
window.switchTab           = switchTab;
window.handleKey           = handleKey;
window.sendMessage         = sendMessage;
window.changePage          = changePage;
window.explainTerm         = explainTerm;
window.handleExplainKey    = handleExplainKey;
window.logout              = logout;
window.explainPrerequisite = explainPrerequisite;