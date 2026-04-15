# Changelog


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
