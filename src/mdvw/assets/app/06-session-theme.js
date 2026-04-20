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

