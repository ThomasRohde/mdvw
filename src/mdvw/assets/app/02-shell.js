// ---------- Pane management ----------

const leftPane = document.getElementById('left-pane');
const rightPane = document.getElementById('right-pane');
const paneTabs = leftPane.querySelectorAll('.pane-tab');
const paneSections = leftPane.querySelectorAll('.pane-section');
let sessionsLoaded = false;
let incomingLoaded = false;
let tasksLoaded = false;
let graphLoaded = false;
let graphStale = true;
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
  if (name === 'tasks' && !tasksLoaded) loadTasks();
  if (name === 'incoming' && !incomingLoaded) loadIncomingLinks();
  if (name === 'graph' && (!graphLoaded || graphStale)) loadGraph();
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
registerCommand('note.new', 'New Note', 'Ctrl+N', () => openNoteCreateDialog());
registerCommand('note.new_template', 'New Note from Template', '', () => openNoteCreateDialog({ requireTemplate: true }));
registerCommand('note.daily', 'Open Daily Note', '', () => openDailyNote());
registerCommand('note.rename', 'Rename or Move Note', '', () => openNoteMoveDialog());
registerCommand('file.open', 'Open File', 'Ctrl+O', () => openFile());
registerCommand('file.open_dir', 'Open Directory', 'Ctrl+Shift+O', () => openDirectory());
registerCommand('file.save', 'Save', 'Ctrl+S', () => save());
registerCommand('navigate.back', 'Back', 'Alt+Left', () => navigateHistory(-1));
registerCommand('navigate.forward', 'Forward', 'Alt+Right', () => navigateHistory(1));
registerCommand('pane.files', 'Show Files', '', () => { loadBrowser(); showLeftSection('files'); });
registerCommand('pane.outline', 'Show Outline', '', () => showLeftSection('outline'));
registerCommand('pane.tasks', 'Show Tasks', '', () => {
  tasksLoaded = false;
  showLeftSection('tasks');
});
registerCommand('pane.graph', 'Open Graph View', 'Ctrl+Shift+G', () => toggleFullscreenGraph());
registerCommand('pane.graph_sidebar', 'Open Graph (sidebar)', '', () => showGraphView());
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
