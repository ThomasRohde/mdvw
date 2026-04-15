# Changelog

## [Unreleased]

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
