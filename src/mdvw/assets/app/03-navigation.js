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

function normalizeBrowserPath(path) {
  let out = String(path || '').replace(/\\/g, '/').replace(/\/+$/, '');
  if (/^[a-z]:/i.test(out)) out = out.toLowerCase();
  return out;
}

function sameBrowserPath(a, b) {
  return !!a && !!b && normalizeBrowserPath(a) === normalizeBrowserPath(b);
}

function browserPathContains(dir, path) {
  const base = normalizeBrowserPath(dir);
  const target = normalizeBrowserPath(path);
  return !!base && !!target && target !== base && target.startsWith(`${base}/`);
}

function setActiveBrowserPath(path) {
  if (!path) return;
  browserNav.querySelectorAll('.file-link.active').forEach(b => b.classList.remove('active'));
  const btn = Array.from(browserNav.querySelectorAll('.file-link'))
    .find(item => sameBrowserPath(item.dataset.path, path));
  if (btn) {
    btn.classList.add('active');
    btn.scrollIntoView({ block: 'nearest' });
  }
}

async function revealBrowserPath(path) {
  if (!path) return;
  for (let i = 0; i < 20; i += 1) {
    const visibleFile = Array.from(browserNav.querySelectorAll('.file-link'))
      .find(btn => sameBrowserPath(btn.dataset.path, path));
    if (visibleFile) {
      setActiveBrowserPath(path);
      return;
    }
    const nextDir = Array.from(browserNav.querySelectorAll('details[data-path]'))
      .filter(details => browserPathContains(details.dataset.path, path))
      .sort((a, b) => normalizeBrowserPath(a.dataset.path).length - normalizeBrowserPath(b.dataset.path).length)
      .find(details => !details.open || !details.dataset.loaded);
    if (!nextDir) return;
    if (!nextDir.dataset.loaded) await loadDir(nextDir);
    nextDir.open = true;
  }
}

async function refreshBrowserIfVisible(targetPath = '') {
  browserLoaded = false;
  browserNav.innerHTML = '';
  if (leftPaneSection !== 'files' || leftPaneCollapsed || !browseRoot) return;
  try {
    await loadBrowser();
    await revealBrowserPath(targetPath || currentPath);
  } catch {
    browserLoaded = false;
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
      // On close, drop cached children so the next open re-lists from disk and
      // picks up files created externally (e.g. by a terminal session).
      // Bumping loadToken orphans any in-flight loadDir so its late render is a no-op.
      details.addEventListener('toggle', () => {
        if (details.open) {
          if (!details.dataset.loaded) loadDir(details);
          return;
        }
        details.dataset.loaded = '';
        details.dataset.loadToken = String((Number(details.dataset.loadToken) || 0) + 1);
        for (const child of Array.from(details.children)) {
          if (child.tagName !== 'SUMMARY') child.remove();
        }
      });
      li.appendChild(details);
    } else {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'file-link';
      btn.dataset.path = e.path;
      btn.textContent = e.name;
      btn.title = e.path;
      if (sameBrowserPath(e.path, currentPath)) btn.classList.add('active');
      li.appendChild(btn);
    }
    ul.appendChild(li);
  }
  parent.appendChild(ul);
}

async function loadDir(details) {
  if (details.dataset.loaded) return;
  details.dataset.loaded = '1';
  const token = String((Number(details.dataset.loadToken) || 0) + 1);
  details.dataset.loadToken = token;
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
  // Orphan this render if a close/refresh has since bumped the token. The
  // close handler bumps the token too, so user-collapsed-mid-fetch is covered
  // without also tripping when revealBrowserPath pre-loads a still-closed dir.
  if (details.dataset.loadToken !== token) return;
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

const btnFilesRefresh = document.getElementById('btn-files-refresh');
btnFilesRefresh.addEventListener('click', () => refreshBrowserIfVisible());

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

