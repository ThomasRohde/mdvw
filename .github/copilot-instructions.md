# Copilot Instructions for mdvw

## Commands

```bash
pytest -q                              # full test suite (~112 tests)
pytest -q tests/test_render.py        # single test file
pytest -q -k test_basic_heading       # single test by name
ruff check src tests scripts          # lint (zero-warning policy; CI fails on any warning)
python scripts/fetch_vendor.py --verify   # verify vendored JS/CSS SHA256s match manifest
```

## Architecture

mdvw is a Windows-only offline Markdown viewer/editor built on **pywebview** (EdgeChromium/WebView2).

**Data flow:**
1. `cli.py` parses args and calls `app.py:run()`
2. `app.py` renders `assets/template.html` → writes `index.html` to a fresh `tempfile.mkdtemp("mdvw-")` dir → launches a pywebview window
3. `render.py` converts Markdown → HTML via `markdown-it-py` + `mdit-py-plugins`, then sanitizes with `nh3`
4. `JsApi` in `app.py` is the Python↔JS bridge; all its methods are callable from the frontend via `window.pywebview.api.*`
5. `watcher.py` (watchfiles + asyncio) detects external file changes on a daemon thread and calls `api._load(reason="watch")`
6. `ipc.py` implements single-instance handoff: first launch binds a loopback socket and writes a lockfile; second launch sends the new path and exits

**Module map:**
- `app.py` — main window, `JsApi` class, file save/load, export, fingerprint-based conflict detection
- `render.py` — Markdown pipeline; custom inline rules for `==highlight==`, `++underline++`, `{color:…}…{/color}` syntax
- `export.py` — self-contained HTML export (inlines CSS, fonts, images as data URIs)
- `search.py` — workspace `.md` search (`Ctrl+Shift+F`)
- `diagnostics.py` — flags broken links, invalid frontmatter, blocked remote refs
- `frontmatter.py` — YAML frontmatter parsing and card rendering
- `config.py` — user prefs → `%APPDATA%/mdvw/config.json`
- `state.py` — UI state (pane widths, recent files) → `%APPDATA%/mdvw/state.json`
- `tray.py` — system tray icon (pystray)
- `assoc.py` — `.md` file association via Windows Registry (HKCU, no admin)
- `assets/template.html` + `assets/app.js` + `assets/app.css` — frontend
- `assets/vendor/` — vendored KaTeX, Mermaid, highlight.js, webfonts (SHA256-pinned)

## Key Conventions

### pywebview / JsApi
- **All `JsApi` instance state must use underscore-prefix** (`self._foo`, never `self.foo`). pywebview enumerates public attributes for JS exposure and will recurse into `.NET` objects (e.g. `window.native.AccessibilityObject.Bounds.Empty.Empty…`) until it hits the recursion limit.
- **Never call `window.evaluate_js(...)` from the `closing` event handler.** Both run on the UI thread — this causes a deadlock. The closing guard reads the mirrored `api._dirty` instead.

### File save/reload
- `_atomic_write_text(path, content)` — tmp file + fsync + `os.replace`; never write directly to the target path.
- Fingerprint-based conflict detection: `_loaded_fingerprint` tracks mtime+size. `_load(reason="watch")` parks the new fingerprint in `_pending_fingerprint`; the JS frontend must call `api.ack_reload()` to promote it.

### Sanitizer invariants (`render.py`)
Do not loosen these without re-reading commit history:
- `id` attribute is **stripped** from user HTML (prevents shadowing bootstrap elements like `#md-source`)
- `img src` accepts only `data:` URIs and strictly-relative paths — no `http(s)`, no `//host`, no UNC, no absolute paths
- `file:` is **rejected** as a link scheme (prevents `os.startfile` exploitation)

### JSON embedded in `<script>` tags
Use `_json_for_script_tag(value)` — not bare `json.dumps()`. It escapes `<`, `>`, `&`, U+2028, U+2029 to prevent `</script>` breakout and JS string literal corruption.

### Vendored assets
- `src/mdvw/assets/vendor/**` is hash-pinned via `src/mdvw/assets/vendor/manifest.json`
- **Never hand-edit vendored files.** To upgrade: `python scripts/fetch_vendor.py --update`, then commit.
- `.gitattributes` marks `vendor/**` as `-text` — do not remove this (LF→CRLF on Windows would break SHA256s).

### Linting
- Ruff ruleset: `E F W I UP B SIM RUF`; line length 100; target Python 3.13
- No per-file ignores. All new code must pass `ruff check` with zero warnings.

### GitHub Actions
- Workflow steps are pinned to **full commit SHAs** with the readable tag as a trailing comment
- To bump an action: `gh api repos/<org>/<action>/commits/<tag>` to get the SHA

### Release flow
```bash
# Edit CHANGELOG.md (## [Unreleased] section), commit
python scripts/release.py 0.2.0            # bumps __version__, dates changelog, commits, tags
git push origin main v0.2.0               # triggers release.yml → PyPI + GitHub Release
python scripts/release.py --post-release 0.3.0.dev0  # reopens dev cycle
```
`release.py` requires a clean tree and `__version__` ending in `.devN`. Use `--dry` to preview.
