// mdvw front-end glue — three-mode viewer/editor.

const html = document.documentElement;
const preview = document.getElementById('preview');
const editor = document.getElementById('editor');
const toast = document.getElementById('toast');
const fileChip = document.getElementById('file-chip');
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
const startMode = (bootstrapEl('md-start-mode').textContent.trim() || 'read');
let browseRoot = (bootstrapEl('md-browse-root')?.textContent || '').trim();
const uiState = JSON.parse(bootstrapEl('md-ui-state')?.textContent || '{}');

const getApi = () => (window.pywebview && window.pywebview.api) || null;

let currentSource = mdSource;
let currentMode = 'read';
let dirty = false;

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
  const typing = document.activeElement && (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT');
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

// ---------- Pane management ----------

const leftPane = document.getElementById('left-pane');
const rightPane = document.getElementById('right-pane');
const paneTabs = leftPane.querySelectorAll('.pane-tab');
const paneSections = leftPane.querySelectorAll('.pane-section');
let sessionsLoaded = false;
let leftPaneCollapsed = uiState.left_pane_collapsed ?? false;
let leftPaneWidth = uiState.left_pane_width ?? 280;
let leftPaneSection = uiState.left_pane_section ?? 'files';
let rightPaneCollapsed = uiState.right_pane_collapsed ?? true;
let rightPaneWidth = uiState.right_pane_width ?? 300;

function applyLeftPane() {
  if (leftPaneCollapsed) {
    mainEl.style.setProperty('--left-w', '0px');
    leftPane.hidden = true;
  } else {
    mainEl.style.setProperty('--left-w', leftPaneWidth + 'px');
    leftPane.hidden = false;
  }
}

function applyRightPane() {
  if (rightPaneCollapsed) {
    mainEl.style.setProperty('--right-w', '0px');
    rightPane.hidden = true;
  } else {
    mainEl.style.setProperty('--right-w', rightPaneWidth + 'px');
    rightPane.hidden = false;
  }
}

function showLeftSection(name) {
  leftPaneSection = name;
  paneTabs.forEach(t => {
    const on = t.dataset.section === name;
    t.classList.toggle('active', on);
    t.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  paneSections.forEach(s => {
    const on = s.id === `section-${name}`;
    s.classList.toggle('active', on);
    s.hidden = !on;
  });
  leftPaneCollapsed = false;
  applyLeftPane();
  persistState();
  // Lazy-load section data
  if (name === 'sessions' && !sessionsLoaded) loadSessions();
  if (name === 'files' && !browserLoaded && browseRoot) loadBrowser();
}

function toggleLeftPane() {
  leftPaneCollapsed = !leftPaneCollapsed;
  applyLeftPane();
  btnFiles.classList.toggle('active', !leftPaneCollapsed);
  persistState();
}

function toggleRightPane() {
  rightPaneCollapsed = !rightPaneCollapsed;
  applyRightPane();
  document.getElementById('btn-inspector').classList.toggle('active', !rightPaneCollapsed);
  persistState();
}

paneTabs.forEach(t => t.addEventListener('click', () => {
  if (t.dataset.section === leftPaneSection && !leftPaneCollapsed) {
    toggleLeftPane();
  } else {
    showLeftSection(t.dataset.section);
  }
}));

// Resize drag handlers
function setupResize(handleId, getWidth, setWidth, minW, maxW) {
  const handle = document.getElementById(handleId);
  if (!handle) return;
  handle.addEventListener('mousedown', (e) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = getWidth();
    handle.classList.add('dragging');
    const onMove = (e2) => {
      const isLeft = handleId === 'left-resize';
      const delta = isLeft ? e2.clientX - startX : startX - e2.clientX;
      setWidth(Math.max(minW, Math.min(maxW, startW + delta)));
    };
    const onUp = () => {
      handle.classList.remove('dragging');
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
      persistState();
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  });
}

setupResize('left-resize',
  () => leftPaneWidth,
  (w) => { leftPaneWidth = w; applyLeftPane(); },
  160, 500);

setupResize('right-resize',
  () => rightPaneWidth,
  (w) => { rightPaneWidth = w; applyRightPane(); },
  200, 500);

// State persistence
let persistTimer = 0;
function persistState() {
  clearTimeout(persistTimer);
  persistTimer = setTimeout(async () => {
    const api = getApi();
    if (api && api.save_ui_state) {
      await api.save_ui_state({
        left_pane_width: leftPaneWidth,
        left_pane_collapsed: leftPaneCollapsed,
        left_pane_section: leftPaneSection,
        right_pane_width: rightPaneWidth,
        right_pane_collapsed: rightPaneCollapsed,
        mode: currentMode,
        preview_narrow: preview.classList.contains('narrow'),
      });
    }
  }, 300);
}

// ---------- Command palette ----------

const paletteEl = document.getElementById('command-palette');
const paletteInput = document.getElementById('palette-input');
const paletteResults = document.getElementById('palette-results');
const paletteBackdrop = document.getElementById('palette-backdrop');
let paletteOpen = false;
let paletteActiveIdx = 0;
let paletteFiltered = [];

const commands = [];
function registerCommand(id, label, keys, action) {
  commands.push({ id, label, keys: keys || '', action });
}

let paletteMode = 'command'; // 'command' | 'heading'

function openPalette(mode) {
  paletteMode = mode || 'command';
  paletteOpen = true;
  paletteEl.hidden = false;
  paletteBackdrop.hidden = false;
  paletteInput.value = paletteMode === 'heading' ? '@' : '';
  paletteInput.placeholder = paletteMode === 'heading' ? 'Go to heading…' : 'Type a command…';
  paletteActiveIdx = 0;
  renderPaletteResults(paletteInput.value);
  paletteInput.focus();
}

function closePalette() {
  paletteOpen = false;
  paletteEl.hidden = true;
  paletteBackdrop.hidden = true;
}

function getHeadingItems() {
  const headings = preview.querySelectorAll('h1,h2,h3,h4,h5,h6');
  return Array.from(headings).map(h => ({
    label: h.textContent.trim(),
    level: parseInt(h.tagName[1], 10),
    el: h,
  }));
}

function renderPaletteResults(query) {
  const raw = query;
  const isHeadingMode = raw.startsWith('@');

  if (isHeadingMode) {
    const q = raw.slice(1).toLowerCase().trim();
    const items = getHeadingItems();
    paletteFiltered = q
      ? items.filter(h => h.label.toLowerCase().includes(q))
      : items;
    paletteResults.innerHTML = '';
    if (!paletteFiltered.length) {
      paletteResults.innerHTML = '<div class="palette-empty">No headings found</div>';
      return;
    }
    paletteFiltered.forEach((item, i) => {
      const div = document.createElement('div');
      div.className = 'palette-item' + (i === paletteActiveIdx ? ' active' : '');
      const labelSpan = document.createElement('span');
      labelSpan.className = 'palette-label';
      const lvlBadge = `<span class="palette-keys" style="margin-right:8px">H${item.level}</span>`;
      if (q) {
        const idx = item.label.toLowerCase().indexOf(q);
        const before = item.label.slice(0, idx);
        const match = item.label.slice(idx, idx + q.length);
        const after = item.label.slice(idx + q.length);
        labelSpan.innerHTML = `${lvlBadge}${escapeHtml(before)}<b>${escapeHtml(match)}</b>${escapeHtml(after)}`;
      } else {
        labelSpan.innerHTML = `${lvlBadge}${escapeHtml(item.label)}`;
      }
      // Indent based on level
      labelSpan.style.paddingLeft = ((item.level - 1) * 12) + 'px';
      div.appendChild(labelSpan);
      div.addEventListener('click', () => {
        closePalette();
        item.el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      div.addEventListener('mouseenter', () => {
        paletteActiveIdx = i;
        paletteResults.querySelectorAll('.palette-item').forEach((el, j) =>
          el.classList.toggle('active', j === i));
      });
      paletteResults.appendChild(div);
    });
    return;
  }

  // File search mode (no prefix, when browse root exists)
  if (raw.trim() && !raw.startsWith('>') && browseRoot && paletteMode === 'command') {
    // Search both commands and filenames
    const q = raw.toLowerCase().trim();
    const cmdMatches = commands.filter(c => c.label.toLowerCase().includes(q));
    // Trigger async file search
    searchFilenames(q);
    paletteFiltered = cmdMatches;
    // Render commands first, file results will append asynchronously
    renderPaletteCommandItems(q, cmdMatches);
    return;
  }

  // Command mode
  const q = raw.toLowerCase().trim();
  paletteFiltered = q
    ? commands.filter(c => c.label.toLowerCase().includes(q))
    : [...commands];
  paletteResults.innerHTML = '';
  if (!paletteFiltered.length) {
    paletteResults.innerHTML = '<div class="palette-empty">No matching commands</div>';
    return;
  }
  paletteFiltered.forEach((cmd, i) => {
    const div = document.createElement('div');
    div.className = 'palette-item' + (i === paletteActiveIdx ? ' active' : '');
    const labelSpan = document.createElement('span');
    labelSpan.className = 'palette-label';
    if (q) {
      const idx = cmd.label.toLowerCase().indexOf(q);
      const before = cmd.label.slice(0, idx);
      const match = cmd.label.slice(idx, idx + q.length);
      const after = cmd.label.slice(idx + q.length);
      labelSpan.innerHTML = `${escapeHtml(before)}<b>${escapeHtml(match)}</b>${escapeHtml(after)}`;
    } else {
      labelSpan.textContent = cmd.label;
    }
    div.appendChild(labelSpan);
    if (cmd.keys) {
      const keysSpan = document.createElement('span');
      keysSpan.className = 'palette-keys';
      keysSpan.textContent = cmd.keys;
      div.appendChild(keysSpan);
    }
    div.addEventListener('click', () => { closePalette(); cmd.action(); });
    div.addEventListener('mouseenter', () => {
      paletteActiveIdx = i;
      paletteResults.querySelectorAll('.palette-item').forEach((el, j) =>
        el.classList.toggle('active', j === i));
    });
    paletteResults.appendChild(div);
  });
}

function escapeHtml(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

paletteInput.addEventListener('input', () => {
  paletteActiveIdx = 0;
  renderPaletteResults(paletteInput.value);
});

paletteInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closePalette(); e.preventDefault(); return; }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    paletteActiveIdx = Math.min(paletteActiveIdx + 1, paletteFiltered.length - 1);
    updatePaletteActive();
    return;
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    paletteActiveIdx = Math.max(paletteActiveIdx - 1, 0);
    updatePaletteActive();
    return;
  }
  if (e.key === 'Enter') {
    e.preventDefault();
    const item = paletteFiltered[paletteActiveIdx];
    if (item) {
      closePalette();
      if (item.action) item.action(); // command mode
      else if (item.el) item.el.scrollIntoView({ behavior: 'smooth', block: 'start' }); // heading mode
    }
    return;
  }
});

function updatePaletteActive() {
  paletteResults.querySelectorAll('.palette-item').forEach((el, i) => {
    const on = i === paletteActiveIdx;
    el.classList.toggle('active', on);
    if (on) el.scrollIntoView({ block: 'nearest' });
  });
}

paletteBackdrop.addEventListener('click', closePalette);

let fileSearchTimer = 0;
function searchFilenames(query) {
  clearTimeout(fileSearchTimer);
  fileSearchTimer = setTimeout(async () => {
    if (!paletteOpen) return;
    const api = getApi();
    if (!api || !api.search_filenames) return;
    const results = await api.search_filenames(query);
    if (!paletteOpen || paletteInput.value.startsWith('@')) return;
    // Append file results to palette
    if (results && results.length) {
      const sep = document.createElement('div');
      sep.className = 'palette-empty';
      sep.style.padding = '4px 16px';
      sep.style.fontSize = '10px';
      sep.style.letterSpacing = '0.1em';
      sep.textContent = 'FILES';
      paletteResults.appendChild(sep);
      for (const f of results) {
        const existing = paletteFiltered.length;
        paletteFiltered.push({ action: () => openPathFromPalette(f.path), label: f.name, path: f.relative });
        const div = document.createElement('div');
        div.className = 'palette-item';
        const labelSpan = document.createElement('span');
        labelSpan.className = 'palette-label';
        labelSpan.textContent = f.name;
        const pathSpan = document.createElement('span');
        pathSpan.className = 'palette-keys';
        pathSpan.textContent = f.relative;
        div.appendChild(labelSpan);
        div.appendChild(pathSpan);
        const idx = existing + paletteResults.querySelectorAll('.palette-empty').length - 1;
        div.addEventListener('click', () => { closePalette(); openPathFromPalette(f.path); });
        paletteResults.appendChild(div);
      }
    }
  }, 150);
}

async function openPathFromPalette(path) {
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (api && api.open_path) {
    const ok = await api.open_path(path);
    if (!ok) flash('Could not open file');
  }
}

function renderPaletteCommandItems(q, cmdMatches) {
  paletteResults.innerHTML = '';
  if (!cmdMatches.length) {
    // File results will populate asynchronously
    return;
  }
  cmdMatches.forEach((cmd, i) => {
    const div = document.createElement('div');
    div.className = 'palette-item' + (i === paletteActiveIdx ? ' active' : '');
    const labelSpan = document.createElement('span');
    labelSpan.className = 'palette-label';
    if (q) {
      const idx = cmd.label.toLowerCase().indexOf(q);
      const before = cmd.label.slice(0, idx);
      const match = cmd.label.slice(idx, idx + q.length);
      const after = cmd.label.slice(idx + q.length);
      labelSpan.innerHTML = `${escapeHtml(before)}<b>${escapeHtml(match)}</b>${escapeHtml(after)}`;
    } else {
      labelSpan.textContent = cmd.label;
    }
    div.appendChild(labelSpan);
    if (cmd.keys) {
      const keysSpan = document.createElement('span');
      keysSpan.className = 'palette-keys';
      keysSpan.textContent = cmd.keys;
      div.appendChild(keysSpan);
    }
    div.addEventListener('click', () => { closePalette(); cmd.action(); });
    paletteResults.appendChild(div);
  });
}

// Register built-in commands
registerCommand('mode.read', 'Read Mode', 'Ctrl+1', () => setMode('read'));
registerCommand('mode.edit', 'Edit Mode', 'Ctrl+2', () => setMode('edit'));
registerCommand('mode.source', 'Source Mode', 'Ctrl+3', () => setMode('source'));
registerCommand('file.open', 'Open File', 'Ctrl+O', () => openFile());
registerCommand('file.open_dir', 'Open Directory', 'Ctrl+Shift+O', () => openDirectory());
registerCommand('file.save', 'Save', 'Ctrl+S', () => save());
registerCommand('pane.files', 'Show Files', '', () => { loadBrowser(); showLeftSection('files'); });
registerCommand('pane.outline', 'Show Outline', '', () => showLeftSection('outline'));
registerCommand('pane.toggle_left', 'Toggle Left Pane', '', () => toggleLeftPane());
registerCommand('view.inspector', 'Toggle Inspector', 'Ctrl+Alt+I', () => toggleRightPane());
registerCommand('view.width', 'Toggle Preview Width', 'Ctrl+Shift+W', () => {
  preview.classList.toggle('narrow'); updateWidthIcon(); persistState();
});
registerCommand('view.theme', 'Cycle Theme', '', () => {
  const cur = html.dataset.theme || 'auto';
  const next = cur === 'auto' ? 'light' : cur === 'light' ? 'dark' : 'auto';
  html.dataset.theme = next; resolveTheme(); mermaidInited = false;
  flash(`Theme: ${next}`);
  if (currentMode !== 'source') rerender();
});
registerCommand('navigate.heading', 'Go to Heading', 'Ctrl+Shift+H', () => openPalette('heading'));
registerCommand('help', 'Keyboard Shortcuts', '', () => helpDialog.showModal());

// ---------- Inspector ----------

const inspFm = document.getElementById('insp-fm');
const inspStats = document.getElementById('insp-stats');

// Export buttons
async function preparePrint() {
  // Source mode doesn't rerender on input, and edit mode rerenders on a
  // debounce — either can leave #preview stale when the user hits Print.
  // Sync the current buffer and force a fresh render so what prints is
  // what's in the editor, not an older preview snapshot.
  if (currentMode === 'edit' || currentMode === 'source') {
    currentSource = editor.value;
  }
  await rerender();
}

document.getElementById('btn-export-print').addEventListener('click', async () => {
  await preparePrint();
  const api = getApi();
  if (api && api.print_document) await api.print_document();
});
document.getElementById('btn-export-html').addEventListener('click', async () => {
  const api = getApi();
  if (!api || !api.export_html) { flash('Export unavailable'); return; }
  const content = (currentMode === 'edit' || currentMode === 'source') ? editor.value : currentSource;
  const result = await api.export_html(content);
  if (result && result.status === 'ok') flash('Exported HTML');
  else if (result && result.status === 'error') flash(`Export failed: ${result.message}`);
});

registerCommand('export.print', 'Print', '', async () => {
  await preparePrint();
  const api = getApi();
  if (api && api.print_document) await api.print_document();
});
registerCommand('export.html', 'Export HTML', '', async () => {
  const api = getApi();
  if (!api || !api.export_html) return;
  const content = (currentMode === 'edit' || currentMode === 'source') ? editor.value : currentSource;
  const result = await api.export_html(content);
  if (result && result.status === 'ok') flash('Exported HTML');
  else if (result && result.status === 'error') flash(`Export failed: ${result.message}`);
});

document.getElementById('btn-inspector-close').addEventListener('click', () => {
  rightPaneCollapsed = true;
  applyRightPane();
  document.getElementById('btn-inspector').classList.remove('active');
  persistState();
});

async function updateInspector() {
  // Frontmatter
  const api = getApi();
  if (api && api.parse_frontmatter_fields) {
    const fields = await api.parse_frontmatter_fields(currentSource);
    if (fields && typeof fields === 'object' && Object.keys(fields).length > 0) {
      let html = '<table>';
      for (const [k, v] of Object.entries(fields)) {
        const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
        html += `<tr><td>${escapeHtml(k)}</td><td>${escapeHtml(val)}</td></tr>`;
      }
      html += '</table>';
      inspFm.innerHTML = html;
    } else {
      inspFm.innerHTML = '<div class="inspector-placeholder">No frontmatter</div>';
    }
  }

  // Stats
  const text = currentSource || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const chars = text.length;
  const headings = (text.match(/^#{1,6}\s/gm) || []).length;
  const readMin = Math.max(1, Math.ceil(words / 250));
  inspStats.innerHTML = [
    statRow('Words', words.toLocaleString()),
    statRow('Characters', chars.toLocaleString()),
    statRow('Headings', headings),
    statRow('Reading time', `~${readMin} min`),
  ].join('');
}

function statRow(label, value) {
  return `<div class="insp-stat-row"><span class="stat-label">${escapeHtml(label)}</span><span class="stat-value">${escapeHtml(String(value))}</span></div>`;
}

// ---------- Status bar ----------

const sbMode = document.getElementById('sb-mode');
const sbSave = document.getElementById('sb-save');
const sbWords = document.getElementById('sb-words');
const sbCursor = document.getElementById('sb-cursor');

function updateStatusBar() {
  sbMode.textContent = { read: 'Read', edit: 'Edit', source: 'Source' }[currentMode] || 'Read';
  sbSave.textContent = dirty ? 'Modified' : 'Saved';
  const text = currentSource || '';
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  sbWords.textContent = `${words.toLocaleString()} words`;
  // Cursor position only in editor modes
  const showCursor = currentMode === 'edit' || currentMode === 'source';
  sbCursor.hidden = !showCursor;
}

function updateCursorPosition() {
  if (currentMode !== 'edit' && currentMode !== 'source') return;
  const pos = editor.selectionStart;
  const text = editor.value.substring(0, pos);
  const lines = text.split('\n');
  const line = lines.length;
  const col = lines[lines.length - 1].length + 1;
  sbCursor.textContent = `Ln ${line}, Col ${col}`;
  sbCursor.hidden = false;
}

editor.addEventListener('click', updateCursorPosition);
editor.addEventListener('keyup', updateCursorPosition);

sbMode.addEventListener('click', () => {
  setMode({ read: 'edit', edit: 'source', source: 'read' }[currentMode]);
});

// ---------- Find in document ----------

const findBar = document.getElementById('find-bar');
const findInput = document.getElementById('find-input');
const findCount = document.getElementById('find-count');
const findCaseCheck = document.getElementById('find-case');
const findWholeCheck = document.getElementById('find-whole');
let findMatches = [];
let findCurrentIdx = -1;
let findMarks = [];

function openFind() {
  findBar.hidden = false;
  findInput.focus();
  findInput.select();
  runFind();
}

function closeFind() {
  findBar.hidden = true;
  clearFindHighlights();
  findCount.textContent = '';
}

function runFind() {
  clearFindHighlights();
  const query = findInput.value;
  if (!query) { findCount.textContent = ''; findMatches = []; findCurrentIdx = -1; return; }
  const caseSensitive = findCaseCheck.checked;
  const wholeWord = findWholeCheck.checked;

  if (currentMode === 'read' || currentMode === 'edit') {
    findInPreview(query, caseSensitive, wholeWord);
  } else {
    findInEditor(query, caseSensitive, wholeWord);
  }

  if (findMatches.length > 0) {
    findCurrentIdx = 0;
    highlightCurrentMatch();
    findCount.textContent = `1 of ${findMatches.length}`;
  } else {
    findCurrentIdx = -1;
    findCount.textContent = 'No results';
  }
}

function findInPreview(query, caseSensitive, wholeWord) {
  findMatches = [];
  findMarks = [];
  const walker = document.createTreeWalker(preview, NodeFilter.SHOW_TEXT, null);
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) textNodes.push(node);

  const flags = caseSensitive ? 'g' : 'gi';
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = wholeWord ? `\\b${escaped}\\b` : escaped;
  const re = new RegExp(pattern, flags);

  for (const textNode of textNodes) {
    const text = textNode.textContent;
    let m;
    const matches = [];
    while ((m = re.exec(text)) !== null) matches.push({ start: m.index, end: m.index + m[0].length });
    if (!matches.length) continue;

    // Split the text node and wrap matches in <mark>
    const parent = textNode.parentNode;
    const frag = document.createDocumentFragment();
    let lastIdx = 0;
    for (const { start, end } of matches) {
      if (start > lastIdx) frag.appendChild(document.createTextNode(text.slice(lastIdx, start)));
      const mark = document.createElement('mark');
      mark.className = 'find-highlight';
      mark.textContent = text.slice(start, end);
      frag.appendChild(mark);
      findMarks.push(mark);
      findMatches.push(mark);
      lastIdx = end;
    }
    if (lastIdx < text.length) frag.appendChild(document.createTextNode(text.slice(lastIdx)));
    parent.replaceChild(frag, textNode);
  }
}

function findInEditor(query, caseSensitive, wholeWord) {
  findMatches = [];
  const text = editor.value;
  const flags = caseSensitive ? 'g' : 'gi';
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = wholeWord ? `\\b${escaped}\\b` : escaped;
  const re = new RegExp(pattern, flags);
  let m;
  while ((m = re.exec(text)) !== null) {
    findMatches.push({ start: m.index, end: m.index + m[0].length });
  }
}

function highlightCurrentMatch() {
  if (findCurrentIdx < 0 || findCurrentIdx >= findMatches.length) return;

  if (currentMode === 'read' || currentMode === 'edit') {
    // Preview mode: update mark classes
    findMarks.forEach((m, i) => {
      m.className = i === findCurrentIdx ? 'find-highlight-current' : 'find-highlight';
    });
    findMatches[findCurrentIdx].scrollIntoView({ block: 'center', behavior: 'smooth' });
  } else {
    // Editor mode: select the match
    const match = findMatches[findCurrentIdx];
    editor.focus();
    editor.setSelectionRange(match.start, match.end);
    // Scroll into view by briefly focusing
    editor.blur();
    editor.focus();
  }
}

function clearFindHighlights() {
  // Restore text nodes from marks
  for (const mark of findMarks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    const text = document.createTextNode(mark.textContent);
    parent.replaceChild(text, mark);
    parent.normalize();
  }
  findMarks = [];
  findMatches = [];
  findCurrentIdx = -1;
}

function findNext() {
  if (!findMatches.length) return;
  findCurrentIdx = (findCurrentIdx + 1) % findMatches.length;
  highlightCurrentMatch();
  findCount.textContent = `${findCurrentIdx + 1} of ${findMatches.length}`;
}

function findPrev() {
  if (!findMatches.length) return;
  findCurrentIdx = (findCurrentIdx - 1 + findMatches.length) % findMatches.length;
  highlightCurrentMatch();
  findCount.textContent = `${findCurrentIdx + 1} of ${findMatches.length}`;
}

findInput.addEventListener('input', runFind);
findCaseCheck.addEventListener('change', runFind);
findWholeCheck.addEventListener('change', runFind);
document.getElementById('find-next').addEventListener('click', findNext);
document.getElementById('find-prev').addEventListener('click', findPrev);
document.getElementById('find-close').addEventListener('click', closeFind);

findInput.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeFind(); e.preventDefault(); return; }
  if (e.key === 'Enter') {
    e.preventDefault();
    if (e.shiftKey) findPrev(); else findNext();
  }
});

registerCommand('find.open', 'Find in Document', 'Ctrl+F', () => openFind());

// ---------- Outline ----------

const outlineNav = document.getElementById('outline-nav');

function slugify(text, used) {
  let s = text.toLowerCase().trim()
    .replace(/[^\w\s-]/g, '').replace(/\s+/g, '-').replace(/-+/g, '-');
  if (!s) s = 'section';
  let out = s, i = 2;
  while (used.has(out)) out = `${s}-${i++}`;
  used.add(out);
  return out;
}

function buildOutline(root) {
  outlineNav.innerHTML = '';
  const headings = root.querySelectorAll('h1,h2,h3,h4,h5,h6');
  if (!headings.length) { outlineNav.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12.5px">No headings</div>'; return; }
  const used = new Set();
  for (const h of headings) {
    if (!h.id) h.id = slugify(h.textContent, used);
    else used.add(h.id);
    const a = document.createElement('a');
    a.href = `#${h.id}`;
    a.dataset.lvl = h.tagName[1];
    a.textContent = h.textContent.trim();
    a.addEventListener('click', (e) => {
      e.preventDefault();
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    outlineNav.appendChild(a);
  }
}

// Active-heading tracking
const activeObserver = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    const id = entry.target.id;
    outlineNav.querySelectorAll('a').forEach(a => a.classList.toggle('active', a.getAttribute('href') === `#${id}`));
    break;
  }
}, { root: preview, rootMargin: '-20% 0px -70% 0px' });
function observeHeadings(root) {
  activeObserver.disconnect();
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5,h6')) activeObserver.observe(h);
}

// ---------- Heading collapse ----------

function headingLevel(el) {
  return el && /^H[1-6]$/.test(el.tagName) ? parseInt(el.tagName[1], 10) : 0;
}

function toggleHeading(heading, collapsed) {
  const lvl = headingLevel(heading);
  if (!lvl) return;
  const target = collapsed === undefined ? heading.dataset.collapsed !== 'true' : collapsed;
  heading.dataset.collapsed = target ? 'true' : 'false';
  let el = heading.nextElementSibling;
  let skipUntil = 0;
  while (el) {
    const l = headingLevel(el);
    if (l && l <= lvl) break;
    if (target) {
      el.classList.add('mdvw-hidden');
    } else {
      if (skipUntil) {
        if (l && l <= skipUntil) skipUntil = 0;
        else { el = el.nextElementSibling; continue; }
      }
      el.classList.remove('mdvw-hidden');
      if (l && el.dataset.collapsed === 'true') skipUntil = l;
    }
    el = el.nextElementSibling;
  }
}

function headingKey(h) {
  return h.id || `${h.tagName}-${h.textContent.trim()}`;
}
const manualOverrides = new Set();

function wireHeadingCollapse(root) {
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    if (h.dataset.collapseWired) continue;
    h.dataset.collapseWired = '1';
    h.addEventListener('click', (e) => {
      const rect = h.getBoundingClientRect();
      if (e.clientX - rect.left > 28) return;
      toggleHeading(h);
      if (autoCollapseActive && headingLevel(h) >= 2) {
        const key = headingKey(h);
        if (h.dataset.collapsed === 'true') manualOverrides.delete(key);
        else manualOverrides.add(key);
      }
    });
  }
  observeHeadings(root);
}

let autoCollapseActive = false;

function collapseAll(root) {
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5,h6')) toggleHeading(h, true);
}
function expandAll(root) {
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5,h6')) toggleHeading(h, false);
}
function applyAutoCollapse(root) {
  for (const h of root.querySelectorAll('h1')) toggleHeading(h, false);
  for (const h of root.querySelectorAll('h2,h3,h4,h5,h6')) toggleHeading(h, true);
  for (const h of root.querySelectorAll('h2,h3,h4,h5,h6')) {
    if (manualOverrides.has(headingKey(h))) toggleHeading(h, false);
  }
}

const btnCollapseAll = document.getElementById('btn-collapse-all');
const btnExpandAll = document.getElementById('btn-expand-all');
const btnAutoCollapse = document.getElementById('btn-auto-collapse');

btnCollapseAll.addEventListener('click', () => {
  autoCollapseActive = false;
  manualOverrides.clear();
  btnAutoCollapse.classList.remove('active');
  collapseAll(preview);
});
btnExpandAll.addEventListener('click', () => {
  autoCollapseActive = false;
  manualOverrides.clear();
  btnAutoCollapse.classList.remove('active');
  expandAll(preview);
});
btnAutoCollapse.addEventListener('click', () => {
  autoCollapseActive = !autoCollapseActive;
  btnAutoCollapse.classList.toggle('active', autoCollapseActive);
  if (autoCollapseActive) { manualOverrides.clear(); applyAutoCollapse(preview); }
});

// ---------- File browser (only when launched without a file arg) ----------

const browserNav = document.getElementById('browser-nav');
const btnFiles = document.getElementById('btn-files');
let browserLoaded = false;

function renderEntries(entries, parent) {
  if (!Array.isArray(entries) || entries.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'browser-empty';
    empty.textContent = '(empty)';
    parent.appendChild(empty);
    return;
  }
  const ul = document.createElement('ul');
  for (const e of entries) {
    const li = document.createElement('li');
    if (e.type === 'dir') {
      const details = document.createElement('details');
      details.dataset.path = e.path;
      const summary = document.createElement('summary');
      summary.textContent = e.name;
      details.appendChild(summary);
      // Lazy: only fetch children when the user actually expands the folder.
      details.addEventListener('toggle', () => {
        if (details.open && !details.dataset.loaded) loadDir(details);
      });
      li.appendChild(details);
    } else {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'file-link';
      btn.dataset.path = e.path;
      btn.textContent = e.name;
      btn.title = e.path;
      li.appendChild(btn);
    }
    ul.appendChild(li);
  }
  parent.appendChild(ul);
}

async function loadDir(details) {
  if (details.dataset.loaded) return;
  details.dataset.loaded = '1';
  const placeholder = document.createElement('div');
  placeholder.className = 'browser-empty';
  placeholder.textContent = 'Loading…';
  details.appendChild(placeholder);
  const api = await whenApiReady();
  let result = null;
  if (api && api.list_markdown_dir) {
    try { result = await api.list_markdown_dir(details.dataset.path); }
    catch { /* leave entries empty */ }
  }
  placeholder.remove();
  renderEntries(result ? result.entries : [], details);
}

function whenApiReady() {
  // pywebview injects `window.pywebview.api` asynchronously and fires a
  // `pywebviewready` event. During module init the API can still be null;
  // fall back to a short poll so we don't silently drop the call.
  return new Promise((resolve) => {
    if (getApi()) { resolve(getApi()); return; }
    const done = () => {
      window.removeEventListener('pywebviewready', done);
      resolve(getApi());
    };
    window.addEventListener('pywebviewready', done, { once: true });
    // Safety net in case the event already fired before we listened.
    let tries = 0;
    const tick = () => {
      if (getApi()) { window.removeEventListener('pywebviewready', done); resolve(getApi()); return; }
      if (tries++ < 50) setTimeout(tick, 40);
      else resolve(null);
    };
    setTimeout(tick, 40);
  });
}

async function loadBrowser() {
  if (browserLoaded) return;
  const api = await whenApiReady();
  if (!api || !api.list_markdown_dir) return;
  const result = await api.list_markdown_dir('');
  browserNav.innerHTML = '';
  if (!result) {
    browserNav.innerHTML = '<div class="browser-empty">File browser unavailable.</div>';
    browserLoaded = true;
    return;
  }
  const rootInfo = document.createElement('div');
  rootInfo.className = 'browser-empty';
  rootInfo.style.fontFamily = 'var(--font-mono)';
  rootInfo.style.fontSize = '11.5px';
  rootInfo.style.wordBreak = 'break-all';
  rootInfo.textContent = result.path;
  browserNav.appendChild(rootInfo);
  renderEntries(result.entries, browserNav);
  browserLoaded = true;
}

browserNav.addEventListener('click', async (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('.file-link') : null;
  if (!btn) return;
  e.preventDefault();
  const path = btn.dataset.path;
  if (!path) return;
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.open_path) return;
  const ok = await api.open_path(path);
  if (ok) {
    browserNav.querySelectorAll('.file-link.active').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
  } else {
    flash('Could not open file');
  }
});

btnFiles.addEventListener('click', async () => {
  if (!browseRoot) { flash('File browser unavailable'); return; }
  if (leftPaneSection === 'files' && !leftPaneCollapsed) {
    toggleLeftPane();
  } else {
    await loadBrowser();
    showLeftSection('files');
  }
});
// Auto-open the sidebar on first paint when no specific file was passed.
if (browseRoot && !mdPath) {
  loadBrowser().then(() => showLeftSection('files'));
}

// ---------- Diagnostics ----------

const diagList = document.getElementById('diagnostics-list');
const sbDiagnostics = document.getElementById('sb-diagnostics');
let diagDebounce = 0;
let lastDiagIssues = [];

async function runDiagnostics() {
  const api = getApi();
  if (!api || !api.run_diagnostics) return;
  const issues = await api.run_diagnostics(currentSource);
  lastDiagIssues = issues || [];
  renderDiagnostics(lastDiagIssues);
  updateDiagBadge(lastDiagIssues);
}

function renderDiagnostics(issues) {
  diagList.innerHTML = '';
  if (!issues.length) {
    diagList.innerHTML = '<div class="diag-empty">No issues found</div>';
    return;
  }
  const icons = { error: '●', warning: '▲', info: 'ℹ' };
  for (const issue of issues) {
    const div = document.createElement('div');
    div.className = 'diag-item';
    const icon = document.createElement('span');
    icon.className = `diag-icon diag-icon-${issue.severity}`;
    icon.textContent = icons[issue.severity] || '●';
    const msg = document.createElement('span');
    msg.className = 'diag-msg';
    msg.textContent = issue.message;
    div.appendChild(icon);
    div.appendChild(msg);
    if (issue.line) {
      const line = document.createElement('span');
      line.className = 'diag-line';
      line.textContent = `L${issue.line}`;
      div.appendChild(line);
    }
    diagList.appendChild(div);
  }
}

function updateDiagBadge(issues) {
  const errors = issues.filter(i => i.severity === 'error').length;
  const warnings = issues.filter(i => i.severity === 'warning').length;
  const total = errors + warnings;
  if (total > 0) {
    sbDiagnostics.hidden = false;
    sbDiagnostics.innerHTML = errors > 0
      ? `<span class="sb-diag-badge">${errors}</span> ${warnings > 0 ? `${warnings}⚠` : ''}`
      : `${warnings}⚠`;
  } else {
    sbDiagnostics.hidden = true;
  }
}

function scheduleDiagnostics() {
  clearTimeout(diagDebounce);
  diagDebounce = setTimeout(runDiagnostics, 500);
}

sbDiagnostics.addEventListener('click', () => showLeftSection('diagnostics'));

registerCommand('diagnostics.show', 'Show Diagnostics', '', () => showLeftSection('diagnostics'));

// ---------- Workspace search ----------

const wsSearchInput = document.getElementById('ws-search-input');
const wsSearchResults = document.getElementById('ws-search-results');
const wsSearchCase = document.getElementById('ws-search-case');
let wsSearchTimer = 0;

function openWorkspaceSearch() {
  showLeftSection('search');
  wsSearchInput.focus();
  wsSearchInput.select();
}

async function runWorkspaceSearch() {
  const query = wsSearchInput.value.trim();
  if (!query) { wsSearchResults.innerHTML = ''; return; }
  const api = getApi();
  if (!api || !api.search_workspace) {
    wsSearchResults.innerHTML = '<div class="ws-search-empty">Search unavailable</div>';
    return;
  }
  wsSearchResults.innerHTML = '<div class="ws-search-empty">Searching…</div>';
  const caseSensitive = wsSearchCase.checked;
  const results = await api.search_workspace(query, caseSensitive);
  wsSearchResults.innerHTML = '';
  if (!results || !results.length) {
    wsSearchResults.innerHTML = '<div class="ws-search-empty">No results</div>';
    return;
  }
  // Group by file
  const groups = new Map();
  for (const r of results) {
    if (!groups.has(r.path)) groups.set(r.path, { name: r.name, relative: r.relative, hits: [] });
    groups.get(r.path).hits.push(r);
  }
  for (const [filePath, group] of groups) {
    const header = document.createElement('div');
    header.className = 'ws-search-group';
    header.textContent = group.relative;
    header.title = filePath;
    wsSearchResults.appendChild(header);
    for (const hit of group.hits) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'ws-search-hit';
      btn.dataset.path = hit.path;
      const lineSpan = document.createElement('span');
      lineSpan.className = 'ws-search-line';
      lineSpan.textContent = `${hit.line}:`;
      btn.appendChild(lineSpan);
      // Highlight the match in context
      const ctx = hit.context;
      const qi = query.toLowerCase();
      const idx = caseSensitive ? ctx.indexOf(query) : ctx.toLowerCase().indexOf(qi);
      if (idx >= 0) {
        btn.appendChild(document.createTextNode(ctx.slice(0, idx)));
        const mark = document.createElement('span');
        mark.className = 'ws-search-match';
        mark.textContent = ctx.slice(idx, idx + query.length);
        btn.appendChild(mark);
        btn.appendChild(document.createTextNode(ctx.slice(idx + query.length)));
      } else {
        btn.appendChild(document.createTextNode(ctx));
      }
      btn.addEventListener('click', async () => {
        if (!(await confirmDiscardIfDirty())) return;
        const api2 = getApi();
        if (api2 && api2.open_path) {
          pendingHighlight = { path: hit.path, query, caseSensitive };
          const ok = await api2.open_path(hit.path);
          if (!ok) {
            pendingHighlight = null;
            flash('Could not open file');
          }
        }
      });
      wsSearchResults.appendChild(btn);
    }
  }
}

wsSearchInput.addEventListener('input', () => {
  clearTimeout(wsSearchTimer);
  wsSearchTimer = setTimeout(runWorkspaceSearch, 300);
});
wsSearchCase.addEventListener('change', () => {
  if (wsSearchInput.value.trim()) runWorkspaceSearch();
});
wsSearchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); runWorkspaceSearch(); }
  if (e.key === 'Escape') { e.preventDefault(); wsSearchInput.blur(); }
});

registerCommand('search.workspace', 'Search Workspace', 'Ctrl+Shift+F', () => openWorkspaceSearch());

// ---------- Sessions / Recent files ----------

const recentList = document.getElementById('recent-list');

async function loadSessions() {
  const api = await whenApiReady();
  if (!api || !api.get_recent_files) return;
  const files = await api.get_recent_files();
  recentList.innerHTML = '';
  if (!files || !files.length) {
    recentList.innerHTML = '<div class="recent-empty">No recent files</div>';
    sessionsLoaded = true;
    return;
  }
  for (const f of files) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'recent-item' + (f.exists ? '' : ' recent-item-missing');
    btn.dataset.path = f.path;
    btn.title = f.exists ? f.path : `${f.path} (not found)`;
    const nameSpan = document.createElement('span');
    nameSpan.className = 'recent-item-name';
    nameSpan.textContent = f.name;
    const pathSpan = document.createElement('span');
    pathSpan.className = 'recent-item-path';
    pathSpan.textContent = f.path;
    btn.appendChild(nameSpan);
    btn.appendChild(pathSpan);
    recentList.appendChild(btn);
  }
  const clearBtn = document.createElement('button');
  clearBtn.type = 'button';
  clearBtn.className = 'recent-clear';
  clearBtn.textContent = 'Clear recent files';
  clearBtn.addEventListener('click', async () => {
    const api = getApi();
    if (api && api.clear_recent_files) await api.clear_recent_files();
    recentList.innerHTML = '<div class="recent-empty">No recent files</div>';
  });
  recentList.appendChild(clearBtn);
  sessionsLoaded = true;
}

recentList.addEventListener('click', async (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('.recent-item') : null;
  if (!btn) return;
  const path = btn.dataset.path;
  if (!path) return;
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.open_recent) return;
  const ok = await api.open_recent(path);
  if (ok) {
    sessionsLoaded = false; // refresh list next time
  } else {
    flash('Could not open file');
  }
});

// Refresh sessions list when switching to the sessions tab
const origShowLeftSection = showLeftSection;

registerCommand('session.recent', 'Show Recent Files', '', () => {
  loadSessions();
  showLeftSection('sessions');
});
registerCommand('session.clear', 'Clear Recent Files', '', async () => {
  const api = getApi();
  if (api && api.clear_recent_files) await api.clear_recent_files();
  sessionsLoaded = false;
  flash('Recent files cleared');
});

// ---------- Theme ----------

function syncTitlebarTheme(dark) {
  const api = getApi();
  if (!api || !api.set_titlebar_dark) return;
  try { Promise.resolve(api.set_titlebar_dark(dark)).catch(() => {}); }
  catch { /* bridge not ready — non-fatal */ }
}

function resolveTheme() {
  const attr = html.dataset.theme;
  const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const resolved = attr === 'auto' ? (sysDark ? 'dark' : 'light') : attr;
  html.dataset.resolvedTheme = resolved;
  syncTitlebarTheme(resolved === 'dark');
  return resolved;
}
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  resolveTheme();
  mermaidInited = false;
  if (currentMode !== 'source') rerender();
});
resolveTheme();
// The first resolveTheme() runs before pywebview has injected its bridge,
// so the Python-side `_on_loaded` handler paints the initial title bar
// from the system registry. Re-sync here so any later divergence between
// app theme and system theme (e.g. explicit user toggle) is honoured.
window.addEventListener('pywebviewready', () => {
  syncTitlebarTheme(html.dataset.resolvedTheme === 'dark');
}, { once: true });

document.getElementById('btn-theme').addEventListener('click', () => {
  const cur = html.dataset.theme || 'auto';
  const next = cur === 'auto' ? 'light' : cur === 'light' ? 'dark' : 'auto';
  html.dataset.theme = next;
  resolveTheme();
  mermaidInited = false;
  flash(`Theme: ${next}`);
  if (currentMode !== 'source') rerender();
});

document.getElementById('btn-inspector').addEventListener('click', () => toggleRightPane());

// ---------- Open/Save ----------

const unsavedPrompt = document.getElementById('unsaved-prompt');

async function confirmDiscardIfDirty() {
  if (!dirty) return true;
  const choice = await new Promise((resolve) => {
    unsavedPrompt.addEventListener('close', () => resolve(unsavedPrompt.returnValue || 'cancel'), { once: true });
    unsavedPrompt.showModal();
  });
  if (choice === 'cancel') return false;
  if (choice === 'discard') return true;
  if (choice === 'save') {
    await save();
    // If save failed (e.g. user cancelled save-as), dirty stays true → block.
    return !dirty;
  }
  return false;
}

async function openFile() {
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (api && api.open_file) await api.open_file();
}
async function openDirectory() {
  // Switching workspaces only updates _browse_root / refreshes the
  // sidebar; the current document and its dirty state are preserved,
  // so no confirmDiscardIfDirty() gate is needed here.
  const api = getApi();
  if (api && api.open_directory) await api.open_directory();
}
document.getElementById('btn-open').addEventListener('click', openFile);
document.getElementById('btn-open-dir').addEventListener('click', openDirectory);
document.getElementById('btn-save').addEventListener('click', () => save());

// Invoked from Python after open_directory() sets a new workspace root.
// Keeps the frontend state (browseRoot + sidebar cache) in sync with
// self._browse_root so the Files pane, workspace search gating, and
// palette file-search all see the new root without a page reload.
window.mdvwBrowseRootChanged = (payload) => {
  const newRoot = (payload && typeof payload.path === 'string') ? payload.path : '';
  if (!newRoot) return;
  browseRoot = newRoot;
  browserLoaded = false;
  browserNav.innerHTML = '';
  // If the Files pane is visible, refresh it immediately; otherwise leave
  // the lazy reload to the next Files-button click.
  const onFiles = (leftPaneSection === 'files') && !leftPaneCollapsed;
  if (onFiles) {
    loadBrowser();
  }
  flash(`Workspace: ${newRoot}`);
};
const btnWidth = document.getElementById('btn-width');
function updateWidthIcon() {
  const narrow = preview.classList.contains('narrow');
  btnWidth.querySelector('.icon-width-wide').style.display = narrow ? 'none' : '';
  btnWidth.querySelector('.icon-width-narrow').style.display = narrow ? '' : 'none';
}
btnWidth.addEventListener('click', () => { preview.classList.toggle('narrow'); updateWidthIcon(); persistState(); });
document.getElementById('btn-help').addEventListener('click', () => helpDialog.showModal());

const saveConflictDialog = document.getElementById('save-conflict');

async function save() {
  const api = getApi();
  if (!api || !api.save_file) { flash('Save unavailable'); return; }
  const content = (currentMode === 'edit' || currentMode === 'source') ? editor.value : currentSource;
  let result = await api.save_file(content, false);
  if (result && result.status === 'conflict') {
    // Disk changed since we loaded — ask before overwriting.
    const decision = await new Promise((resolve) => {
      saveConflictDialog.addEventListener('close', () =>
        resolve(saveConflictDialog.returnValue || 'cancel'), { once: true });
      saveConflictDialog.showModal();
    });
    if (decision !== 'overwrite') { flash('Save cancelled'); return; }
    result = await api.save_file(content, true);
  }
  if (result && result.status === 'ok') {
    currentSource = content;
    setDirty(false);
    flash('Saved');
    if (currentMode === 'read') await rerender();
    return;
  }
  if (result && result.status === 'error') {
    flash(`Save failed: ${result.message || 'unknown error'}`);
    return;
  }
  flash('Save cancelled');
}

// ---------- Live split-edit preview ----------

let renderDebounce = 0;
function setDirty(v) {
  dirty = !!v;
  const api = getApi();
  // Best-effort mirror for native UIs that read outside the close path.
  if (api && api.set_dirty) api.set_dirty(!!v);
  updateStatusBar();
}

// Synchronous dirty-state probe called by Python's `closing` handler via
// `window.evaluate_js`. This is the authoritative state — the async
// mirror above can lag on fast close/quit.
window.mdvwIsDirty = function () { return !!dirty; };

editor.addEventListener('input', () => {
  setDirty(true);
  currentSource = editor.value;
  if (currentMode === 'edit') {
    clearTimeout(renderDebounce);
    renderDebounce = setTimeout(() => rerender(), 120);
  }
});

// ---------- Render pipeline ----------

async function rerender() {
  const api = getApi();
  if (!api || !api.render_markdown) return;
  const htmlOut = await api.render_markdown(currentSource);
  preview.innerHTML = htmlOut;
  await enhance(preview);
  updateInspector();
  scheduleDiagnostics();
}

const reloadDialog = document.getElementById('reload-conflict');

// Set by the workspace-search click handler before api.open_path; consumed
// by applyExternalDocument once the target file has rendered. Carries the
// query into the in-document find bar so the user sees the hit highlighted
// and scrolled into view instead of just a cold-open document.
let pendingHighlight = null;

function applyPendingHighlight(currentPath) {
  if (!pendingHighlight) return;
  if (pendingHighlight.path && currentPath && pendingHighlight.path !== currentPath) {
    pendingHighlight = null;
    return;
  }
  const { query, caseSensitive } = pendingHighlight;
  pendingHighlight = null;
  if (!query) return;
  findInput.value = query;
  findCaseCheck.checked = !!caseSensitive;
  findWholeCheck.checked = false;
  openFind();
}

async function applyExternalDocument({ html: htmlOut, source, name, path }) {
  currentSource = source;
  setDirty(false);
  if (path) {
    fileChip.textContent = path;
    fileChip.title = path;
  } else if (name) {
    fileChip.textContent = name;
    fileChip.title = name;
  }
  if (name) document.title = `${name} — mdvw`;
  if (currentMode === 'edit' || currentMode === 'source') editor.value = source;
  preview.innerHTML = htmlOut;
  await enhance(preview);
  updateInspector();
  scheduleDiagnostics();
  applyPendingHighlight(path);
  // Tell Python we committed to this version so it can advance the
  // save-conflict baseline. Without this, a rejected watch reload would
  // leave Python's baseline out-of-sync with reality.
  const api = getApi();
  if (api && api.ack_reload) await api.ack_reload();
}

// Intercept all link clicks inside the preview. Any user-document link
// must be opened in the OS shell, never navigated inside this window,
// because this window holds the native JS↔Python bridge.
document.getElementById('preview').addEventListener('click', (e) => {
  const a = e.target && e.target.closest ? e.target.closest('a[href]') : null;
  if (!a) return;
  // Internal in-page anchors (#foo) are fine — let scrollIntoView handle via hashchange.
  const raw = a.getAttribute('href') || '';
  if (raw.startsWith('#')) {
    e.preventDefault();
    const tgt = document.getElementById(raw.slice(1));
    if (tgt) tgt.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return;
  }
  e.preventDefault();
  const api = getApi();
  if (api && api.open_external) api.open_external(a.href);
}, true); // capture: pre-empts any in-document handlers

// Pushed from Python (file watcher / open_file).
// `reason` is 'open' (explicit user open, already gated by confirmDiscardIfDirty)
// or 'watch' (external disk change). For 'watch', the only guard is `dirty` —
// read mode can still hold unsaved edits from a prior edit session.
window.mdvwSetDocument = async function (payload) {
  const reason = payload.reason || 'open';
  if (reason === 'watch' && dirty) {
    reloadDialog.addEventListener('close', async () => {
      if (reloadDialog.returnValue === 'reload') {
        await applyExternalDocument(payload);
      }
      // else: keep edits; drop the incoming update.
    }, { once: true });
    reloadDialog.showModal();
    return;
  }
  await applyExternalDocument(payload);
};

window.mdvwConfirmTrayQuit = async function () {
  if (!dirty) {
    const api = getApi();
    if (api && api.confirm_quit) await api.confirm_quit();
    return;
  }
  const choice = await new Promise((resolve) => {
    unsavedPrompt.addEventListener('close', () => resolve(unsavedPrompt.returnValue || 'cancel'), { once: true });
    unsavedPrompt.showModal();
  });
  if (choice === 'save') {
    await save();
    if (dirty) return; // save failed or cancelled
  } else if (choice === 'cancel') {
    return; // user cancelled — stay running
  }
  // 'discard' or save succeeded
  const api = getApi();
  if (api && api.confirm_quit) await api.confirm_quit();
};

window.mdvwPromptAssociation = function () {
  assocDialog.addEventListener('close', async () => {
    const api = getApi();
    if (assocDialog.returnValue === 'yes' && api && api.register_association) {
      await api.register_association();
    } else if (api && api.decline_association) {
      await api.decline_association();
    }
  }, { once: true });
  assocDialog.showModal();
};

// ---------- Image paste/drop ----------

async function handleImagePaste(e) {
  if (currentMode !== 'edit' && currentMode !== 'source') return;
  const items = e.clipboardData && e.clipboardData.items;
  if (!items) return;
  for (const item of items) {
    if (!item.type.startsWith('image/')) continue;
    e.preventDefault();
    const file = item.getAsFile();
    if (!file) continue;
    const dataUrl = await fileToDataUrl(file);
    await insertImage(dataUrl, '');
    return;
  }
}

async function handleImageDrop(e) {
  if (currentMode !== 'edit' && currentMode !== 'source') return;
  const files = e.dataTransfer && e.dataTransfer.files;
  if (!files || !files.length) return;
  for (const file of files) {
    if (!file.type.startsWith('image/')) continue;
    e.preventDefault();
    const dataUrl = await fileToDataUrl(file);
    await insertImage(dataUrl, file.name);
    return;
  }
}

function fileToDataUrl(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(file);
  });
}

async function insertImage(dataUrl, suggestedName) {
  if (!dataUrl) { flash('Could not read image'); return; }
  const api = getApi();
  if (!api || !api.save_image) { flash('Image save unavailable'); return; }
  const result = await api.save_image(dataUrl, suggestedName);
  if (result && result.status === 'ok') {
    const md = `![](${result.relative_path})`;
    const pos = editor.selectionStart;
    const before = editor.value.substring(0, pos);
    const after = editor.value.substring(editor.selectionEnd);
    editor.value = before + md + after;
    editor.selectionStart = editor.selectionEnd = pos + md.length;
    setDirty(true);
    currentSource = editor.value;
    if (currentMode === 'edit') {
      clearTimeout(renderDebounce);
      renderDebounce = setTimeout(() => rerender(), 120);
    }
    flash(`Image saved: ${result.relative_path}`);
  } else if (result && result.status === 'error') {
    flash(result.message || 'Image save failed');
  }
}

editor.addEventListener('paste', handleImagePaste);
editor.addEventListener('drop', handleImageDrop);
editor.addEventListener('dragover', (e) => {
  if (currentMode === 'edit' || currentMode === 'source') e.preventDefault();
});

registerCommand('insert.image', 'Paste Image as Attachment', '', async () => {
  if (currentMode !== 'edit' && currentMode !== 'source') {
    flash('Switch to Edit or Source mode first');
    return;
  }
  flash('Use Ctrl+V to paste an image from clipboard');
});

// ---------- Toast ----------

let toastTimer = 0;
function flash(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 1400);
}

// ---------- Init ----------

// Apply persisted pane state.
applyLeftPane();
applyRightPane();
if (leftPaneSection) showLeftSection(leftPaneSection);
// If left pane was saved as collapsed, restore that.
if (uiState.left_pane_collapsed) { leftPaneCollapsed = true; applyLeftPane(); }
if (uiState.preview_narrow) preview.classList.add('narrow');
btnFiles.classList.toggle('active', !leftPaneCollapsed && leftPaneSection === 'files');

await enhance(preview);
updateInspector();
updateStatusBar();
scheduleDiagnostics();
// startMode preset (from CLI --edit etc.)
if (startMode && startMode !== 'read') await setMode(startMode);
