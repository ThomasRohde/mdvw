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

// ---------- Workspace tasks ----------

const tasksList = document.getElementById('tasks-list');
const tasksShowDone = document.getElementById('tasks-show-done');

function taskEmpty(message) {
  tasksList.innerHTML = `<div class="tasks-empty">${escapeHtml(message)}</div>`;
}

async function loadTasks() {
  const api = await whenApiReady();
  if (!browseRoot) {
    taskEmpty('No workspace');
    tasksLoaded = true;
    return;
  }
  if (!api || !api.get_workspace_tasks) {
    taskEmpty('Tasks unavailable');
    tasksLoaded = true;
    return;
  }
  taskEmpty('Loading…');
  const tasks = await api.get_workspace_tasks(tasksShowDone.checked);
  tasksList.innerHTML = '';
  if (!tasks || !tasks.length) {
    taskEmpty(tasksShowDone.checked ? 'No tasks' : 'No open tasks');
    tasksLoaded = true;
    return;
  }

  const groups = new Map();
  for (const task of tasks) {
    if (!groups.has(task.path)) {
      groups.set(task.path, { relative: task.relative, items: [] });
    }
    groups.get(task.path).items.push(task);
  }

  for (const [path, group] of groups) {
    const header = document.createElement('div');
    header.className = 'tasks-group';
    header.textContent = group.relative;
    header.title = path;
    tasksList.appendChild(header);

    for (const task of group.items) {
      const row = document.createElement('div');
      row.className = 'task-item';

      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'task-item-toggle';
      toggle.dataset.path = task.path;
      toggle.dataset.line = String(task.line);
      toggle.title = task.checked ? 'Mark not done' : 'Mark done';
      toggle.textContent = task.checked ? '[x]' : '[ ]';

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'task-item-open';
      btn.dataset.path = task.path;
      btn.dataset.query = task.text || '';
      btn.title = path;

      const main = document.createElement('span');
      main.className = 'task-item-main';

      const text = document.createElement('span');
      text.className = 'task-item-text';
      text.textContent = task.text;

      main.appendChild(text);
      btn.appendChild(main);

      const meta = document.createElement('span');
      meta.className = 'task-item-meta';
      const metaParts = [];
      if (task.heading) metaParts.push(task.heading);
      metaParts.push(`L${task.line}`);
      meta.textContent = metaParts.join(' · ');
      btn.appendChild(meta);

      row.appendChild(toggle);
      row.appendChild(btn);
      tasksList.appendChild(row);
    }
  }

  tasksLoaded = true;
}

tasksList.addEventListener('click', async (e) => {
  const toggle = e.target && e.target.closest ? e.target.closest('.task-item-toggle') : null;
  if (toggle) {
    const path = toggle.dataset.path;
    const line = Number(toggle.dataset.line || '0');
    if (!path || !Number.isInteger(line) || line < 1) return;
    if (dirty && sameBrowserPath(path, currentPath)) {
      flash('Save or discard changes before toggling this task');
      return;
    }
    const api = getApi();
    if (!api || !api.toggle_workspace_task) {
      flash('Task toggle unavailable');
      return;
    }
    const result = await api.toggle_workspace_task(path, line);
    if (result && result.status === 'ok') {
      tasksLoaded = false;
      if (leftPaneSection === 'tasks' && !leftPaneCollapsed) await loadTasks();
      flash(result.checked ? 'Task done' : 'Task reopened');
      return;
    }
    flash((result && result.message) || 'Could not update task');
    return;
  }

  const btn = e.target && e.target.closest ? e.target.closest('.task-item-open') : null;
  if (!btn) return;
  const path = btn.dataset.path;
  const query = btn.dataset.query;
  if (!path) return;
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.open_path) return;
  pendingHighlight = { path, query, caseSensitive: true };
  const ok = await api.open_path(path);
  if (!ok) {
    pendingHighlight = null;
    flash('Could not open file');
  }
});

tasksShowDone.addEventListener('change', () => {
  tasksLoaded = false;
  if (leftPaneSection === 'tasks' && !leftPaneCollapsed) loadTasks();
});

// ---------- Incoming links ----------

const incomingList = document.getElementById('incoming-list');

async function loadIncomingLinks() {
  const api = await whenApiReady();
  incomingList.innerHTML = '';
  if (!api || !api.get_incoming_links || !currentPath) {
    incomingList.innerHTML = '<div class="incoming-empty">No current note</div>';
    incomingLoaded = true;
    return;
  }
  const links = await api.get_incoming_links(currentPath);
  if (!links || !links.length) {
    incomingList.innerHTML = '<div class="incoming-empty">No incoming links</div>';
    incomingLoaded = true;
    return;
  }
  for (const link of links) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'incoming-item';
    btn.dataset.path = link.source_path;
    btn.dataset.raw = link.raw;
    btn.title = link.source_path;

    const source = document.createElement('span');
    source.className = 'incoming-source';
    const line = document.createElement('span');
    line.className = 'incoming-line';
    line.textContent = `L${link.line}`;
    source.appendChild(line);
    source.appendChild(document.createTextNode(link.source_relative));

    const ctx = document.createElement('span');
    ctx.className = 'incoming-context';
    ctx.textContent = link.context || link.display || link.raw;

    btn.appendChild(source);
    btn.appendChild(ctx);
    incomingList.appendChild(btn);
  }
  incomingLoaded = true;
}

incomingList.addEventListener('click', async (e) => {
  const btn = e.target && e.target.closest ? e.target.closest('.incoming-item') : null;
  if (!btn) return;
  const path = btn.dataset.path;
  if (!path) return;
  if (!(await confirmDiscardIfDirty())) return;
  const api = getApi();
  if (!api || !api.open_path) return;
  pendingHighlight = { path, query: `[[${btn.dataset.raw || ''}]]`, caseSensitive: true };
  const ok = await api.open_path(path);
  if (!ok) {
    pendingHighlight = null;
    flash('Could not open file');
  }
});

registerCommand('pane.incoming', 'Show Incoming Links', '', () => {
  incomingLoaded = false;
  loadIncomingLinks();
  showLeftSection('incoming');
});
