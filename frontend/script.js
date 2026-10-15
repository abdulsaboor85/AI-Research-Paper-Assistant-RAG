/* ==========================================================
   script.js - PaperInsight AI main app
   ========================================================== */

const API_BASE = "";   // same server as the page
const STORAGE = {
  dark:        "papermind_darkMode",
  pdfWidth:    "papermind_pdfPanelWidth",
  activePaper: "papermind_activePaperId",
};
const TABS = ["chat", "summary", "insights", "prerequisites", "explain", "comparison"];

const state = {
  isDark: false,
  thinking: false,
  currentPage: 1,
  totalPages: 0,
  papers: [],
  activePaperId: null,
  tabCache: {},        // { paperId: { insights, prerequisites } }
  explainCache: {},
  pollTimers: {},
  chatHistory: {},
  chatLoaded: {},
  knownTerms: [],
};

let pdfDoc = null;
let pdfZoomLevel = 1;
let fsPage = 1;
let fsZoomLevel = 1;

/* ── Small helpers ────────────────────────────────────────── */

const $ = (id) => document.getElementById(id);

function setText(id, text) {
  const el = $(id);
  if (el) el.textContent = text;
}

function clearElement(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
}

function escapeHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function showToast(message) {
  const container = $("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = "toast";
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3600);
}

async function fetchJson(path, options = {}) {
  const response = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let data = {};
  if (text) {
    try { data = JSON.parse(text); } catch { data = { raw: text }; }
  }
  if (!response.ok) throw new Error(data.error || data.message || `Request failed: ${response.status}`);
  return data;
}

function copyText(text) {
  navigator.clipboard.writeText(text)
    .then(() => showToast("Copied!"))
    .catch(() => showToast("Failed to copy"));
}

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

/** Replace the content of a panel with an icon + title + text box. */
function showBox(panelId, icon, title, text, badge) {
  const panel = $(panelId);
  if (!panel) return;
  clearElement(panel);
  panel.appendChild(makeComingSoonBox(icon, title, text, badge));
}

function makeCard(css, html) {
  const el = document.createElement("div");
  el.style.cssText = css;
  el.innerHTML = html;
  return el;
}

const CARD = "background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);";

/* ── Papers ───────────────────────────────────────────────── */

function getActivePaper() {
  return state.papers.find((p) => p.id === state.activePaperId) || state.papers[0] || null;
}

function updatePaper(updated) {
  state.papers = state.papers.map((p) =>
    p.id !== updated.id ? p : { ...p, ...updated, analysis: updated.analysis || p.analysis }
  );
}

function setActivePaper(paperId) {
  state.activePaperId = paperId;
  localStorage.setItem(STORAGE.activePaper, paperId);
  state.papers = state.papers.map((p) => ({ ...p, active: p.id === paperId }));
  renderPapers();
  const paper = getActivePaper();
  setText("pdfTitle", paper ? paper.title : "Select a paper to view");
  loadPdfInViewer(paper);
}

/* ── Chat bubbles (light markdown) ────────────────────────── */

function formatMessageText(raw) {
  if (!raw) return "";
  const bold = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  let html = "";
  let list = [];
  let listTag = null;
  let paragraph = [];

  const flushList = () => {
    if (list.length) html += `<${listTag}>${list.map((li) => `<li>${li}</li>`).join("")}</${listTag}>`;
    list = [];
    listTag = null;
  };
  const flushParagraph = () => {
    if (paragraph.length) html += `<p>${paragraph.join("<br>")}</p>`;
    paragraph = [];
  };
  const addListItem = (tag, text) => {
    flushParagraph();
    if (listTag !== tag) flushList();
    listTag = tag;
    list.push(bold(text));
  };

  for (const line of escapeHtml(raw.trim()).split("\n")) {
    const text = line.trim();
    if (!text) { flushList(); flushParagraph(); continue; }

    const heading = text.match(/^#{1,3}\s+(.*)/);
    const ordered = text.match(/^(\d+)[.)]\s+(.*)/);
    const bullet = text.match(/^[-*]\s+(.*)/);

    if (heading) {
      flushList(); flushParagraph();
      html += `<h4 class="msg-heading">${bold(heading[1])}</h4>`;
    } else if (ordered) {
      addListItem("ol", ordered[2]);
    } else if (bullet) {
      addListItem("ul", bullet[1]);
    } else {
      flushList();
      paragraph.push(bold(text));
    }
  }
  flushList(); flushParagraph();
  return html;
}

function createMessageElement(role, text) {
  const msg = document.createElement("div");

  if (role === "user") {
    msg.className = "msg user";
    msg.innerHTML = `<div class="msg-body"><div class="msg-bubble"></div></div><div class="msg-avatar">U</div>`;
    msg.querySelector(".msg-bubble").textContent = text;
    return msg;
  }

  msg.className = "msg assistant";
  msg.innerHTML = `
    <div class="msg-avatar">PM</div>
    <div class="msg-body">
      <div class="msg-bubble">${formatMessageText(text)}</div>
      <div class="msg-actions"><button type="button" class="msg-action-btn">Copy</button></div>
    </div>`;
  msg.querySelector(".msg-action-btn").addEventListener("click", () => copyText(text));
  return msg;
}

/* ══════════════════════════════════════════════════════════
   PDF VIEWER (sidebar + fullscreen share one renderer)
   ══════════════════════════════════════════════════════════ */

const PDF_PLACEHOLDER = `
  <div class="pdf-placeholder">
    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2z"/>
    </svg>
    <p>Upload a paper to preview</p>
  </div>`;

/** Draw one PDF page (canvas + selectable text layer) into `container`. */
async function renderPdfPage(pageNum, container, targetWidth, zoom) {
  const page = await pdfDoc.getPage(pageNum);
  const dpr = window.devicePixelRatio || 1;
  const cssScale = (targetWidth / page.getViewport({ scale: 1 }).width) * zoom;
  const viewport = page.getViewport({ scale: cssScale });
  const renderViewport = page.getViewport({ scale: cssScale * dpr });

  const wrap = document.createElement("div");
  wrap.className = "pdf-page-wrap";
  wrap.style.width = `${viewport.width}px`;
  wrap.style.height = `${viewport.height}px`;

  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(renderViewport.width);
  canvas.height = Math.ceil(renderViewport.height);
  canvas.style.cssText = `width:${viewport.width}px;height:${viewport.height}px;display:block;border-radius:6px;`;
  await page.render({ canvasContext: canvas.getContext("2d", { alpha: false }), viewport: renderViewport }).promise;
  wrap.appendChild(canvas);

  void buildPdfTextLayer(page, wrap, viewport);

  try { container.querySelector(".pdf-page-wrap")?._textLayerTask?.cancel?.(); } catch (_) {}
  clearElement(container);
  container.appendChild(wrap);
}

async function loadPdfInViewer(paper) {
  const body = $("pdfBody");
  if (!body) return;

  if (!paper) {
    body.innerHTML = PDF_PLACEHOLDER;
    pdfDoc = null;
    state.currentPage = 1;
    state.totalPages = 0;
    pdfZoomLevel = 1;
    setText("pageInfo", "0 / 0");
    setText("pdfZoomLabel", "100%");
    return;
  }

  body.innerHTML = `<div style="color:var(--text3);font-size:12px;text-align:center;padding:20px;">Loading PDF…</div>`;

  try {
    const url = `${API_BASE}/uploads/${paper.path.replace(/^papers\/uploads\//, "")}`;
    pdfDoc = await pdfjsLib.getDocument(url).promise;
    state.totalPages = pdfDoc.numPages;
    pdfZoomLevel = 1;
    await renderSidebarPage(1);
  } catch (e) {
    body.innerHTML = `<div style="color:var(--red);font-size:12px;text-align:center;padding:20px;">Could not load PDF.<br>${escapeHtml(e.message)}</div>`;
    pdfDoc = null;
    state.totalPages = 0;
    state.currentPage = 1;
    setText("pageInfo", "0 / 0");
  }
}

async function renderSidebarPage(pageNum) {
  const body = $("pdfBody");
  if (!pdfDoc || !body) return;

  body.style.cssText = "overflow-y:auto;padding:8px;display:flex;justify-content:center;align-items:flex-start;";
  await renderPdfPage(pageNum, body, (body.clientWidth || 320) - 16, pdfZoomLevel);

  state.currentPage = pageNum;
  setText("pageInfo", `${pageNum} / ${state.totalPages}`);
  setText("pdfZoomLabel", `${Math.round(pdfZoomLevel * 100)}%`);
}

function pdfZoom(delta) {
  if (!pdfDoc) return;
  pdfZoomLevel = Math.min(4, Math.max(0.5, pdfZoomLevel + delta));
  renderSidebarPage(state.currentPage);
}

function changePage(delta) {
  if (!pdfDoc) { showToast("No PDF loaded"); return; }
  const next = state.currentPage + delta;
  if (next >= 1 && next <= state.totalPages) renderSidebarPage(next);
}

/* ── Select text in the PDF -> "Explain" popup ───────────── */

async function buildPdfTextLayer(page, wrap, viewport) {
  const layer = document.createElement("div");
  layer.className = "pdf-text-layer";
  layer.style.width = `${viewport.width}px`;
  layer.style.height = `${viewport.height}px`;
  layer.style.setProperty("--scale-factor", String(viewport.scale));
  wrap.appendChild(layer);

  try {
    if (typeof pdfjsLib.renderTextLayer !== "function") return;
    const textContent = await page.getTextContent({ normalizeWhitespace: true });
    // Not awaited on purpose: a slow text layer must never block the page itself.
    wrap._textLayerTask = pdfjsLib.renderTextLayer({
      textContent, container: layer, viewport, textDivs: [], enhanceTextSelection: true,
    });
    wrap._textLayerTask.promise?.catch((err) => console.warn("[PDF] text layer failed:", err));
  } catch (err) {
    console.warn("[PDF] could not build text layer:", err);
  }
}

function getPdfSelectionTerm() {
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;

  const range = sel.getRangeAt(0);
  const layerOf = (node) => (node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement)?.closest?.(".pdf-text-layer");
  const startLayer = layerOf(range.startContainer);
  if (!startLayer || startLayer !== layerOf(range.endContainer)) return null;

  const term = sel.toString()
    .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, " ")
    .replace(/[\u00A0\u200B\u200C\u200D\uFEFF]/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  if (!term || term.length > 500 || term.split(" ").length > 40) return null;
  return term;
}

function getPopup() {
  let popup = $("pdfExplainPopup");
  if (!popup) {
    popup = document.createElement("div");
    popup.id = "pdfExplainPopup";
    popup.className = "pdf-explain-popup";
    document.body.appendChild(popup);
  }
  return popup;
}

/** Keep the popup fully on screen (flip above the selection if needed). */
function positionPopup(popup) {
  const gap = 10, margin = 8;
  const x = Number(popup.dataset.anchorX || 0);
  const y = Number(popup.dataset.anchorY || 0);
  const rect = popup.getBoundingClientRect();
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;

  let left = Math.max(margin, Math.min(x + gap, vw - rect.width - margin));
  let top = y + gap;
  if (top + rect.height > vh - margin) top = y - rect.height - gap;
  if (top < margin) top = Math.min(Math.max(margin, y + gap), vh - rect.height - margin);

  popup.style.left = `${left}px`;
  popup.style.top = `${Math.max(margin, top)}px`;
}

function showPdfExplainPopup(term, x, y) {
  const popup = getPopup();
  popup.dataset.anchorX = String(x);
  popup.dataset.anchorY = String(y);
  popup.innerHTML = `<button type="button" class="pdf-explain-trigger" id="pdfExplainTriggerBtn">Explain "${escapeHtml(term)}"</button>`;
  popup.style.cssText = "display:block;visibility:hidden;left:8px;top:8px;";

  requestAnimationFrame(() => {
    positionPopup(popup);
    popup.style.visibility = "visible";
  });
  $("pdfExplainTriggerBtn").onclick = () => runPdfExplain(term, popup);
}

function closePdfExplainPopup() {
  const popup = $("pdfExplainPopup");
  if (popup) popup.style.display = "none";
}

async function runPdfExplain(term, popup) {
  const paper = getActivePaper();
  if (!paper) { showToast("Select a paper first"); return; }

  popup.innerHTML = `<div class="pdf-explain-loading">Explaining "${escapeHtml(term)}"…</div>`;
  positionPopup(popup);

  try {
    const data = await fetchJson("/api/explain", {
      method: "POST",
      body: JSON.stringify({ term, paper_path: paper.path }),
    });
    state.tabCache = {};  // memory changed -> Insights/Prerequisites must recalculate
    renderPdfExplainCard(popup, data);
    showToast(`"${term}" saved to Memory.`);
  } catch (err) {
    popup.innerHTML = `<div class="pdf-explain-error">${escapeHtml(err.message || "Failed to explain")}</div>`;
    positionPopup(popup);
  }
}

function renderPdfExplainCard(popup, data) {
  const example = (data.real_world_example || "").replace(/^example\s*:\s*/i, "");
  popup.innerHTML = `
    <div class="pdf-explain-card">
      <div class="pdf-explain-card-head">
        <strong>${escapeHtml(data.term || "Explanation")}</strong>
        <button type="button" class="pdf-explain-close" aria-label="Close">×</button>
      </div>
      <div class="pdf-explain-section"><b>From paper:</b> ${escapeHtml(data.from_paper || "Not explained in the retrieved paper context.")}</div>
      <div class="pdf-explain-section"><b>Simple:</b> ${escapeHtml(data.simple_explanation || "No simple explanation was returned.")}</div>
      ${example ? `<div class="pdf-explain-section"><b>Example:</b> ${escapeHtml(example)}</div>` : ""}
    </div>`;
  popup.querySelector(".pdf-explain-close").addEventListener("click", closePdfExplainPopup);
  requestAnimationFrame(() => positionPopup(popup));
}

document.addEventListener("mouseup", (e) => {
  if (!e.target.closest?.(".pdf-text-layer")) return;
  setTimeout(() => {  // let the browser finish updating the selection first
    const term = getPdfSelectionTerm();
    if (term) showPdfExplainPopup(term, e.clientX, e.clientY);
  }, 0);
});

document.addEventListener("mousedown", (e) => {
  const popup = $("pdfExplainPopup");
  if (popup && popup.style.display === "block" && !popup.contains(e.target)) closePdfExplainPopup();
});

window.addEventListener("resize", () => {
  const popup = $("pdfExplainPopup");
  if (popup?.style.display === "block") positionPopup(popup);
});

/* ── Fullscreen PDF ───────────────────────────────────────── */

async function openPdfFullscreen() {
  if (!pdfDoc) { showToast("No PDF loaded"); return; }

  fsPage = state.currentPage;
  fsZoomLevel = 1;
  const paper = getActivePaper();
  if (paper) setText("pdfFullscreenTitle", paper.title);

  $("pdfFullscreenOverlay").classList.add("open");
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", handleFullscreenKey);

  try {
    await renderFullscreenPage(fsPage);
  } catch (err) {
    console.error("[PDF] fullscreen failed:", err);
    showToast("Could not render fullscreen PDF page.");
  }
}

function closePdfFullscreen() {
  $("pdfFullscreenOverlay")?.classList.remove("open");
  document.body.style.overflow = "";
  document.removeEventListener("keydown", handleFullscreenKey);
  closePdfExplainPopup();
}

function handleFullscreenKey(e) {
  if (e.key === "Escape") closePdfFullscreen();
  if (e.key === "ArrowRight") changeFsPage(1);
  if (e.key === "ArrowLeft") changeFsPage(-1);
}

async function renderFullscreenPage(pageNum) {
  const body = $("pdfFullscreenBody");
  if (!pdfDoc || !body) return;

  await renderPdfPage(pageNum, body, Math.max(320, Math.floor(window.innerWidth * 0.9)), fsZoomLevel);
  fsPage = pageNum;
  setText("pdfFsPageInfo", `${pageNum} / ${state.totalPages}`);
  setText("pdfFsZoomLabel", `${Math.round(fsZoomLevel * 100)}%`);
}

function changeFsPage(delta) {
  const next = fsPage + delta;
  if (next >= 1 && next <= state.totalPages) renderFullscreenPage(next).catch(console.error);
}

function pdfFsZoom(delta) {
  fsZoomLevel = Math.min(4, Math.max(0.5, fsZoomLevel + delta));
  renderFullscreenPage(fsPage).catch(console.error);
}

/* ── Tab cache ────────────────────────────────────────────── */

const getCachedTab = (paperId, tab) => state.tabCache[paperId]?.[tab] ?? null;

function setCachedTab(paperId, tab, data) {
  (state.tabCache[paperId] ||= {})[tab] = data;
}

/* ── Chat history ─────────────────────────────────────────── */

function renderChatHistory(paperId) {
  const chatArea = $("chatArea");
  const thinking = $("thinkingMsg");
  if (!chatArea || !thinking) return;

  Array.from(chatArea.children).forEach((child) => {
    if (child !== thinking) chatArea.removeChild(child);
  });
  thinking.style.display = "none";

  (state.chatHistory[paperId] || []).forEach(({ role, text }) => {
    chatArea.insertBefore(createMessageElement(role, text), thinking);
  });
  chatArea.scrollTop = chatArea.scrollHeight;
}

async function loadChatHistory(paper) {
  if (!paper) { renderChatHistory(null); return; }

  if (!state.chatLoaded[paper.id]) {
    renderChatHistory(null);
    try {
      const data = await fetchJson(`/api/chat-history/${paper.path}`);
      state.chatHistory[paper.id] = Array.isArray(data.history) ? data.history : [];
    } catch {
      state.chatHistory[paper.id] = [];
    }
    state.chatLoaded[paper.id] = true;
  }
  renderChatHistory(paper.id);
}

/* ── Indexing progress ────────────────────────────────────── */

function showProgressBar(pct, message) {
  let bar = $("indexProgressBar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "indexProgressBar";
    bar.className = "index-progress-bar";
    bar.innerHTML = `<div class="ipb-track"><div class="ipb-fill" id="ipbFill"></div></div><div class="ipb-label" id="ipbLabel"></div>`;
    const list = $("paperList");
    list?.parentNode?.insertBefore(bar, list);
  }
  bar.style.display = "block";
  $("ipbFill").style.width = `${Math.min(100, Math.max(0, pct))}%`;
  $("ipbLabel").textContent = message || "";
}

function hideProgressBar() {
  const bar = $("indexProgressBar");
  if (bar) bar.style.display = "none";
}

function startIndexPolling(paper) {
  const name = paper.collectionName;
  if (state.pollTimers[name]) return;

  const stop = () => {
    clearInterval(state.pollTimers[name]);
    delete state.pollTimers[name];
    hideProgressBar();
  };

  state.pollTimers[name] = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/status/${paper.path}`);
      if (!res.ok) return;
      const { status, pct, step, message } = await res.json();

      state.papers = state.papers.map((p) =>
        p.id !== paper.id ? p : { ...p, indexStatus: status, indexPct: pct, indexStep: step, indexMessage: message }
      );
      renderPapers();

      if (state.activePaperId === paper.id && status === "indexing") showProgressBar(pct, message || step);

      if (status === "ready") { stop(); showToast(`"${paper.title}" is ready!`); }
      if (status === "error") { stop(); showToast(`Indexing failed for "${paper.title}". Try re-uploading.`); }
    } catch { /* network blip: try again next tick */ }
  }, 2000);
}

/* ── Sidebar paper list ───────────────────────────────────── */

function renderPapers() {
  const list = $("paperList");
  if (!list) return;
  clearElement(list);

  if (!state.papers.length) {
    list.innerHTML = `<div style="padding:16px;text-align:center;color:var(--text3);font-size:12px;">No papers yet — upload one to get started</div>`;
    return;
  }

  state.papers.forEach((paper) => {
    const status = paper.indexStatus || "ready";

    let meta = "";
    if (status === "indexing") {
      meta = `<span style="color:var(--amber);">${escapeHtml(paper.indexStep || "Indexing...")}</span>
              <div class="sidebar-mini-bar"><div class="sidebar-mini-fill" style="width:${paper.indexPct ?? 0}%"></div></div>`;
    } else if (status === "error") {
      meta = `<span style="color:var(--red);">Index failed</span>`;
    }

    const item = document.createElement("div");
    item.className = `paper-item${paper.active ? " active" : ""}`;
    item.innerHTML = `
      <div class="paper-dot ${status === "ready" ? "ready" : status}"></div>
      <div class="paper-info">
        <div class="paper-title"></div>
        <div class="paper-meta">${meta}</div>
      </div>`;
    item.querySelector(".paper-title").textContent = paper.title || "Untitled";
    item.addEventListener("click", () => void selectPaper(paper.id));
    list.appendChild(item);
  });
}

async function logout() {
  try { await fetch(`${API_BASE}/api/logout`, { method: "POST" }); }
  finally { window.location.href = "/auth"; }
}

/* ── Settings dropdown ────────────────────────────────────── */

function closeSettingsMenu() {
  const menu = $("settingsDropdown");
  if (menu) menu.style.display = "none";
}

function toggleSettingsMenu(e) {
  e?.stopPropagation();
  const menu = $("settingsDropdown");
  if (menu) menu.style.display = menu.style.display === "block" ? "none" : "block";
}

document.addEventListener("click", (e) => {
  const menu = $("settingsDropdown");
  const button = $("settingsBtn");
  if (menu?.style.display === "block" && !menu.contains(e.target) && !button?.contains(e.target)) {
    menu.style.display = "none";
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if ($("memoryModalOverlay")?.style.display === "flex") closeMemoryModal();
  else if ($("apiKeyModalOverlay")?.style.display === "flex") closeApiKeyModal();
});

/* ── Memory modal ─────────────────────────────────────────── */

async function openMemoryModal() {
  closeSettingsMenu();
  $("memoryModalOverlay").style.display = "flex";
  try {
    const data = await fetchJson("/api/known-terms");
    state.knownTerms = Array.isArray(data.terms) ? data.terms : [];
  } catch {
    state.knownTerms = [];
  }
  renderMemoryModal();
}

function closeMemoryModal() {
  $("memoryModalOverlay").style.display = "none";
  // Refresh Insights / Prerequisites if one is open, so changes show right away.
  const active = document.querySelector(".tab.active")?.id.replace("tab-", "");
  if (active === "insights" || active === "prerequisites") switchTab(active);
}

function renderMemoryModal() {
  const grid = $("memoryTermsGrid");
  const empty = $("memoryEmptyState");
  const clearBtn = $("memoryClearAllBtn");
  const n = state.knownTerms.length;

  clearElement(grid);
  setText("memoryCount", `${n} term${n !== 1 ? "s" : ""} learned`);
  if (clearBtn) clearBtn.style.display = n ? "inline-flex" : "none";
  grid.style.display = n ? "grid" : "none";
  empty.style.display = n ? "none" : "flex";

  state.knownTerms.forEach((term) => {
    const card = document.createElement("div");
    card.className = "memory-term-card";
    card.innerHTML = `<span class="memory-term-label"></span><button class="memory-term-remove" type="button">🗑</button>`;

    const label = card.querySelector(".memory-term-label");
    label.textContent = term;
    label.title = term;

    const remove = card.querySelector(".memory-term-remove");
    remove.title = `Forget "${term}"`;
    remove.addEventListener("click", (e) => { e.stopPropagation(); deleteKnownTerm(term); });
    grid.appendChild(card);
  });
}

async function deleteKnownTerm(term) {
  if (prompt(`This cannot be undone. Type DELETE to permanently forget "${term}":`) !== "DELETE") {
    showToast("Cancelled — nothing deleted.");
    return;
  }
  try {
    await fetchJson("/api/known-terms/delete", { method: "POST", body: JSON.stringify({ term }) });
    state.knownTerms = state.knownTerms.filter((t) => t.toLowerCase() !== term.toLowerCase());
    renderMemoryModal();
    state.tabCache = {};
    showToast(`Forgot "${term}" — Prerequisites and Difficulty Score updated.`);
  } catch (e) {
    showToast(e.message || "Failed to delete");
  }
}

async function deleteAllKnownTerms() {
  if (!state.knownTerms.length) { showToast("Nothing to forget yet"); return; }
  const typed = prompt(`This will erase ALL ${state.knownTerms.length} learned terms and cannot be undone. Type DELETE ALL to confirm:`);
  if (typed !== "DELETE ALL") { showToast("Cancelled — nothing deleted."); return; }

  try {
    await fetchJson("/api/known-terms/delete-all", { method: "POST" });
    state.knownTerms = [];
    renderMemoryModal();
    state.tabCache = {};
    showToast("All known terms cleared.");
  } catch (e) {
    showToast(e.message || "Failed to delete");
  }
}

/* ── API key modal ────────────────────────────────────────── */

const API_KEY_HELP = "Paste your Gemini API key below. It's stored in your account, so you won't need a .env file.";

async function openApiKeyModal() {
  closeSettingsMenu();
  const sub = $("apiKeyModalSub");
  const removeBtn = $("apiKeyRemoveBtn");

  $("apiKeyInput").value = "";
  $("apiKeyModalOverlay").style.display = "flex";
  sub.textContent = API_KEY_HELP;
  removeBtn.style.display = "none";

  try {
    const data = await fetchJson("/api/settings");
    if (data.hasKey) {
      const source = data.source === "user" ? "saved by you" : "from .env";
      sub.textContent = `Current key (${source}): ${data.masked}. Paste a new one below to replace it.`;
      removeBtn.style.display = data.source === "user" ? "inline-flex" : "none";
    }
  } catch { /* keep default text */ }

  $("apiKeyInput").focus();
}

function closeApiKeyModal() {
  $("apiKeyModalOverlay").style.display = "none";
}

async function saveApiKey() {
  const key = $("apiKeyInput").value.trim();
  if (!key) { showToast("Please paste a key first"); return; }
  try {
    await fetchJson("/api/settings/api-key", { method: "POST", body: JSON.stringify({ api_key: key }) });
    showToast("API key saved. It'll be used for all Gemini calls from now on.");
    closeApiKeyModal();
  } catch (e) {
    showToast(e.message || "Failed to save key");
  }
}

async function removeApiKey() {
  if (prompt("This cannot be undone. Type DELETE to remove your saved Gemini API key:") !== "DELETE") {
    showToast("Cancelled — key not removed.");
    return;
  }
  try {
    await fetchJson("/api/settings/api-key/delete", { method: "POST" });
    showToast("API key removed. Falling back to .env if one is configured there.");
    closeApiKeyModal();
  } catch (e) {
    showToast(e.message || "Failed to remove key");
  }
}

/* ── INSIGHTS TAB ─────────────────────────────────────────── */

const SCORE_COMPONENTS = [
  { key: "readability",     label: "Readability",     icon: "📖", fallback: 20 },
  { key: "uncommon_words",  label: "Uncommon Words",  icon: "🔤", fallback: 15 },
  { key: "technical_terms", label: "Technical Terms", icon: "🔬", fallback: 25 },
  { key: "llm_perception",  label: "LLM Perception",  icon: "🤖", fallback: 40 },
];

function makeBar(value, max = 10) {
  const pct = Math.round((value / max) * 100);
  return makeCard(
    "background:var(--surface2);border-radius:99px;height:6px;width:100%;margin-top:4px;",
    `<div style="height:6px;border-radius:99px;width:${pct}%;background:var(--accent);transition:width 0.4s;"></div>`
  );
}

function renderInsights(paper) {
  const panel = $("insightsContent");
  if (!panel) return;
  clearElement(panel);

  if (!paper) { showBox("insightsContent", "📄", "No Paper Selected", "Upload or select a paper."); return; }
  const analysis = paper.analysis;
  if (!analysis?.final_score) { showBox("insightsContent", "⏳", "Analyzing...", "Computing difficulty analysis."); return; }

  const score = analysis.final_score;
  const label = analysis.difficulty_label || "";
  const scores = analysis.scores || {};
  const weights = analysis.weights || {};
  const stats = analysis.breakdown || {};
  const labelColor = { Easy: "var(--green)", Medium: "var(--amber)", Hard: "var(--red)" }[label] || "var(--accent)";

  // Personalization banner
  const p = analysis.personalization;
  if (p && (p.known_terms_matched > 0 || p.prereqs_known > 0)) {
    const parts = [];
    if (p.known_terms_matched > 0) parts.push(`${p.known_terms_matched} of ${p.total_technical_terms} technical terms`);
    if (p.prereqs_known > 0) parts.push(`${p.prereqs_known} of ${p.total_prereqs} prerequisites`);
    const change = typeof p.base_final_score === "number"
      ? ` Score lowered from <strong>${p.base_final_score.toFixed(1)}</strong> to <strong>${score.toFixed(1)}</strong>.`
      : "";
    panel.appendChild(makeCard(
      "background:var(--green-soft);border:1px solid var(--green);border-radius:var(--radius-lg);padding:10px 14px;margin-bottom:14px;font-size:12px;color:var(--green);display:flex;align-items:center;gap:8px;line-height:1.5;",
      `<span style="font-size:15px;">🧠</span><span>Personalized for you: you already know ${parts.join(" and ")}.${change}</span>`
    ));
  }

  // Score circle
  const pct = Math.round((score / 10) * 100);
  const circumference = 2 * Math.PI * 36;
  const offset = circumference - (pct / 100) * circumference;
  panel.appendChild(makeCard(
    `${CARD}padding:24px;margin-bottom:16px;display:flex;align-items:center;justify-content:space-between;`,
    `<div>
       <div style="font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">Difficulty Score</div>
       <div style="font-size:42px;font-weight:700;color:var(--text);line-height:1;">${score.toFixed(1)}<span style="font-size:18px;color:var(--text2);"> / 10</span></div>
       <div style="margin-top:10px;"><span style="background:${labelColor}20;color:${labelColor};border:1px solid ${labelColor}40;padding:4px 12px;border-radius:99px;font-size:12px;font-weight:600;">${label || "Unknown"}</span></div>
     </div>
     <svg width="90" height="90" viewBox="0 0 90 90">
       <circle cx="45" cy="45" r="36" fill="none" stroke="var(--surface2)" stroke-width="8"/>
       <circle cx="45" cy="45" r="36" fill="none" stroke="var(--accent)" stroke-width="8"
         stroke-dasharray="${circumference.toFixed(1)}" stroke-dashoffset="${offset.toFixed(1)}"
         stroke-linecap="round" transform="rotate(-90 45 45)" style="transition:stroke-dashoffset 0.6s;"/>
       <text x="45" y="50" text-anchor="middle" font-size="16" font-weight="700" fill="var(--text)">${pct}%</text>
     </svg>`
  ));

  // Component scores
  const components = makeCard(`${CARD}padding:18px;margin-bottom:16px;`,
    `<div style="font-size:13px;font-weight:600;margin-bottom:16px;color:var(--text);">Component Scores</div>`);
  SCORE_COMPONENTS.forEach(({ key, label: name, icon, fallback }) => {
    const value = scores[key];
    const weight = typeof weights[key] === "number" ? Math.round(weights[key] * 100) : fallback;
    const row = makeCard("margin-bottom:14px;",
      `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
         <span style="font-size:12px;color:var(--text2);">${icon} ${name} <span style="color:var(--text3);font-size:10px;">(weight ${weight}%)</span></span>
         <span style="font-size:12px;font-weight:600;color:var(--text);">${value !== undefined ? Number(value).toFixed(1) : "N/A"} / 10</span>
       </div>`);
    if (value !== undefined) row.appendChild(makeBar(Number(value)));
    components.appendChild(row);
  });
  panel.appendChild(components);

  // Paper statistics
  const statRows = [
    ["Total Sentences", stats.total_sentences],
    ["Total Words", stats.total_words],
    ["Uncommon Word %", stats.uncommon_word_pct != null ? `${stats.uncommon_word_pct}%` : null],
    ["Tech Keyphrases", stats.technical_keyphrases],
    ["FK Grade", stats.flesch_kincaid_grade],
    ["Reading Ease", stats.flesch_reading_ease],
  ];
  const statsCard = makeCard(`${CARD}padding:18px;`,
    `<div style="font-size:13px;font-weight:600;margin-bottom:14px;color:var(--text);">Paper Statistics</div>`);
  const grid = makeCard("display:grid;grid-template-columns:1fr 1fr;gap:10px;", "");
  statRows.forEach(([name, value]) => {
    grid.appendChild(makeCard("background:var(--surface2);border-radius:var(--radius);padding:10px 12px;",
      `<div style="font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:0.4px;">${name}</div>
       <div style="font-size:15px;font-weight:600;color:var(--text);margin-top:2px;">${value ?? "N/A"}</div>`));
  });
  statsCard.appendChild(grid);
  panel.appendChild(statsCard);
}

/* ── PREREQUISITES TAB ────────────────────────────────────── */

function explainPrerequisite(concept) {
  switchTab("explain");
  setTimeout(() => {
    const input = $("explainInput");
    if (input) {
      input.value = concept;
      input.style.transition = "box-shadow 0.3s";
      input.style.boxShadow = "0 0 0 3px rgba(45, 91, 227, 0.35)";
      setTimeout(() => { input.style.boxShadow = ""; }, 1200);
    }
    void explainTerm();
  }, 80);
}

/** "3. Softmax: explanation" -> { number, concept, explanation } */
function parsePrerequisites(text) {
  const items = [];
  text.trim().split("\n").forEach((line) => {
    const match = line.match(/^\s*(\d+)[.)]\s*(.+)/);
    if (!match) return;
    const content = match[2].trim();
    const colon = content.indexOf(":");
    items.push(colon === -1
      ? { number: match[1], concept: content, explanation: "" }
      : { number: match[1], concept: content.slice(0, colon).trim(), explanation: content.slice(colon + 1).trim() });
  });
  return items;
}

function renderPrerequisites(text) {
  const panel = $("prerequisitesContent");
  if (!panel) return;
  clearElement(panel);

  if (!text || !text.trim()) {
    showBox("prerequisitesContent", "🎉", "Nothing Left To Learn", "You already know every prerequisite for this paper — nice work.");
    return;
  }

  panel.appendChild(makeCard(
    "background:var(--accent-soft);border:1px solid var(--accent-border);border-radius:var(--radius-lg);padding:14px 18px;margin-bottom:16px;display:flex;align-items:center;gap:10px;",
    `<span style="font-size:20px;">🎓</span>
     <div>
       <div style="font-size:13px;font-weight:600;color:var(--accent);">Learning Roadmap</div>
       <div style="font-size:11px;color:var(--text2);margin-top:2px;">Click any topic to get an instant explanation. Topics you already learned are hidden automatically.</div>
     </div>`));

  const items = parsePrerequisites(text);
  if (!items.length) {
    const raw = makeCard(`${CARD}padding:18px;white-space:pre-wrap;font-size:12.5px;color:var(--text2);line-height:1.8;`, "");
    raw.textContent = text;
    panel.appendChild(raw);
    return;
  }

  items.forEach((item, index) => {
    const color = index < items.length * 0.33 ? "var(--green)" : index < items.length * 0.66 ? "var(--amber)" : "var(--red)";
    const card = makeCard(
      `${CARD}border-left:3px solid ${color};padding:14px 16px;margin-bottom:10px;display:flex;align-items:flex-start;gap:14px;cursor:pointer;transition:background 0.15s, box-shadow 0.15s, transform 0.1s;`,
      `<div style="min-width:28px;height:28px;border-radius:50%;background:var(--accent);color:white;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px;">${item.number}</div>
       <div style="flex:1;min-width:0;">
         <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
           <div class="prereq-concept" style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:3px;"></div>
           <span class="prereq-chip" style="font-size:10px;color:var(--accent);background:var(--accent-soft);border:1px solid var(--accent-border);border-radius:99px;padding:2px 8px;white-space:nowrap;flex-shrink:0;opacity:0;transition:opacity 0.2s;">Explain →</span>
         </div>
         <div class="prereq-text" style="font-size:12px;color:var(--text2);line-height:1.6;"></div>
       </div>`);

    card.querySelector(".prereq-concept").textContent = item.concept;
    card.querySelector(".prereq-text").textContent = item.explanation;
    const chip = card.querySelector(".prereq-chip");

    card.addEventListener("mouseenter", () => {
      card.style.cssText += "background:var(--accent-soft);box-shadow:0 2px 10px rgba(45,91,227,0.12);transform:translateY(-1px);border-color:var(--accent-border);";
      chip.style.opacity = "1";
    });
    card.addEventListener("mouseleave", () => {
      card.style.background = "var(--surface)";
      card.style.boxShadow = "";
      card.style.transform = "";
      card.style.borderColor = "";
      chip.style.opacity = "0";
    });
    card.addEventListener("click", () => explainPrerequisite(item.concept));
    panel.appendChild(card);
  });

  const dot = (color) => `<span style="width:10px;height:10px;border-radius:2px;background:${color};display:inline-block;"></span>`;
  const legendItem = (color, name) => `<span style="font-size:11px;color:var(--text3);display:flex;align-items:center;gap:5px;">${dot(color)}${name}</span>`;
  panel.appendChild(makeCard(
    "display:flex;gap:16px;margin-top:6px;padding:10px 4px;flex-wrap:wrap;",
    `${legendItem("var(--green)", "Foundational")}${legendItem("var(--amber)", "Intermediate")}${legendItem("var(--red)", "Advanced")}
     <span style="font-size:11px;color:var(--text3);margin-left:auto;">👆 Click any topic to explain it</span>`));
}

/* ── EXPLAIN TAB ──────────────────────────────────────────── */

const EXPLAIN_STEPS = [   // [percent, label, ms before next step]
  [15, "Retrieving relevant sections from paper…", 400],
  [35, "Sending context to Gemini…", 1200],
  [55, "Gemini is reading the paper…", 3000],
  [75, "Generating explanation…", 6000],
  [90, "Preparing your answer…", 10000],
  [95, "Waiting for Gemini response…", 0],
];

function makeExplainLoadingCard(term) {
  if (!$("explainAnimStyles")) {
    const style = document.createElement("style");
    style.id = "explainAnimStyles";
    style.textContent = "@keyframes shimmer{0%,100%{opacity:0.35}50%{opacity:0.75}} #explainProgressFill{transition:width 0.6s ease}";
    document.head.appendChild(style);
  }

  const skeleton = ["📄 From This Paper", "💡 In Simple Words", "🌍 Real-World Example"].map((name) => `
    <div style="border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px 16px;opacity:0.5;">
      <div style="font-size:10px;font-weight:600;color:var(--text3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:9px;">${name}</div>
      ${[82, 65, 50].map((w, i) => `<div style="background:var(--surface2);border-radius:5px;height:9px;width:${w}%;margin-bottom:6px;animation:shimmer 1.6s ease-in-out infinite ${i * 0.2}s;"></div>`).join("")}
    </div>`).join("");

  return makeCard(`${CARD}padding:28px 24px;margin-top:8px;`, `
    <div style="margin-bottom:18px;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px;">
        <div style="font-size:13px;font-weight:600;color:var(--text);">Explaining <span style="color:var(--accent);">"${escapeHtml(term)}"</span></div>
        <div id="explainProgressPct" style="font-size:12px;font-weight:600;color:var(--accent);">0%</div>
      </div>
      <div style="background:var(--surface2);border-radius:99px;height:7px;width:100%;overflow:hidden;">
        <div id="explainProgressFill" style="height:7px;border-radius:99px;background:var(--accent);width:0%;"></div>
      </div>
      <div id="explainProgressLabel" style="font-size:11px;color:var(--text3);margin-top:8px;">Starting…</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:10px;">${skeleton}</div>`);
}

function startExplainProgress() {
  let stopped = false;

  const setProgress = (pct, label) => {
    const fill = $("explainProgressFill");
    if (fill) fill.style.width = `${pct}%`;
    setText("explainProgressPct", `${pct}%`);
    setText("explainProgressLabel", label);
  };

  const showStep = (i) => {
    if (stopped || i >= EXPLAIN_STEPS.length) return;
    const [pct, label, delay] = EXPLAIN_STEPS[i];
    setProgress(pct, label);
    if (delay) setTimeout(() => showStep(i + 1), delay);
  };

  showStep(0);
  return () => { stopped = true; setProgress(100, "Done!"); };
}

async function explainTerm() {
  const input = $("explainInput");
  const panel = $("explainContent");
  const paper = getActivePaper();
  if (!input || !panel) return;

  const term = input.value.trim();
  if (!term) { showToast("Please type a term to explain"); return; }
  if (!paper) { showToast("Upload or select a paper first"); return; }
  if (paper.indexStatus === "indexing") { showToast("Paper is still being indexed."); return; }

  const cacheKey = `${paper.id}::${term.toLowerCase()}`;
  if (state.explainCache[cacheKey]) { renderExplainResult(state.explainCache[cacheKey]); return; }

  clearElement(panel);
  panel.appendChild(makeExplainLoadingCard(term));
  const stopProgress = startExplainProgress();

  try {
    const data = await fetchJson("/api/explain", {
      method: "POST",
      body: JSON.stringify({ term, paper_path: paper.path }),
    });
    stopProgress();
    state.explainCache[cacheKey] = data;
    renderExplainResult(data);

    state.tabCache = {};  // server saved the term to Memory -> recalculate Insights/Prerequisites
    showToast(`"${term}" saved to Memory — Prerequisites and Difficulty Score will drop.`);
  } catch (error) {
    stopProgress();
    showBox("explainContent", "❌", "Explanation Failed", error.message || "Check your API key.");
  }
}

function renderExplainResult(data) {
  const panel = $("explainContent");
  if (!panel) return;
  clearElement(panel);

  const { term, from_paper, simple_explanation, real_world_example, chunks_used, found_in_paper } = data;

  const badgeColors = found_in_paper
    ? "background:var(--green-soft);color:var(--green);border:1px solid var(--green);"
    : "background:var(--amber-soft);color:var(--amber);border:1px solid var(--amber);";
  const badgeText = found_in_paper
    ? `Found in paper (${chunks_used} section${chunks_used !== 1 ? "s" : ""})`
    : "Not in paper — using general knowledge";
  panel.appendChild(makeCard(
    `display:inline-flex;align-items:center;gap:6px;padding:4px 12px;border-radius:99px;font-size:11px;font-weight:600;margin-bottom:16px;${badgeColors}`,
    escapeHtml(badgeText)));

  panel.appendChild(makeCard(
    "font-size:22px;font-weight:700;color:var(--text);margin-bottom:20px;letter-spacing:-0.3px;",
    escapeHtml(term.charAt(0).toUpperCase() + term.slice(1))));

  const section = (icon, title, text, color) => makeCard(
    `${CARD}padding:18px 20px;margin-bottom:14px;border-left:3px solid ${color};`,
    `<div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;"><span style="font-size:16px;">${icon}</span>${title}</div>
     <div style="font-size:13.5px;color:var(--text);line-height:1.75;">${escapeHtml(text)}</div>`);

  panel.appendChild(section("📄", "From This Paper", from_paper, "var(--accent)"));
  panel.appendChild(section("💡", "In Simple Words", simple_explanation, "var(--green)"));

  if (real_world_example) {
    const example = real_world_example.replace(/^example\s*:\s*/i, "").trim();
    panel.appendChild(makeCard(
      "background:var(--amber-soft);border:1px solid var(--amber);border-radius:var(--radius-lg);padding:18px 20px;margin-bottom:14px;border-left:3px solid var(--amber);",
      `<div style="display:flex;align-items:center;gap:8px;font-size:12px;font-weight:600;color:var(--amber);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:10px;"><span style="font-size:16px;">🌍</span>Real-World Example</div>
       <div style="display:flex;gap:10px;align-items:flex-start;">
         <span style="font-size:24px;line-height:1;flex-shrink:0;margin-top:2px;">💬</span>
         <div style="font-size:13.5px;color:var(--text);line-height:1.75;font-style:italic;">"${escapeHtml(example)}"</div>
       </div>`));
  }

  panel.appendChild(makeCard("font-size:11px;color:var(--text3);margin-top:4px;text-align:center;",
    "Type another term above and click Explain to look it up."));
}

function handleExplainKey(event) {
  if (event.key === "Enter") { event.preventDefault(); void explainTerm(); }
}

/* ── TAB SWITCHING ────────────────────────────────────────── */

const TAB_LOADERS = {
  insights: {
    panel: "insightsContent", label: "Insights", emptyIcon: "📄",
    url: "/api/analyze",
    loadingTitle: "Analyzing paper...",
    loadingText: "Running difficulty analysis, personalized to what you already know.",
    failTitle: "Analysis Failed",
    render: renderInsights,
    parse: (data, paper) => {
      const updated = { ...paper, ...(data.paper || {}), analysis: data.analysis || {} };
      updatePaper(updated);
      renderPapers();
      return updated;
    },
  },
  prerequisites: {
    panel: "prerequisitesContent", label: "Prerequisites", emptyIcon: "📚",
    url: "/api/prerequisites",
    loadingTitle: "Extracting Prerequisites...",
    loadingText: "Building your personalized learning roadmap.",
    failTitle: "Extraction Failed",
    render: renderPrerequisites,
    parse: (data) => data.prerequisites || "",
  },
};

async function loadTab(name) {
  const cfg = TAB_LOADERS[name];
  const paper = getActivePaper();

  if (!paper) { showBox(cfg.panel, cfg.emptyIcon, "No Paper Selected", "Upload or select a paper."); return; }

  const cached = getCachedTab(paper.id, name);
  if (cached !== null) { cfg.render(cached); return; }

  if (paper.indexStatus === "indexing") {
    showBox(cfg.panel, "⏳", "Indexing in progress...", `Wait for the green dot, then click ${cfg.label} again.`);
    return;
  }

  showBox(cfg.panel, "⏳", cfg.loadingTitle, cfg.loadingText);
  try {
    const data = await fetchJson(cfg.url, { method: "POST", body: JSON.stringify({ paper_path: paper.path }) });
    const result = cfg.parse(data, paper);
    setCachedTab(paper.id, name, result);
    cfg.render(result);
  } catch (error) {
    showBox(cfg.panel, "❌", cfg.failTitle, error.message || "Check your API key.");
  }
}

function switchTab(name) {
  TABS.forEach((tab) => {
    $(`tab-${tab}`)?.classList.toggle("active", tab === name);
    $(`panel-${tab}`)?.classList.toggle("active", tab === name);
  });

  if (name === "summary") showBox("summaryAccordion", "📝", "Summary — Coming Soon", "Auto-generated paper summaries are in development.", "In Development");
  if (name === "comparison") showBox("comparisonContent", "⚖️", "Comparison — Coming Soon", "Multi-paper comparison is in development.", "In Development");
  if (TAB_LOADERS[name]) void loadTab(name);
}

/* ── Loading + selecting papers ───────────────────────────── */

async function loadPapers() {
  const data = await fetchJson("/api/papers");
  state.papers = (Array.isArray(data.papers) ? data.papers : []).map((p) => ({ ...p, active: false }));

  const savedId = localStorage.getItem(STORAGE.activePaper);
  state.activePaperId = state.papers.some((p) => p.id === savedId) ? savedId : state.papers[0]?.id ?? null;
  state.papers = state.papers.map((p) => ({ ...p, active: p.id === state.activePaperId }));
  state.papers.filter((p) => p.indexStatus === "indexing").forEach(startIndexPolling);

  renderPapers();
  const paper = getActivePaper();
  setText("pdfTitle", paper ? paper.title : "Select a paper to view");
  await loadPdfInViewer(paper);
  await loadChatHistory(paper);
}

async function selectPaper(paperId) {
  setActivePaper(paperId);
  await loadChatHistory(getActivePaper());

  const activeTab = document.querySelector(".tab.active")?.id.replace("tab-", "");
  if (TAB_LOADERS[activeTab]) switchTab(activeTab);

  const paper = getActivePaper();
  if (paper?.indexStatus === "indexing") {
    showProgressBar(paper.indexPct ?? 0, paper.indexMessage || paper.indexStep || "Indexing...");
  } else {
    hideProgressBar();
  }
}

/* ── Upload ───────────────────────────────────────────────── */

async function handleFiles(files) {
  const pdfs = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) { showToast("Please upload PDF files only"); return; }

  for (const file of pdfs) {
    const formData = new FormData();
    formData.append("file", file);

    try {
      showToast(`Uploading ${file.name}...`);
      const response = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: formData });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || "Upload failed");

      const paper = { ...data.paper, analysis: {}, indexStatus: "indexing", indexPct: 5, active: true };
      state.papers = [paper, ...state.papers.map((p) => ({ ...p, active: false }))];
      state.activePaperId = paper.id;
      localStorage.setItem(STORAGE.activePaper, paper.id);

      renderPapers();
      setText("pdfTitle", paper.title);
      await loadPdfInViewer(paper);
      state.chatLoaded[paper.id] = true;
      state.chatHistory[paper.id] = [];
      renderChatHistory(paper.id);
      showProgressBar(5, "Starting...");
      showToast(`Uploaded ${file.name} — indexing in background...`);
      startIndexPolling(paper);
    } catch (error) {
      showToast(error.message || "Upload failed");
    }
  }
}

/* ── Chat ─────────────────────────────────────────────────── */

async function sendMessage() {
  if (state.thinking) return;

  const input = $("chatInput");
  const chatArea = $("chatArea");
  const thinking = $("thinkingMsg");
  const paper = getActivePaper();
  if (!input || !chatArea || !thinking) return;

  const message = input.value.trim();
  if (!message) return;
  if (!paper) { showToast("Upload or select a paper first"); return; }
  if (paper.indexStatus === "indexing") { showToast("Paper is still being indexed. Please wait."); return; }

  const addMessage = (role, text) => {
    (state.chatHistory[paper.id] ||= []).push({ role, text });
    if (state.activePaperId === paper.id) {
      chatArea.insertBefore(createMessageElement(role, text), thinking);
      chatArea.scrollTop = chatArea.scrollHeight;
    }
  };

  addMessage("user", message);
  input.value = "";
  input.style.height = "auto";
  thinking.style.display = "flex";
  chatArea.scrollTop = chatArea.scrollHeight;
  state.thinking = true;

  try {
    const data = await fetchJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, paper_path: paper.path }),
    });
    thinking.style.display = "none";
    addMessage("assistant", data.reply || "No response returned.");
  } catch (error) {
    thinking.style.display = "none";
    addMessage("assistant", error.message || "Error: Could not get response");
  } finally {
    state.thinking = false;
  }
}

function handleKey(event) {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); void sendMessage(); }
}

/* ── Theme + layout ───────────────────────────────────────── */

function applyTheme() {
  document.body.classList.toggle("dark", state.isDark);
  setText("darkIcon", state.isDark ? "☀️" : "🌙");
}

function toggleDark() {
  state.isDark = !state.isDark;
  applyTheme();
  localStorage.setItem(STORAGE.dark, String(state.isDark));
}

function setupResizeHandle() {
  const handle = $("resizeHandle");
  const panel = $("pdfPanel");
  if (!handle || !panel) return;

  const setWidth = (px) => { panel.style.width = panel.style.minWidth = `${px}px`; };
  const saved = localStorage.getItem(STORAGE.pdfWidth);
  if (saved) setWidth(saved);

  let resizing = false, startX = 0, startWidth = 0;

  handle.addEventListener("mousedown", (e) => {
    resizing = true;
    startX = e.clientX;
    startWidth = panel.offsetWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  });
  document.addEventListener("mousemove", (e) => {
    if (resizing) setWidth(Math.max(280, Math.min(700, startWidth + (startX - e.clientX))));
  });
  document.addEventListener("mouseup", () => {
    if (!resizing) return;
    resizing = false;
    document.body.style.cursor = document.body.style.userSelect = "";
    localStorage.setItem(STORAGE.pdfWidth, String(panel.offsetWidth));
  });
}

function setupUploadControls() {
  const fileInput = $("fileInput");
  const dropZone = $("dropZone");

  fileInput?.addEventListener("change", (e) => {
    void handleFiles(Array.from(e.target.files || []));
    e.target.value = "";
  });

  if (dropZone) {
    dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.style.opacity = "0.7"; });
    dropZone.addEventListener("dragleave", () => { dropZone.style.opacity = "1"; });
    dropZone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropZone.style.opacity = "1";
      void handleFiles(Array.from(e.dataTransfer.files || []));
    });
    dropZone.addEventListener("click", () => fileInput?.click());
  }

  $("pdfCloseBtn")?.addEventListener("click", () => {
    $("pdfPanel")?.style.setProperty("display", "none");
    $("resizeHandle")?.style.setProperty("display", "none");
    showToast("PDF panel hidden");
  });
}

/* ── Start ────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", async () => {
  state.isDark = localStorage.getItem(STORAGE.dark) === "true";
  applyTheme();
  setupUploadControls();
  setupResizeHandle();
  switchTab("chat");   // also fills the "Coming Soon" boxes
  try {
    await loadPapers();
  } catch (error) {
    showToast(error.message || "Failed to load papers");
    renderPapers();
  }
});