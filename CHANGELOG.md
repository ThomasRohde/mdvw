# Changelog


## [Unreleased]


## [0.6.1] — 2026-04-17
### Fixed
- **Inspector frontmatter panel was blank for documents with date
  fields.** PyYAML parses `date: 2026-04-15` into a `datetime.date`,
  which pywebview's JS bridge cannot JSON-serialize — the call
  resolved to nothing and the panel never rendered, while Document
  Stats (pure JS off the source) populated fine and made the silent
  failure easy to miss. `parse_frontmatter_fields` now coerces
  non-JSON-native values to strings via `default=str`.
- **Export HTML failed silently.** `create_file_dialog(SAVE_DIALOG)`
  in pywebview 6.x on Windows (winforms backend) returns a 1-tuple
  `(path,)`, not a bare string. `Path(result)` raised a `TypeError`
  that pywebview swallowed, leaving the JS caller with `undefined`
  and no flash. A shared `_save_dialog_path` helper now normalizes
  both shapes (tuple and string), used by export HTML and the save-as
  picker.
- **Printing clipped the output to the first page.** The app's CSS
  chains `height: 100%` / `overflow: hidden` from `html`/`body`
  through `#main`/`#center`/`.split` down to `#preview`, so the
  preview scrolls inside one viewport. The print stylesheet overrode
  `display` but not those height/overflow clamps, so `window.print()`
  saw a single-viewport canvas. Print now releases every constraint
  in the chain and adds `break-after: avoid` on headings + the
  frontmatter card and `break-inside: avoid` on `pre`/`table`/
  `figure`/`img` for cleaner pagination.


## [0.6.0] — 2026-04-17
### Features
- **Workspace text search.** A new left-pane search section
  (Ctrl+Shift+F) scans every `.md`/`.markdown` file under the workspace
  root for a query string, grouped by file with the matched line
  highlighted in the result list. Symlinked files that resolve outside
  the workspace are skipped so the search cannot read arbitrary disk
  content. Clicking a hit opens the file and pre-fills the in-document
  find bar with the same query, so the match is highlighted and
  scrolled into view instead of cold-opening the document.
- **Find in document.** Ctrl+F opens a find bar with match count,
  previous/next navigation, and case-sensitive / whole-word toggles.
  Works in Read and Edit modes (highlights in preview) and in Source
  mode (selects in the textarea).
- **Document diagnostics.** A new diagnostics section flags invalid
  frontmatter, broken relative links/images, and blocked remote
  references. Runs on demand and re-evaluates after each render.
- **Self-contained HTML export.** `export_html` produces a single-file
  HTML with inlined CSS, fonts, and image data URIs — the exported
  document renders identically to the preview, fully offline. Paired
  with `print_document` for print-to-PDF via the WebView.
- **Command palette.** A unified palette blends slash-command matches
  with filename matches from the workspace (when a browse root is
  set), so filename jumps and command execution share one input.
- **Image paste.** Pasting an image from the clipboard into the editor
  saves it as a PNG alongside the current document and inserts a
  relative `![](…)` reference.
- **Document inspector + status bar.** A left-pane Inspector shows
  parsed frontmatter fields and document stats (words, characters,
  headings, reading time). A footer status bar shows the active mode,
  dirty state, word count, and editor cursor position.

### Changed
- **Left pane sections.** The sidebar replaces the single file tree
  with switchable sections: Files, Recent, Outline, Search,
  Diagnostics, and Inspector. Active section and pane geometry
  persist in `%APPDATA%/mdvw/state.json`, kept separate from
  `config.json` (user preferences) so transient UI state doesn't
  pollute the user-facing config.
- **Outline collapse/expand.** Headings can be collapsed to hide all
  nested content in the preview. Auto-collapse respects child state
  and preserves manual overrides across re-renders.


## [0.5.1] — 2026-04-16
### Fixed
- **Window opens behind Explorer.** Double-clicking a `.md` file in
  Windows Explorer now reliably brings mdvw to the foreground — both on
  first launch and on subsequent IPC hand-offs to the existing instance.
  The short-lived client process grants foreground rights to the server
  via `AllowSetForegroundWindow` before handing off.


## [0.5.0] — 2026-04-16
### Features
- **YAML frontmatter card.** Markdown files with a `---`-fenced YAML
  header now display the raw metadata in a styled card at the top of
  the preview pane instead of rendering it as a thematic break and
  paragraph text. Invalid YAML shows an error card; the body still
  renders normally. Edit frontmatter in Source mode — original
  formatting is preserved on save.

### Fixed
- **Tray quit hang.** Clicking Quit in the system tray no longer leaves
  the Python process running. The `_on_closing` handler was vetoing
  `window.destroy()` because it always treated tray mode as
  "close-to-tray"; a `_quitting` flag now lets the tray's Quit action
  bypass the veto.


## [0.4.0] — 2026-04-15
### Changed
- **Close-to-tray.** Clicking the window's **X** now hides the window
  instead of exiting, when the tray icon is running. The process stays
  alive so a subsequent `mdvw file.md` is effectively instant. Quit is
  the tray's right-click → **Quit** (moves the unsaved-changes prompt
  there). Tooltip updates to "mdvw — running (right-click to quit)"
  while hidden. `--no-tray` preserves the previous X-exits behavior.

### Features
- **Single-instance handoff.** A second `mdvw foo.md` invocation no
  longer spawns a duplicate tray icon: it hands the file path to the
  already-running instance over a loopback socket (`127.0.0.1`, port
  recorded in `%APPDATA%\mdvw\instance.lock`) and exits. The running
  instance pops the window forward and loads the new file. Stale
  lockfiles are detected via connect-refused and cleared. Windows +
  tray only; `--no-tray` opts out entirely.

## [0.3.2] — 2026-04-15
### Fixed
- File-association icons. `mdvw --register` now writes `DefaultIcon`
  entries for the ProgID, `Applications\mdvw.exe`, and
  `Capabilities\ApplicationIcon`, so `.md` files show mdvw's rocket in
  Explorer and the "Open with" dialog no longer falls back to pip's
  generic gui-launcher stub icon.
- `mdvw --register` now opens Settings → Default apps preselected on
  mdvw (`ms-settings:defaultapps?registeredAppUser=mdvw`) so the user
  can flip the default in one step. Windows intentionally blocks apps
  from setting themselves as default without explicit user consent.
- `assoc.py` `print()` calls hardened against `sys.stdout is None`
  (the in-app "register" prompt runs under a windowed launcher where
  stdio is not attached).

## [0.3.1] — 2026-04-15
### Fixed
- `pip install mdvw` no longer generates a console-subsystem `mdvw.exe`
  that flashes a cmd window on file-association or shortcut launch. The
  entry moved from `[project.scripts]` to `[project.gui-scripts]`, so
  pip produces a GUI-subsystem launcher instead. CLI diagnostics
  (`--register`, `--version`, `--help`) still work via
  `python -m mdvw …` from a terminal.
- Stderr diagnostics no longer crash the save path or close handler
  when launched under `pythonw.exe` or a PyInstaller windowed build
  (where `sys.stderr is None`).

## [0.3.0] — 2026-04-15
### Changed
- File browser sidebar now loads lazily: only the launch directory's
  immediate children are fetched on open, and each subfolder is fetched
  on first expand. Eliminates the multi-second stall when starting
  `mdvw` in a large tree. Folders render collapsed by default.

## [0.2.0] — 2026-04-15
<!-- Add notes for the next release here. `scripts/release.py VERSION`
     will rename this section to `[VERSION] — YYYY-MM-DD`, bump
     src/mdvw/__init__.py, commit, and tag. -->

### Features
- File browser sidebar with a permanent burger toggle in the toolbar.
  Shows a collapsible tree of markdown files under the launch directory
  (`Path.cwd()`), skipping `.git`, `node_modules`, and other noise dirs.
  Clicking a file loads it and auto-collapses the panel; the existing
  dirty-buffer prompt is reused so unsaved edits aren't silently lost.
  Auto-opens on first paint when `mdvw` is launched without a file.

## [0.1.0] — 2026-04-15

Initial public release.

### Features
- Offline Markdown viewer/editor for Windows, Python 3.13+
- Three view modes: Read / Edit (split) / Source
- KaTeX math, Mermaid diagrams, highlight.js syntax highlighting — all vendored
- GFM + extensions: tables, task lists, footnotes, `==highlight==`, `++underline++`, `{color:…}…{/color}`
- Outline drawer, collapse/expand sections, follow-system theme
- System tray (optional), `.md` file association via `mdvw --register`
- Live reload on external file changes
