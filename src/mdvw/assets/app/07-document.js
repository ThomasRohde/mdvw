// ---------- Open/Save ----------

const unsavedPrompt = document.getElementById('unsaved-prompt');
const noteCreateDialog = document.getElementById('note-create-dialog');
const noteCreateForm = document.getElementById('note-create-form');
const noteCreateTitle = document.getElementById('note-create-title');
const noteCreateTarget = document.getElementById('note-create-target');
const noteCreateTemplateRow = document.getElementById('note-create-template-row');
const noteCreateTemplate = document.getElementById('note-create-template');
const noteCreateHint = document.getElementById('note-create-hint');
const noteCreateError = document.getElementById('note-create-error');
const noteCreateCancel = document.getElementById('note-create-cancel');
const noteMoveDialog = document.getElementById('note-move-dialog');
const noteMoveForm = document.getElementById('note-move-form');
const noteMoveTarget = document.getElementById('note-move-target');
const noteMoveError = document.getElementById('note-move-error');
const noteMoveCancel = document.getElementById('note-move-cancel');
const wikiPreview = document.getElementById('wiki-hover-preview');
let noteCreateRequiresTemplate = false;

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

function setNoteCreateError(message = '') {
  noteCreateError.textContent = message;
  noteCreateError.hidden = !message;
}

function setNoteMoveError(message = '') {
  noteMoveError.textContent = message;
  noteMoveError.hidden = !message;
}

function fillNoteTemplateOptions(templates) {
  noteCreateTemplate.innerHTML = '';
  for (const template of templates) {
    const option = document.createElement('option');
    option.value = template.relative;
    option.textContent = template.relative;
    noteCreateTemplate.appendChild(option);
  }
}

async function loadNoteTemplates() {
  const api = getApi();
  if (!api || !api.get_note_templates) return [];
  try {
    return await api.get_note_templates();
  } catch {
    return [];
  }
}

async function openNoteCreateDialog({ requireTemplate = false } = {}) {
  if (!browseRoot) {
    flash('Open a workspace first');
    return;
  }
  noteCreateRequiresTemplate = requireTemplate;
  noteCreateTitle.textContent = requireTemplate ? 'New Note from Template' : 'New Note';
  noteCreateHint.textContent = requireTemplate
    ? 'Creates beside the current note, or at the workspace root. Templates come from Templates/.'
    : 'Creates beside the current note, or at the workspace root.';
  noteCreateTarget.value = '';
  setNoteCreateError('');
  noteCreateTemplateRow.hidden = !requireTemplate;
  noteCreateTemplate.disabled = !requireTemplate;
  if (requireTemplate) {
    const templates = await loadNoteTemplates();
    if (!templates.length) {
      flash('No templates found in Templates');
      return;
    }
    fillNoteTemplateOptions(templates);
  } else {
    noteCreateTemplate.innerHTML = '';
  }
  noteCreateDialog.showModal();
  requestAnimationFrame(() => noteCreateTarget.focus());
}

async function openDailyNote() {
  if (!browseRoot) {
    flash('Open a workspace first');
    return;
  }
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.open_daily_note) {
    flash('Daily notes unavailable');
    return;
  }
  const result = await api.open_daily_note();
  if (result && (result.status === 'created' || result.status === 'ok')) {
    tasksLoaded = false;
    await refreshBrowserIfVisible(result.path || currentPath);
    if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
    flash(result.status === 'created' ? 'Created daily note' : 'Opened daily note');
    return;
  }
  flash((result && result.message) || 'Could not open daily note');
}

function currentWorkspaceRelativeNotePath() {
  const root = normalizeBrowserPath(browseRoot);
  const path = normalizeBrowserPath(currentPath);
  if (!root || !path || !path.startsWith(`${root}/`)) return '';
  return path.slice(root.length + 1).replace(/\.markdown?$/i, '');
}

async function openNoteMoveDialog() {
  if (!browseRoot) {
    flash('Open a workspace first');
    return;
  }
  if (!currentPath || !currentWorkspaceRelativeNotePath()) {
    flash('Current note is not in the workspace');
    return;
  }
  noteMoveTarget.value = currentWorkspaceRelativeNotePath();
  setNoteMoveError('');
  noteMoveDialog.showModal();
  requestAnimationFrame(() => {
    noteMoveTarget.focus();
    noteMoveTarget.select();
  });
}

noteCreateCancel.addEventListener('click', () => noteCreateDialog.close());
noteMoveCancel.addEventListener('click', () => noteMoveDialog.close());

noteCreateForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const target = noteCreateTarget.value.trim();
  if (!target) {
    setNoteCreateError('Enter a note name or path');
    noteCreateTarget.focus();
    return;
  }
  if (noteCreateRequiresTemplate && !noteCreateTemplate.value) {
    setNoteCreateError('Choose a template');
    return;
  }
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.create_note) {
    setNoteCreateError('Note creation unavailable');
    return;
  }
  const result = await api.create_note(
    target,
    noteCreateRequiresTemplate ? noteCreateTemplate.value : '',
  );
  if (result && (result.status === 'created' || result.status === 'ok')) {
    noteCreateDialog.close();
    tasksLoaded = false;
    await refreshBrowserIfVisible(result.path || currentPath);
    if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
    flash(result.status === 'created' ? 'Created note' : 'Opened note');
    return;
  }
  setNoteCreateError((result && result.message) || 'Could not create note');
});

noteMoveForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const target = noteMoveTarget.value.trim();
  if (!target) {
    setNoteMoveError('Enter a note name or path');
    noteMoveTarget.focus();
    return;
  }
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.move_current_note) {
    setNoteMoveError('Rename unavailable');
    return;
  }
  const result = await api.move_current_note(target);
  if (result && result.status === 'ok') {
    noteMoveDialog.close();
    tasksLoaded = false;
    await refreshBrowserIfVisible(result.path || currentPath);
    if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
    flash(result.message || 'Moved note');
    return;
  }
  setNoteMoveError((result && result.message) || 'Could not move note');
});

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
btnBack.addEventListener('click', () => navigateHistory(-1));
btnForward.addEventListener('click', () => navigateHistory(1));

// Invoked from Python after open_directory() sets a new workspace root.
// Keeps the frontend state (browseRoot + sidebar cache) in sync with
// self._browse_root so the Files pane, workspace search gating, and
// palette file-search all see the new root without a page reload.
window.mdvwBrowseRootChanged = (payload) => {
  const newRoot = (payload && typeof payload.path === 'string') ? payload.path : '';
  if (!newRoot) return;
  browseRoot = newRoot;
  resetWikiPreview({ clearCache: true });
  incomingLoaded = false;
  tasksLoaded = false;
  graphLoaded = false;
  graphStale = true;
  // If the Files pane is visible, refresh it immediately; otherwise leave
  // the lazy reload to the next Files-button click.
  refreshBrowserIfVisible();
  if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
  if (graphIsVisible()) loadGraph({ resetView: true });
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
    if (result.path) {
      currentPath = result.path;
      fileChip.textContent = result.path;
      fileChip.title = result.path;
    }
    if (result.name) document.title = `${result.name} — mdvw`;
    recordDocumentNavigation(currentPath, result.name || fileChip.textContent || currentPath, 'save');
    setDirty(false);
    incomingLoaded = false;
    tasksLoaded = false;
    graphStale = true;
    await refreshBrowserIfVisible(result.path || currentPath);
    if (graphIsVisible()) await loadGraph();
    flash('Saved');
    if (currentMode === 'read') await rerender();
    if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
    if (leftPaneSection === 'incoming' && !leftPaneCollapsed) loadIncomingLinks();
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
  scheduleWikiCompletion();
});

// ---------- Wiki-link autocomplete ----------

const wikiComplete = document.getElementById('wiki-complete');
let wikiCompleteOpen = false;
let wikiCompleteItems = [];
let wikiCompleteActive = 0;
let wikiCompleteRange = null;
let wikiCompleteTimer = 0;
let wikiCompleteRequest = 0;
let wikiPreviewTimer = 0;
let wikiPreviewToken = 0;
let wikiPreviewAnchor = null;
const wikiPreviewCache = new Map();

function wikiPreviewCacheKey(raw) {
  return `${browseRoot || ''}\n${currentPath || ''}\n${raw}`;
}

function resetWikiPreview({ clearCache = false } = {}) {
  hideWikiPreview();
  if (clearCache) wikiPreviewCache.clear();
}

function getWikiCompletionContext() {
  if (currentMode !== 'edit' && currentMode !== 'source') return null;
  if (editor.selectionStart !== editor.selectionEnd) return null;
  const pos = editor.selectionStart;
  const before = editor.value.slice(0, pos);
  const open = before.lastIndexOf('[[');
  if (open < 0) return null;
  const close = before.lastIndexOf(']]');
  if (close > open) return null;
  const query = before.slice(open + 2);
  if (query.includes('\n') || query.includes(']') || query.startsWith('!')) return null;
  if (query.includes('|')) return null;
  return { start: open + 2, end: pos, query };
}

function scheduleWikiCompletion() {
  clearTimeout(wikiCompleteTimer);
  const ctx = getWikiCompletionContext();
  if (!ctx) { closeWikiCompletion(); return; }
  wikiCompleteTimer = setTimeout(() => updateWikiCompletion(ctx), 120);
}

async function updateWikiCompletion(ctx) {
  const api = getApi();
  if (!api || !api.search_wiki_targets) { closeWikiCompletion(); return; }
  const request = ++wikiCompleteRequest;
  const items = await api.search_wiki_targets(ctx.query, currentPath);
  if (request !== wikiCompleteRequest) return;
  if (!items || !items.length) { closeWikiCompletion(); return; }
  wikiCompleteRange = ctx;
  wikiCompleteItems = items;
  wikiCompleteActive = 0;
  renderWikiCompletion();
}

function renderWikiCompletion() {
  wikiComplete.innerHTML = '';
  wikiComplete.hidden = false;
  wikiCompleteOpen = true;
  positionWikiCompletion();
  wikiCompleteItems.forEach((item, i) => {
    const div = document.createElement('div');
    div.className = 'wiki-complete-item' + (i === wikiCompleteActive ? ' active' : '');
    const label = document.createElement('span');
    label.className = 'wiki-complete-label';
    label.textContent = item.type === 'heading' ? `# ${item.label}` : item.label;
    const detail = document.createElement('span');
    detail.className = 'wiki-complete-detail';
    detail.textContent = item.detail || item.insert || '';
    div.appendChild(label);
    div.appendChild(detail);
    div.addEventListener('mousedown', (e) => {
      e.preventDefault();
      acceptWikiCompletion(i);
    });
    wikiComplete.appendChild(div);
  });
}

function positionWikiCompletion() {
  const rect = getTextareaCaretRect(editor);
  wikiComplete.style.left = `${Math.min(rect.left, window.innerWidth - 340)}px`;
  wikiComplete.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 280)}px`;
}

function updateWikiCompletionActive() {
  wikiComplete.querySelectorAll('.wiki-complete-item').forEach((el, i) => {
    const on = i === wikiCompleteActive;
    el.classList.toggle('active', on);
    if (on) el.scrollIntoView({ block: 'nearest' });
  });
}

function acceptWikiCompletion(index = wikiCompleteActive) {
  const item = wikiCompleteItems[index];
  if (!item || !wikiCompleteRange) return;
  const suffix = editor.value.slice(wikiCompleteRange.end, wikiCompleteRange.end + 2) === ']]' ? '' : ']]';
  const insert = `${item.insert}${suffix}`;
  editor.value =
    editor.value.slice(0, wikiCompleteRange.start) +
    insert +
    editor.value.slice(wikiCompleteRange.end);
  const pos = wikiCompleteRange.start + insert.length;
  editor.selectionStart = editor.selectionEnd = pos;
  currentSource = editor.value;
  setDirty(true);
  closeWikiCompletion();
  if (currentMode === 'edit') {
    clearTimeout(renderDebounce);
    renderDebounce = setTimeout(() => rerender(), 120);
  }
}

function closeWikiCompletion() {
  wikiCompleteOpen = false;
  wikiComplete.hidden = true;
  wikiComplete.innerHTML = '';
  wikiCompleteItems = [];
  wikiCompleteRange = null;
}

function hideWikiPreview() {
  clearTimeout(wikiPreviewTimer);
  wikiPreview.hidden = true;
  wikiPreview.innerHTML = '';
  wikiPreviewAnchor = null;
}

function positionWikiPreview(anchor) {
  const rect = anchor.getBoundingClientRect();
  const width = wikiPreview.offsetWidth || 360;
  const height = wikiPreview.offsetHeight || 220;
  const left = Math.min(
    window.innerWidth - width - 12,
    Math.max(12, rect.left),
  );
  const below = rect.bottom + 8;
  const above = rect.top - height - 8;
  const top = above >= 12 ? above : Math.min(window.innerHeight - height - 12, below);
  wikiPreview.style.left = `${left}px`;
  wikiPreview.style.top = `${Math.max(12, top)}px`;
}

function renderWikiPreview(result) {
  if (!result || result.status !== 'ok') {
    wikiPreview.innerHTML = `<div class="wiki-preview-empty">${escapeHtml((result && result.message) || 'Preview unavailable')}</div>`;
    return;
  }
  wikiPreview.innerHTML = `
    <div class="wiki-preview-card">
      <div class="wiki-preview-head">
        <span class="wiki-preview-title">${escapeHtml(result.title || '')}</span>
        <span class="wiki-preview-path">${escapeHtml(result.relative || '')}</span>
      </div>
      <div class="wiki-preview-body">${result.html || ''}</div>
    </div>
  `;
}

async function showWikiPreview(anchor) {
  const raw = anchor && anchor.dataset ? anchor.dataset.wikilink : '';
  if (!raw) return;
  const token = ++wikiPreviewToken;
  wikiPreviewAnchor = anchor;
  const api = getApi();
  const cacheKey = wikiPreviewCacheKey(raw);
  let result = wikiPreviewCache.get(cacheKey);
  if (!result) {
    if (!api || !api.preview_wiki_link) return;
    result = await api.preview_wiki_link(raw);
    wikiPreviewCache.set(cacheKey, result);
  }
  if (token !== wikiPreviewToken || wikiPreviewAnchor !== anchor) return;
  renderWikiPreview(result);
  wikiPreview.hidden = false;
  positionWikiPreview(anchor);
}

function scheduleWikiPreview(anchor) {
  clearTimeout(wikiPreviewTimer);
  wikiPreviewTimer = setTimeout(() => showWikiPreview(anchor), 220);
}

function getTextareaCaretRect(textarea) {
  const style = window.getComputedStyle(textarea);
  const mirror = document.createElement('div');
  const props = [
    'boxSizing', 'width', 'fontFamily', 'fontSize', 'fontWeight', 'fontStyle',
    'letterSpacing', 'textTransform', 'paddingTop', 'paddingRight', 'paddingBottom',
    'paddingLeft', 'borderTopWidth', 'borderRightWidth', 'borderBottomWidth',
    'borderLeftWidth', 'lineHeight', 'whiteSpace', 'wordWrap',
  ];
  mirror.style.position = 'absolute';
  mirror.style.visibility = 'hidden';
  mirror.style.overflow = 'hidden';
  mirror.style.whiteSpace = 'pre-wrap';
  mirror.style.wordWrap = 'break-word';
  for (const prop of props) mirror.style[prop] = style[prop];
  mirror.textContent = textarea.value.slice(0, textarea.selectionStart);
  const marker = document.createElement('span');
  marker.textContent = '\u200b';
  mirror.appendChild(marker);
  document.body.appendChild(mirror);
  const markerRect = marker.getBoundingClientRect();
  const textareaRect = textarea.getBoundingClientRect();
  const left = textareaRect.left + markerRect.left - mirror.getBoundingClientRect().left - textarea.scrollLeft;
  const top = textareaRect.top + markerRect.top - mirror.getBoundingClientRect().top - textarea.scrollTop;
  document.body.removeChild(mirror);
  return {
    left: Math.max(8, left),
    top: Math.max(8, top),
    bottom: Math.max(8, top + parseFloat(style.lineHeight || '20')),
  };
}

editor.addEventListener('keydown', (e) => {
  if (!wikiCompleteOpen) return;
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    wikiCompleteActive = Math.min(wikiCompleteActive + 1, wikiCompleteItems.length - 1);
    updateWikiCompletionActive();
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    wikiCompleteActive = Math.max(wikiCompleteActive - 1, 0);
    updateWikiCompletionActive();
  } else if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    acceptWikiCompletion();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeWikiCompletion();
  }
});

editor.addEventListener('click', scheduleWikiCompletion);
editor.addEventListener('scroll', () => { if (wikiCompleteOpen) positionWikiCompletion(); });

// ---------- Render pipeline ----------

async function rerender() {
  const api = getApi();
  if (!api || !api.render_markdown) return;
  hideWikiPreview();
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
let pendingWikiJump = null;

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

function normalizedHeadingText(text) {
  return (text || '').toLowerCase().trim().replace(/\s+/g, ' ');
}

function scrollToHeading(heading) {
  if (!heading) return false;
  const wanted = normalizedHeadingText(heading);
  for (const h of preview.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    if (normalizedHeadingText(h.textContent) === wanted || h.id === heading) {
      h.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return true;
    }
  }
  return false;
}

function applyPendingWikiJump(path) {
  if (!pendingWikiJump) return;
  if (pendingWikiJump.path && path && pendingWikiJump.path !== path) {
    pendingWikiJump = null;
    return;
  }
  const heading = pendingWikiJump.heading;
  pendingWikiJump = null;
  if (heading && !scrollToHeading(heading)) flash(`Heading not found: ${heading}`);
}

async function applyExternalDocument({ html: htmlOut, source, name, path, reason = 'open' }) {
  currentSource = source;
  resetWikiPreview({ clearCache: true });
  setDirty(false);
  currentPath = path || '';
  if (path) {
    fileChip.textContent = path;
    fileChip.title = path;
  } else if (name) {
    fileChip.textContent = name;
    fileChip.title = name;
  }
  if (name) document.title = `${name} — mdvw`;
  recordDocumentNavigation(currentPath, name || fileChip.textContent || currentPath, reason);
  if (browserLoaded) setActiveBrowserPath(currentPath);
  if (currentMode === 'edit' || currentMode === 'source') editor.value = source;
  preview.innerHTML = htmlOut;
  await enhance(preview);
  updateInspector();
  scheduleDiagnostics();
  incomingLoaded = false;
  tasksLoaded = false;
  graphStale = true;
  if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
  if (leftPaneSection === 'incoming' && !leftPaneCollapsed) loadIncomingLinks();
  if (graphIsVisible()) await loadGraph();
  applyPendingHighlight(path);
  applyPendingWikiJump(path);
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
  const wikiRaw = a.dataset.wikilink;
  if (wikiRaw) {
    e.preventDefault();
    hideWikiPreview();
    openWikiLink(wikiRaw);
    return;
  }
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

preview.addEventListener('mouseover', (e) => {
  const anchor = e.target && e.target.closest ? e.target.closest('a.mdvw-wikilink') : null;
  if (!anchor || anchor === wikiPreviewAnchor) return;
  scheduleWikiPreview(anchor);
});

preview.addEventListener('mousemove', (e) => {
  const anchor = e.target && e.target.closest ? e.target.closest('a.mdvw-wikilink') : null;
  if (!anchor && !wikiPreview.hidden) hideWikiPreview();
});

preview.addEventListener('mouseleave', hideWikiPreview);
preview.addEventListener('scroll', hideWikiPreview);
document.addEventListener('mousedown', hideWikiPreview);

async function openWikiLink(raw) {
  const api = getApi();
  if (!api || !api.resolve_wiki_link) { flash('Wiki links unavailable'); return; }
  const resolved = await api.resolve_wiki_link(raw);
  if (!resolved || !resolved.status) { flash('Wiki link unavailable'); return; }
  if (resolved.status === 'ok' && resolved.path) {
    if (sameBrowserPath(resolved.path, currentPath)) {
      if (resolved.heading) scrollToHeading(resolved.heading);
      return;
    }
    if (!(await confirmDiscardIfDirty())) return;
    pendingWikiJump = { path: resolved.path, heading: resolved.heading || '' };
    const ok = api.open_path ? await api.open_path(resolved.path) : false;
    if (!ok) {
      pendingWikiJump = null;
      flash('Could not open wiki link');
    }
    return;
  }
  if (resolved.status === 'no_workspace') { flash(resolved.message || 'No workspace'); return; }
  if (resolved.status === 'missing' && api.create_wiki_note) {
    if (!(await confirmDiscardIfDirty())) return;
    const created = await api.create_wiki_note(raw);
    if (created && (created.status === 'created' || created.status === 'ok')) {
      await refreshBrowserIfVisible(created.path || currentPath);
      flash('Created note');
      return;
    }
    flash((created && created.message) || 'Could not create note');
    return;
  }
  flash(resolved.message || 'Wiki link not resolved');
  if (resolved.status === 'ambiguous' || resolved.status === 'missing_heading') {
    showLeftSection('diagnostics');
    runDiagnostics();
  }
}

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

(async function initApp() {

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
})();
