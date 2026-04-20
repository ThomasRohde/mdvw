// mdvw front-end glue — three-mode viewer/editor.

const html = document.documentElement;
const preview = document.getElementById('preview');
const editor = document.getElementById('editor');
const toast = document.getElementById('toast');
const fileChip = document.getElementById('file-chip');
const btnBack = document.getElementById('btn-back');
const btnForward = document.getElementById('btn-forward');
const assocDialog = document.getElementById('assoc-prompt');
const helpDialog = document.getElementById('help-dialog');
const segs = document.querySelectorAll('.segmented .seg');
const mainEl = document.getElementById('main');

// Defense in depth: scope bootstrap lookups to the specific <script> tags
// we injected, so a user document with `<div id="md-source">...` can't
// shadow our data during sanitizer edge cases.
const bootstrapEl = (id) =>
  document.querySelector(`script#${id}`) ||
  document.getElementById(id);

const mdSource = JSON.parse(bootstrapEl('md-source').textContent || '""');
const mdPath = bootstrapEl('md-path').textContent.trim();
let currentPath = mdPath;
const startMode = (bootstrapEl('md-start-mode').textContent.trim() || 'read');
let browseRoot = (bootstrapEl('md-browse-root')?.textContent || '').trim();
const uiState = JSON.parse(bootstrapEl('md-ui-state')?.textContent || '{}');

const getApi = () => (window.pywebview && window.pywebview.api) || null;

let currentSource = mdSource;
let currentMode = 'read';
let dirty = false;

// ---------- Document navigation history ----------

const navigationHistory = [];
let navigationIndex = -1;
let pendingHistoryTraversal = null;
let navigationBusy = false;

function navigationEntry(path, name = '') {
  if (!path) return null;
  const fallback = String(path).split(/[\\/]/).filter(Boolean).pop() || String(path);
  return { path: String(path), name: name || fallback };
}

function updateNavigationControls() {
  const back = navigationHistory[navigationIndex - 1] || null;
  const forward = navigationHistory[navigationIndex + 1] || null;
  btnBack.disabled = !back || navigationBusy;
  btnForward.disabled = !forward || navigationBusy;
  btnBack.title = back ? `Back to ${back.name} (Alt+Left)` : 'Back (Alt+Left)';
  btnForward.title = forward ? `Forward to ${forward.name} (Alt+Right)` : 'Forward (Alt+Right)';
}

function recordDocumentNavigation(path, name = '', reason = 'open') {
  const entry = navigationEntry(path, name);
  if (!entry) { updateNavigationControls(); return; }

  if (pendingHistoryTraversal && sameBrowserPath(entry.path, pendingHistoryTraversal.path)) {
    navigationHistory[pendingHistoryTraversal.index] = entry;
    navigationIndex = pendingHistoryTraversal.index;
    pendingHistoryTraversal = null;
    updateNavigationControls();
    return;
  }
  if (pendingHistoryTraversal) pendingHistoryTraversal = null;

  if (reason === 'watch') {
    if (navigationIndex >= 0) navigationHistory[navigationIndex] = entry;
    else {
      navigationHistory.push(entry);
      navigationIndex = 0;
    }
    updateNavigationControls();
    return;
  }

  const current = navigationHistory[navigationIndex] || null;
  if (current && sameBrowserPath(current.path, entry.path)) {
    navigationHistory[navigationIndex] = entry;
    updateNavigationControls();
    return;
  }

  navigationHistory.splice(navigationIndex + 1);
  navigationHistory.push(entry);
  if (navigationHistory.length > 100) navigationHistory.shift();
  navigationIndex = navigationHistory.length - 1;
  updateNavigationControls();
}

async function openHistoryPath(path) {
  const api = await whenApiReady();
  if (!api) return false;
  if (api.open_path) {
    try {
      if (await api.open_path(path)) return true;
    } catch { /* fall back to recent-file allowlist */ }
  }
  if (api.open_recent) {
    try {
      return !!(await api.open_recent(path));
    } catch { return false; }
  }
  return false;
}

async function navigateHistory(delta) {
  if (navigationBusy) return;
  const targetIndex = navigationIndex + delta;
  const target = navigationHistory[targetIndex];
  if (!target) return;
  if (!(await confirmDiscardIfDirty())) return;

  const previousIndex = navigationIndex;
  pendingHistoryTraversal = { index: targetIndex, path: target.path };
  navigationIndex = targetIndex;
  navigationBusy = true;
  updateNavigationControls();
  const ok = await openHistoryPath(target.path);
  navigationBusy = false;
  if (!ok) {
    pendingHistoryTraversal = null;
    navigationIndex = previousIndex;
    updateNavigationControls();
    flash(`Could not open ${target.name}`);
    return;
  }
  updateNavigationControls();
}

recordDocumentNavigation(mdPath, fileChip.textContent || mdPath, 'initial');

// ---------- Mode switching ----------

async function setMode(mode) {
  if (!['read', 'edit', 'source'].includes(mode)) mode = 'read';
  if (mode === currentMode) return;
  // Sync source from editor if leaving edit/source
  if ((currentMode === 'edit' || currentMode === 'source')) {
    currentSource = editor.value;
  }
  currentMode = mode;
  html.dataset.mode = mode;
  segs.forEach(b => {
    const on = b.dataset.mode === mode;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  if (mode === 'edit' || mode === 'source') {
    editor.value = currentSource;
    if (mode === 'edit') {
      await rerender();
      editor.focus();
    } else {
      editor.focus();
    }
  } else {
    await rerender();
  }
  updateStatusBar();
}

segs.forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));

// Cycle on E, but only when not typing in textarea/input
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && paletteOpen) { closePalette(); e.preventDefault(); return; }
  if (e.key === 'Escape' && document.body.classList.contains('graph-fullscreen')) {
    exitFullscreenGraph();
    e.preventDefault();
    return;
  }
  const typing = document.activeElement && (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT');
  if (!typing && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.key === 'ArrowLeft') {
    e.preventDefault();
    navigateHistory(-1);
    return;
  }
  if (!typing && e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.key === 'ArrowRight') {
    e.preventDefault();
    navigateHistory(1);
    return;
  }
  if ((e.ctrlKey || e.metaKey) && (e.key === 'p' || e.key === 'P')) {
    e.preventDefault();
    if (paletteOpen) closePalette(); else openPalette();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'f' || e.key === 'F') && !e.altKey) {
    e.preventDefault();
    openFind();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 's') { e.preventDefault(); save(); return; }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'n' || e.key === 'N') && !e.altKey) {
    e.preventDefault();
    openNoteCreateDialog();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'o') {
    e.preventDefault();
    openFile();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'w' || e.key === 'W')) {
    e.preventDefault();
    preview.classList.toggle('narrow');
    persistState();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'f' || e.key === 'F') && !e.altKey) {
    e.preventDefault();
    openWorkspaceSearch();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'g' || e.key === 'G') && !e.altKey) {
    e.preventDefault();
    toggleFullscreenGraph();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'o' || e.key === 'O') && !e.altKey) {
    e.preventDefault();
    openDirectory();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'h' || e.key === 'H') && !e.altKey) {
    e.preventDefault();
    openPalette('heading');
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.altKey && (e.key === 'i' || e.key === 'I')) {
    e.preventDefault();
    toggleRightPane();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && ['1','2','3'].includes(e.key)) {
    e.preventDefault();
    setMode({'1':'read','2':'edit','3':'source'}[e.key]);
    return;
  }
  if (!typing && (e.key === 'e' || e.key === 'E')) {
    e.preventDefault();
    setMode({read:'edit', edit:'source', source:'read'}[currentMode]);
  }
});

// ---------- KaTeX / Mermaid / highlight.js ----------

function renderMath(root) {
  if (window.renderMathInElement) {
    window.renderMathInElement(root, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false },
      ],
      throwOnError: false,
      ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
      ignoredClasses: ['mermaid'],
    });
  }
  for (const el of root.querySelectorAll('.math')) {
    if (el.dataset.rendered) continue;
    const display = el.classList.contains('math-display');
    try {
      window.katex.render(el.textContent, el, { displayMode: display, throwOnError: false });
      el.dataset.rendered = '1';
    } catch { /* leave raw */ }
  }
}

let mermaidInited = false;
async function renderMermaid(root) {
  if (!window.mermaid) return;
  if (!mermaidInited) {
    const dark = html.dataset.resolvedTheme === 'dark';
    window.mermaid.initialize({
      startOnLoad: false,
      theme: dark ? 'dark' : 'default',
      securityLevel: 'strict',
      fontFamily: 'var(--font-serif)',
    });
    mermaidInited = true;
  }
  const blocks = root.querySelectorAll('pre.mermaid');
  let i = 0;
  for (const el of blocks) {
    if (el.dataset.rendered) continue;
    const id = `mermaid-${Date.now()}-${i++}`;
    try {
      const { svg } = await window.mermaid.render(id, el.textContent);
      el.innerHTML = svg;
      el.dataset.rendered = '1';
    } catch (e) {
      el.textContent = `Mermaid error: ${e.message || e}`;
    }
  }
}

function highlightAndDecorate(root) {
  const blocks = root.querySelectorAll('pre.code-block > code[class*="language-"]');
  for (const code of blocks) {
    const pre = code.parentElement;
    if (pre.dataset.decorated) continue;
    const lang = (code.className.match(/language-(\S+)/) || [])[1] || '';
    // Highlight
    if (window.hljs) {
      try { window.hljs.highlightElement(code); } catch { /* ignore */ }
    }
    // Add language chip + copy header
    const header = document.createElement('div');
    header.className = 'code-header';
    const langSpan = document.createElement('span');
    langSpan.className = 'lang';
    langSpan.textContent = lang || 'text';
    const copy = document.createElement('button');
    copy.className = 'copy-btn';
    copy.type = 'button';
    copy.textContent = 'Copy';
    copy.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(code.textContent);
        copy.textContent = 'Copied';
        setTimeout(() => { copy.textContent = 'Copy'; }, 1200);
      } catch {
        flash('Copy failed');
      }
    });
    header.appendChild(langSpan);
    header.appendChild(copy);
    pre.insertBefore(header, code);
    pre.dataset.decorated = '1';
  }
}

async function enhance(root) {
  renderMath(root);
  await renderMermaid(root);
  highlightAndDecorate(root);
  buildOutline(root);
  wireHeadingCollapse(root);
  if (autoCollapseActive) applyAutoCollapse(root);
}
