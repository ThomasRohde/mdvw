// mdvw front-end glue — three-mode viewer/editor.

const html = document.documentElement;
const preview = document.getElementById('preview');
const editor = document.getElementById('editor');
const toast = document.getElementById('toast');
const fileChip = document.getElementById('file-chip');
const assocDialog = document.getElementById('assoc-prompt');
const helpDialog = document.getElementById('help-dialog');
const segs = document.querySelectorAll('.segmented .seg');

// Defense in depth: scope bootstrap lookups to the specific <script> tags
// we injected, so a user document with `<div id="md-source">...` can't
// shadow our data during sanitizer edge cases.
const bootstrapEl = (id) =>
  document.querySelector(`script#${id}`) ||
  document.getElementById(id);

const mdSource = JSON.parse(bootstrapEl('md-source').textContent || '""');
const mdPath = bootstrapEl('md-path').textContent.trim();
const startMode = (bootstrapEl('md-start-mode').textContent.trim() || 'read');
const browseRoot = (bootstrapEl('md-browse-root')?.textContent || '').trim();

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
}

segs.forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));

// Cycle on E, but only when not typing in textarea/input
document.addEventListener('keydown', (e) => {
  const typing = document.activeElement && (document.activeElement.tagName === 'TEXTAREA' || document.activeElement.tagName === 'INPUT');
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 's') { e.preventDefault(); save(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === 'o') {
    e.preventDefault();
    openFile();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'w' || e.key === 'W')) {
    e.preventDefault();
    preview.classList.toggle('narrow');
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

function applyHljsTheme() {
  const dark = html.dataset.resolvedTheme === 'dark';
  const light = document.getElementById('hljs-theme-light');
  const darkEl = document.getElementById('hljs-theme-dark');
  if (light) light.disabled = dark;
  if (darkEl) darkEl.disabled = !dark;
}

function highlightAndDecorate(root) {
  applyHljsTheme();
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

// ---------- Outline ----------

const outlinePanel = document.getElementById('outline-panel');
const outlineNav = document.getElementById('outline-nav');
document.getElementById('btn-outline').addEventListener('click', () => {
  outlinePanel.hidden = !outlinePanel.hidden;
  document.getElementById('btn-outline').classList.toggle('active', !outlinePanel.hidden);
});
document.getElementById('btn-outline-close').addEventListener('click', () => {
  outlinePanel.hidden = true;
  document.getElementById('btn-outline').classList.remove('active');
});

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
  while (el) {
    const l = headingLevel(el);
    if (l && l <= lvl) break;
    el.classList.toggle('mdvw-hidden', target);
    el = el.nextElementSibling;
  }
}

function wireHeadingCollapse(root) {
  for (const h of root.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    if (h.dataset.collapseWired) continue;
    h.dataset.collapseWired = '1';
    h.addEventListener('click', (e) => {
      // Only trigger when clicking the left bullet area
      const rect = h.getBoundingClientRect();
      if (e.clientX - rect.left > 28) return;
      toggleHeading(h);
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
  // Expand h1, collapse h2+
  for (const h of root.querySelectorAll('h2,h3,h4,h5,h6')) toggleHeading(h, true);
  for (const h of root.querySelectorAll('h1')) toggleHeading(h, false);
}

document.getElementById('btn-collapse-all').addEventListener('click', () => {
  autoCollapseActive = false;
  document.getElementById('btn-auto-collapse').classList.remove('active');
  collapseAll(preview);
});
document.getElementById('btn-expand-all').addEventListener('click', () => {
  autoCollapseActive = false;
  document.getElementById('btn-auto-collapse').classList.remove('active');
  expandAll(preview);
});
document.getElementById('btn-auto-collapse').addEventListener('click', () => {
  autoCollapseActive = !autoCollapseActive;
  document.getElementById('btn-auto-collapse').classList.toggle('active', autoCollapseActive);
  if (autoCollapseActive) applyAutoCollapse(preview); else expandAll(preview);
});

// ---------- File browser (only when launched without a file arg) ----------

const browserPanel = document.getElementById('browser-panel');
const browserNav = document.getElementById('browser-nav');
const btnFiles = document.getElementById('btn-files');
let browserLoaded = false;

function setBrowserOpen(open) {
  browserPanel.hidden = !open;
  btnFiles.classList.toggle('active', open);
  if (open) {
    // Opening the left drawer closes the right outline drawer so they
    // don't both claim the sides simultaneously on narrow windows.
    outlinePanel.hidden = true;
    document.getElementById('btn-outline').classList.remove('active');
  }
}

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
    setBrowserOpen(false);
  } else {
    flash('Could not open file');
  }
});

btnFiles.addEventListener('click', async () => {
  if (!browseRoot) { flash('File browser unavailable'); return; }
  const willOpen = browserPanel.hidden;
  if (willOpen) await loadBrowser();
  setBrowserOpen(willOpen);
});
document.getElementById('btn-browser-close').addEventListener('click', () => setBrowserOpen(false));
// Auto-open the sidebar on first paint when no specific file was passed.
if (browseRoot && !mdPath) {
  loadBrowser().then(() => setBrowserOpen(true));
}

// ---------- Theme ----------

function resolveTheme() {
  const attr = html.dataset.theme;
  const sysDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
  const resolved = attr === 'auto' ? (sysDark ? 'dark' : 'light') : attr;
  html.dataset.resolvedTheme = resolved;
  return resolved;
}
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  resolveTheme();
  mermaidInited = false;
  applyHljsTheme();
  if (currentMode !== 'source') rerender();
});
resolveTheme();

document.getElementById('btn-theme').addEventListener('click', () => {
  const cur = html.dataset.theme || 'auto';
  const next = cur === 'auto' ? 'light' : cur === 'light' ? 'dark' : 'auto';
  html.dataset.theme = next;
  resolveTheme();
  mermaidInited = false;
  flash(`Theme: ${next}`);
  if (currentMode !== 'source') rerender();
});

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
document.getElementById('btn-open').addEventListener('click', openFile);
document.getElementById('btn-save').addEventListener('click', () => save());
const btnWidth = document.getElementById('btn-width');
function updateWidthIcon() {
  const narrow = preview.classList.contains('narrow');
  btnWidth.querySelector('.icon-width-wide').style.display = narrow ? 'none' : '';
  btnWidth.querySelector('.icon-width-narrow').style.display = narrow ? '' : 'none';
}
btnWidth.addEventListener('click', () => { preview.classList.toggle('narrow'); updateWidthIcon(); });
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
}

const reloadDialog = document.getElementById('reload-conflict');

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

// ---------- Toast ----------

let toastTimer = 0;
function flash(msg) {
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 1400);
}

// ---------- Init ----------

await enhance(preview);
// startMode preset (from CLI --edit etc.)
if (startMode && startMode !== 'read') await setMode(startMode);
