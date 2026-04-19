# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Working style

Behavioral defaults. Use judgement on trivial tasks; these bias toward caution over speed.

**Think before coding.** State assumptions explicitly; if uncertain, ask. If multiple interpretations exist, surface them — don't pick silently. If a simpler approach exists, say so. When something is unclear, stop and name what's confusing rather than guessing.

**Simplicity first.** Write the minimum code that solves the problem. No features, abstractions, configurability, or error handling beyond what was asked. If 200 lines could be 50, rewrite. "Would a senior engineer call this overcomplicated?" — if yes, simplify.

**Surgical changes.** Touch only what you must. Don't "improve" adjacent code, comments, or formatting. Don't refactor things that aren't broken. Match existing style. Remove imports/variables your changes orphaned; leave pre-existing dead code alone (mention it instead). Every changed line should trace to the request.

**Goal-driven execution.** Turn asks into verifiable goals ("Fix the bug" → "Write a failing test that reproduces it, then make it pass"). For multi-step work, state the plan as `step → verify` pairs and loop until each check passes.

## Commands

- `pytest -q` — run the test suite (112 tests as of 0.6.0.dev0).
- `ruff check src tests scripts` — lint. Strict config (`E F W I UP B SIM RUF`, no ignores); CI fails on any warning. New code must land clean.
- `python scripts/fetch_vendor.py --verify` — verify vendored JS/CSS hashes match `src/mdvw/assets/vendor/manifest.json`. CI runs this on every build.

## Vendor integrity (hard invariant)

`src/mdvw/assets/vendor/**` is a committed snapshot of KaTeX, Mermaid, highlight.js, and fonts, hash-pinned in `src/mdvw/assets/vendor/manifest.json`.

- Never hand-edit vendored files.
- To add/upgrade: `python scripts/fetch_vendor.py --update` (rewrites the manifest), then commit.
- `.gitattributes` marks the whole `vendor/**` tree as `-text` so Windows checkouts don't LF→CRLF them and break the SHA256s. Don't disable this.

## Release flow

The project uses a version-bump + tag on the **same commit** so the PyPI/GitHub artifact source matches the tag byte-for-byte.

```bash
# Write notes under `## [Unreleased]` in CHANGELOG.md, commit.
python scripts/release.py 0.2.0               # atomic: bump __version__, date the section, commit, tag v0.2.0
git push origin main v0.2.0                    # release.yml → PyPI + GH Release
python scripts/release.py --post-release 0.3.0.dev0   # reopen dev cycle
```

`release.py` requires a clean tree and that `__version__` currently ends in `.devN`. `--dry` shows changes without writing.

## pywebview gotchas (have bitten us; don't re-break)

- **Do not add public attributes to `JsApi`** (e.g., `self.window = …`). pywebview enumerates them for JS exposure and recurses into `.NET` objects like `window.native.AccessibilityObject.Bounds.Empty.Empty…` until it hits the recursion limit. All state is underscore-prefixed; keep it that way.
- **Do not call `window.evaluate_js(...)` from the `closing` event handler.** Both run on the UI thread → deadlock → app becomes unresponsive until many close-button clicks. The closing guard reads the mirrored `api._dirty` instead.
- Window icon is attached via `WM_SETICON` after `loaded` + AUMID via `SetCurrentProcessExplicitAppUserModelID` so the Windows taskbar groups mdvw separately from `python.exe`. See `app.py:_set_window_icon` / `_set_app_user_model_id`.

## Sanitizer invariants

`src/mdvw/render.py` runs user Markdown through `nh3`. Several hardening choices came out of multi-round adversarial review; don't loosen without re-reading the commit history around them:

- **`id` attribute is stripped** from user HTML so a `<div id="md-source">` in a `.md` file can't shadow bootstrap elements.
- **`img src` accepts only `data:` URIs and strictly-relative paths.** No `http(s)`, no protocol-relative `//host`, no UNC `\\server`, no absolute paths. Remote image loads would leak document-open telemetry and defeat the offline posture.
- **`file:` is rejected as a link scheme.** A hostile Markdown file could otherwise ShellExecute a local `.exe` via `os.startfile`.

## Architecture notes worth knowing

- `app.py` writes a per-instance `index.html` to a fresh `tempfile.mkdtemp("mdvw-")` dir (not the package dir — that may be read-only in installed envs). App asset URLs are rewritten to absolute `file://` paths against the packaged assets dir; user-markdown relative URLs are rewritten against the document's own directory. No document-wide `<base href>` (it would misdirect user links).
- `save_file` uses `_atomic_write_text` (tmp + fsync + `os.replace`) and has mtime/size conflict detection via `_loaded_fingerprint`. `_load(reason="watch")` parks the new fingerprint in `_pending_fingerprint`; JS must call `api.ack_reload()` to promote it. Rejecting a watched reload leaves the old baseline intact so the next save still prompts.
- GitHub Actions are pinned to full commit SHAs with the readable tag as a trailing comment. When bumping, look up the new SHAs with `gh api repos/<name>/commits/<tag>`. 
