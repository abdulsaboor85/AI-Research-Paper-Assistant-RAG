/* ═══════════════════════════════════════════════════════════
   JAVASCRIPT FILE PATH CONFIGURATION
   ═══════════════════════════════════════════════════════════
   This JS file should be linked in index.html
   Make sure the path in index.html matches this file's location
   ═══════════════════════════════════════════════════════════ */

/* ═══════════════════════════════════════════════════════════
   GLOBAL STATE & VARIABLES
   ═══════════════════════════════════════════════════════════ */

// Track dark mode state
let isDark = false;

// Track thinking/loading state
let thinking = false;

// Track current PDF page
let currentPage = 0;
let totalPages = 0;

// Papers array - will be populated with real data
let papers = [];

// ═══════════════════════════════════════════════════════════
// API CONFIGURATION
// ═══════════════════════════════════════════════════════════
// UPDATE THESE PATHS WITH YOUR BACKEND API ENDPOINTS

const API_URLS = {
  // Example: 'http://localhost:3000/api/papers'
  // Replace with your actual API endpoint
  fetchPapers: '',
  
  // Example: 'http://localhost:3000/api/upload'
  // Replace with your actual upload endpoint
  uploadPaper: '',
  
  // Example: 'http://localhost:3000/api/chat'
  // Replace with your actual chat endpoint
  sendMessage: '',
  
  // Example: 'http://localhost:3000/api/summary'
  // Replace with your actual summary endpoint
  getSummary: '',
  
  // Add more API endpoints as needed
};

// ═══════════════════════════════════════════════════════════
// DATA STORAGE PATH CONFIGURATION
// ═══════════════════════════════════════════════════════════
// If using localStorage, update the key names below

const STORAGE_KEYS = {
  darkMode: 'papermind_darkMode',
  pdfPanelWidth: 'papermind_pdfPanelWidth',
  // Add more storage keys as needed
};

/* ═══════════════════════════════════════════════════════════
   INITIALIZATION
   ═══════════════════════════════════════════════════════════ */

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  // Load dark mode preference
  const savedDarkMode = localStorage.getItem(STORAGE_KEYS.darkMode);
  if (savedDarkMode === 'true') {
    isDark = true;
    document.body.classList.add('dark');
    document.getElementById('darkBtn').textContent = '☀️';
  }
  
  // Initialize empty papers list
  renderPapers();
  
  // Setup resize handle for PDF panel
  setupResizeHandle();
});

/* ═══════════════════════════════════════════════════════════
   PAPERS LIST RENDERING
   ═══════════════════════════════════════════════════════════ */

function renderPapers() {
  const list = document.getElementById('paperList');
  list.innerHTML = '';
  
  if (papers.length === 0) {
    list.innerHTML = '<div style="padding: 16px; text-align: center; color: var(--text3); font-size: 12px;">No papers uploaded yet</div>';
    return;
  }
  
  papers.forEach(paper => {
    const item = document.createElement('div');
    item.className = 'paper-item' + (paper.active ? ' active' : '');
    
    const statusClass = paper.status === 'ready' ? 'ready' : 'indexing';
    
    item.innerHTML = `
      <div class="paper-dot ${statusClass}"></div>
      <div class="paper-info">
        <div class="paper-title">${escapeHtml(paper.title)}</div>
        <div class="paper-meta">${paper.date}</div>
      </div>
    `;
    
    item.onclick = () => selectPaper(paper.id);
    list.appendChild(item);
  });
}

function selectPaper(id) {
  papers.forEach(p => p.active = p.id === id);
  renderPapers();
  const p = papers.find(p => p.id === id);
  document.getElementById('pdfTitle').textContent = p.title;
  toast('Switched to: ' + p.title.substring(0, 40) + '…');
}

/* ═══════════════════════════════════════════════════════════
   TAB NAVIGATION
   ═══════════════════════════════════════════════════════════ */

function switchTab(name) {
  const validTabs = ['chat', 'summary', 'comparison', 'insights'];
  
  validTabs.forEach(tabName => {
    const tabEl = document.getElementById('tab-' + tabName);
    const panelEl = document.getElementById('panel-' + tabName);
    
    if (tabEl) tabEl.classList.toggle('active', tabName === name);
    if (panelEl) panelEl.classList.toggle('active', tabName === name);
  });
}

/* ═══════════════════════════════════════════════════════════
   DARK MODE
   ═══════════════════════════════════════════════════════════ */

function toggleDark() {
  isDark = !isDark;
  document.body.classList.toggle('dark', isDark);
  document.getElementById('darkBtn').textContent = isDark ? '☀️' : '🌙';
  
  // Save preference
  localStorage.setItem(STORAGE_KEYS.darkMode, isDark);
}

/* ═══════════════════════════════════════════════════════════
   CHAT FUNCTIONALITY
   ═══════════════════════════════════════════════════════════ */

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function sendMessage() {
  if (thinking) return;
  
  const input = document.getElementById('chatInput');
  const val = input.value.trim();
  
  if (!val) return;
  
  const chatArea = document.getElementById('chatArea');
  const thinkEl = document.getElementById('thinkingMsg');
  
  // Display user message
  const userDiv = document.createElement('div');
  userDiv.className = 'msg user';
  userDiv.innerHTML = `
    <div class="msg-body">
      <div class="msg-bubble">${escapeHtml(val)}</div>
    </div>
    <div class="msg-avatar">U</div>
  `;
  chatArea.insertBefore(userDiv, thinkEl);
  
  // Clear input
  input.value = '';
  input.style.height = 'auto';
  
  // Show thinking indicator
  thinkEl.style.display = 'flex';
  chatArea.scrollTop = chatArea.scrollHeight;
  thinking = true;
  
  // ═════════════════════════════════════════════════════════
  // CHAT API INTEGRATION
  // ═════════════════════════════════════════════════════════
  // Send message to your API endpoint
  
  // Example API call:
  /*
  fetch(API_URLS.sendMessage, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      message: val,
      paperId: papers.find(p => p.active)?.id,
    }),
  })
  .then(response => response.json())
  .then(data => {
    displayAssistantMessage(data.reply);
  })
  .catch(error => {
    console.error('Chat error:', error);
    displayAssistantMessage('Error: Could not get response');
  });
  */
  
  // For now, show a placeholder
  setTimeout(() => {
    thinkEl.style.display = 'none';
    
    const aiDiv = document.createElement('div');
    aiDiv.className = 'msg assistant';
    aiDiv.innerHTML = `
      <div class="msg-avatar">PM</div>
      <div class="msg-body">
        <div class="msg-bubble">Configure your API endpoint in the script.js file to enable chat functionality.</div>
        <div class="msg-actions">
          <button class="msg-action-btn" onclick="copyText('Configure API endpoint')">Copy</button>
        </div>
      </div>
    `;
    chatArea.insertBefore(aiDiv, thinkEl);
    chatArea.scrollTop = chatArea.scrollHeight;
    thinking = false;
  }, 800);
}

function displayAssistantMessage(message) {
  const chatArea = document.getElementById('chatArea');
  const thinkEl = document.getElementById('thinkingMsg');
  
  thinkEl.style.display = 'none';
  
  const aiDiv = document.createElement('div');
  aiDiv.className = 'msg assistant';
  aiDiv.innerHTML = `
    <div class="msg-avatar">PM</div>
    <div class="msg-body">
      <div class="msg-bubble">${message}</div>
      <div class="msg-actions">
        <button class="msg-action-btn" onclick="copyText('${message.replace(/'/g, "\\'")}')">Copy</button>
      </div>
    </div>
  `;
  chatArea.insertBefore(aiDiv, thinkEl);
  chatArea.scrollTop = chatArea.scrollHeight;
  thinking = false;
}

/* ═══════════════════════════════════════════════════════════
   PDF VIEWER FUNCTIONS
   ═══════════════════════════════════════════════════════════ */

function highlightPDF(page) {
  const hl = document.getElementById('mainHighlight');
  if (!hl) return;
  
  hl.classList.remove('fade');
  void hl.offsetWidth; // Force reflow
  hl.classList.add('fade');
  
  const pdfBody = document.getElementById('pdfBody');
  pdfBody.scrollTo({ top: 0, behavior: 'smooth' });
  
  currentPage = page || 1;
  document.getElementById('pageInfo').textContent = `${currentPage} / ${totalPages}`;
  toast('Scrolled to page ' + currentPage);
}

function changePage(delta) {
  if (totalPages === 0) {
    toast('No PDF loaded');
    return;
  }
  
  currentPage = Math.max(1, Math.min(totalPages, currentPage + delta));
  document.getElementById('pageInfo').textContent = `${currentPage} / ${totalPages}`;
  toast(`Page ${currentPage}`);
}

/* ═══════════════════════════════════════════════════════════
   UTILITY FUNCTIONS
   ═══════════════════════════════════════════════════════════ */

function escapeHtml(text) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function copyText(text) {
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text)
      .then(() => toast('Copied to clipboard!'))
      .catch(() => toast('Failed to copy'));
  } else {
    // Fallback for older browsers
    const textArea = document.createElement('textarea');
    textArea.value = text;
    document.body.appendChild(textArea);
    textArea.select();
    document.execCommand('copy');
    document.body.removeChild(textArea);
    toast('Copied to clipboard!');
  }
}

function toast(message) {
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  container.appendChild(el);
  
  setTimeout(() => el.remove(), 3200);
}

/* ═══════════════════════════════════════════════════════════
   FILE UPLOAD HANDLING
   ═══════════════════════════════════════════════════════════ */

document.getElementById('fileInput').addEventListener('change', (e) => {
  const files = Array.from(e.target.files);
  handleFiles(files);
  e.target.value = ''; // Reset input
});

const dropZone = document.getElementById('dropZone');

dropZone.addEventListener('dragover', (e) => {
  e.preventDefault();
  dropZone.style.opacity = '0.7';
});

dropZone.addEventListener('dragleave', () => {
  dropZone.style.opacity = '1';
});

dropZone.addEventListener('drop', (e) => {
  e.preventDefault();
  dropZone.style.opacity = '1';
  
  const files = Array.from(e.dataTransfer.files)
    .filter(f => f.name.toLowerCase().endsWith('.pdf'));
  
  if (files.length === 0) {
    toast('Please drop PDF files only');
    return;
  }
  
  handleFiles(files);
});

dropZone.addEventListener('click', () => {
  document.getElementById('fileInput').click();
});

function handleFiles(files) {
  files.forEach(file => {
    // ═════════════════════════════════════════════════════════
    // FILE UPLOAD API INTEGRATION
    // ═════════════════════════════════════════════════════════
    // Upload file to your backend API
    
    // Example API call:
    /*
    const formData = new FormData();
    formData.append('file', file);
    
    fetch(API_URLS.uploadPaper, {
      method: 'POST',
      body: formData,
    })
    .then(response => response.json())
    .then(data => {
      papers.unshift({
        id: data.id,
        title: data.title || file.name.replace('.pdf', ''),
        date: new Date().toLocaleString(),
        status: 'ready',
        active: true,
      });
      renderPapers();
      toast('File uploaded: ' + file.name);
    })
    .catch(error => {
      console.error('Upload error:', error);
      toast('Upload failed');
    });
    */
    
    // For now, add to local list
    papers.unshift({
      id: Date.now() + Math.random(),
      title: file.name.replace('.pdf', ''),
      date: 'Just now',
      status: 'indexing',
      active: false,
    });
    
    renderPapers();
    toast('Added: ' + file.name);
    
    // Simulate indexing completion after delay
    setTimeout(() => {
      const paper = papers.find(p => p.title === file.name.replace('.pdf', ''));
      if (paper) {
        paper.status = 'ready';
        renderPapers();
        toast(file.name + ' is ready!');
      }
    }, 3000);
  });
}

/* ═══════════════════════════════════════════════════════════
   PDF PANEL RESIZE HANDLER
   ═══════════════════════════════════════════════════════════ */

function setupResizeHandle() {
  const handle = document.getElementById('resizeHandle');
  const pdfPanel = document.getElementById('pdfPanel');
  
  let isResizing = false;
  let startX = 0;
  let startWidth = 0;
  
  handle.addEventListener('mousedown', (e) => {
    isResizing = true;
    startX = e.clientX;
    startWidth = pdfPanel.offsetWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  });
  
  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    
    const delta = startX - e.clientX;
    const newWidth = Math.max(280, Math.min(700, startWidth + delta));
    
    pdfPanel.style.width = newWidth + 'px';
    pdfPanel.style.minWidth = newWidth + 'px';
  });
  
  document.addEventListener('mouseup', () => {
    if (!isResizing) return;
    
    isResizing = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    
    // Save width preference
    localStorage.setItem(STORAGE_KEYS.pdfPanelWidth, pdfPanel.offsetWidth);
  });
  
  // Restore saved width
  const savedWidth = localStorage.getItem(STORAGE_KEYS.pdfPanelWidth);
  if (savedWidth) {
    pdfPanel.style.width = savedWidth + 'px';
    pdfPanel.style.minWidth = savedWidth + 'px';
  }
}

/* ═══════════════════════════════════════════════════════════
   TEXT SELECTION FROM PDF
   ═══════════════════════════════════════════════════════════ */

document.getElementById('pdfBody')?.addEventListener('mouseup', () => {
  const selectedText = window.getSelection().toString().trim();
  
  if (selectedText.length > 10) {
    const chatInput = document.getElementById('chatInput');
    chatInput.value = 'Tell me more about: "' + selectedText.substring(0, 100) + '"';
    chatInput.style.height = 'auto';
    chatInput.style.height = chatInput.scrollHeight + 'px';
    
    switchTab('chat');
    toast('Text copied to chat — press Enter to ask!');
  }
});

/* ═══════════════════════════════════════════════════════════
   END OF SCRIPT
   ═══════════════════════════════════════════════════════════ */
