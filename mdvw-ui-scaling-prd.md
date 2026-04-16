# PRD: Scalable UI Surface and High-Value Feature Expansion for `mdvw`

Version: 0.1  
Date: 2026-04-16  
Status: Ready for implementation  
Target repo: `ThomasRohde/mdvw`

## 1. Summary

`mdvw` is already a strong offline-first Windows Markdown viewer/editor with three modes (Read / Edit / Source), outline navigation, file browser, live reload, tray/single-instance behavior, file association, frontmatter display, and strong security hardening.

This PRD defines a scalable UI shell for the next wave of features so the product can grow without turning into a bloated IDE. The core recommendation is:

- keep the center document surface clean
- use a **command palette** as the primary expansion surface
- standardize on **reusable side panes**
- add a **right-side contextual inspector**
- add a thin **status bar** for state and diagnostics

This UI surface will support the first 5 high-value additions:

1. Search Everywhere
2. Sessions / Recents / Reopen Last
3. Paste/Drop Image Attachments
4. Export / Print
5. Diagnostics

## 2. Background and current product shape

`mdvw` currently provides:

- three modes: Read, Edit (split), Source
- offline rendering with vendored KaTeX, Mermaid, highlight.js, fonts
- GFM + extensions
- outline drawer and collapsible sections
- lazy-loading file browser sidebar
- live reload on external changes
- atomic save with disk-conflict prompt
- optional tray behavior and single-instance handoff
- YAML frontmatter card in preview
- follow-system theme
- Windows file association support
- strong security constraints for untrusted Markdown

The recent direction of the product suggests a small but increasingly capable desktop workbench rather than a single-page previewer. The next feature wave should strengthen that direction while preserving the app’s current speed, offline operation, and focus.

## 3. Problem statement

The current product can grow feature-by-feature, but without a clear UI model the result will likely be toolbar clutter, ad hoc drawers, and inconsistent interaction patterns.

We need a UI surface that:

- scales to more capabilities without visual bloat
- remains fast and keyboard-friendly
- preserves `mdvw`’s lightweight identity
- supports both mouse and keyboard users
- fits the current codebase and product philosophy
- keeps untrusted document handling and offline operation intact

## 4. Product goals

### Primary goals

1. Create a scalable, predictable UI shell for future feature growth.
2. Make new capabilities discoverable without crowding the main document view.
3. Improve daily-driver usefulness for real Markdown work.
4. Preserve `mdvw`’s core identity: small, fast, offline, safe, Windows-native.

### Secondary goals

1. Increase keyboard-first efficiency.
2. Make state visible without modal interruption.
3. Provide a clean home for document-level tooling like export and diagnostics.

## 5. Non-goals

This PRD does not aim to turn `mdvw` into:

- a full IDE
- a general-purpose note database
- a Git-aware workspace manager
- a plugin marketplace in this phase
- a cloud-synced application
- a multi-tab document management suite in this phase

Tabs may be revisited later, but they are intentionally not part of this first scaling surface.

## 6. Design principles

1. **Center stays sacred.** The document remains the main thing.
2. **One stable shell.** New features should land in predictable places.
3. **Palette first.** Commands scale better than buttons.
4. **Local-first.** No network dependency for core behavior.
5. **Safe by default.** New features must preserve untrusted-input protections.
6. **Keyboard and mouse parity.** Every major feature must be reachable both ways.
7. **Progressive disclosure.** Advanced capabilities should stay out of the way until needed.

## 7. Proposed UI architecture

## 7.1 Top bar

The top bar becomes the stable header across all modes.

### Responsibilities

- app/menu button
- current file name
- optional compact breadcrumb / parent folder hint
- mode switcher (Read / Edit / Source)
- save state indicator
- command palette entry point
- one overflow menu for rarely used actions

### Requirements

- keep it visually sparse
- do not add feature-specific permanent buttons unless they are used very frequently
- command palette entry should be visible and keyboard-accessible
- top bar must remain consistent across modes

### Rationale

The top bar should communicate “where am I and what state is this file in?” not become a ribbon.

## 7.2 Left utility pane

The current left-side surfaces should become one shared pane framework with switchable sections.

### Initial pane sections

- Files
- Outline
- Search
- Sessions
- Diagnostics

### Behavior

- only one section visible at a time
- pane can be collapsed globally
- pane width is resizable and persisted
- opening a file from Files/Search/Sessions should not spawn new windows
- pane state persists across launches

### Rationale

The existing file browser and outline already prove the usefulness of left-side navigation surfaces. The new sections fit the same mental model.

## 7.3 Center document area

The center remains the primary document workspace.

### Rules

- Read / Edit / Source remain the only center modes
- no permanent extra chrome inside the document view
- temporary overlays are allowed for:
  - in-document search
  - image drop affordance
  - export progress
  - conflict prompts
- contextual information should prefer side panes or inspector over inline clutter

## 7.4 Right contextual inspector

Introduce a collapsible right-side inspector for document-scoped tools and metadata.

### Initial inspector sections

- Frontmatter
- Export
- Attachments / Link info
- Document stats
- Preview options

### Behavior

- hidden by default
- can be opened by command palette, toolbar action, or keyboard shortcut
- content changes based on current file and selection where relevant
- must not be required for basic reading/editing

### Rationale

This gives frontmatter and future document-specific tooling a stable home without polluting the main reading flow.

## 7.5 Bottom status bar

Add a thin status bar for passive but important state.

### Initial contents

- current mode
- save/dirty state
- current file encoding if known
- line/column in Source mode
- word count / char count (current doc)
- diagnostics count
- external file changed indicator
- preview width mode
- optional current browse root label

### Requirements

- compact and low-noise
- click targets allowed for diagnostics count and mode
- no animated noise unless action is required

## 7.6 Command palette

The command palette is the primary growth mechanism.

### Goals

- unify discovery of actions
- reduce toolbar/menu bloat
- support keyboard-first workflows
- provide fuzzy find across commands, files, headings, and recent items

### Invocation

- `Ctrl+P` or `Ctrl+Shift+P`
- visible entry point in the top bar
- should open centered, lightweight, and fast

### Initial command categories

- File
- View
- Navigate
- Search
- Session
- Insert
- Export
- Diagnostics
- Developer (optional, only in debug/dev mode)

### Example commands

- Open File
- Reopen Last File
- Reopen Last Session
- Show Files Pane
- Show Outline Pane
- Show Search Pane
- Show Sessions Pane
- Show Diagnostics Pane
- Go to Heading…
- Find in File
- Search Workspace
- Paste Image as Attachment
- Export PDF
- Export HTML
- Print
- Show Frontmatter
- Show Export Inspector
- Toggle Preview Width
- Toggle Left Pane
- Toggle Right Inspector

### Non-requirement

This is not a VS Code-style omnibox with arbitrary extensibility yet. Keep scope tight.

## 8. Feature set to grow on this shell

## 8.1 Feature 1: Search Everywhere

### User value

This is the single highest-value capability for making `mdvw` a daily driver instead of just a file opener.

### Scope

Search must support:

1. **Find in current document**
   - plain text
   - next/previous
   - highlight all matches
   - optional match case
   - optional whole word

2. **Go to heading**
   - fuzzy search over current document headings
   - accessible from palette and Search pane

3. **Search files by name**
   - within current browse root

4. **Workspace text search**
   - search Markdown content under current browse root
   - return file, heading/context snippet, and line-ish context if feasible

### UI

- left pane: Search
- command palette shortcuts for fast access
- inline find overlay for current document search
- result list opens file in existing window and navigates to match

### Important constraints

- must remain responsive on large trees
- should index lazily or incrementally
- hidden/system/noise folders should follow existing file-browser exclusion rules where practical

### Suggested implementation approach

- start with filename + current-doc search
- then add workspace text search
- use a local lightweight index or incremental scan cache
- persist cache in app data, keyed by browse root and file mtimes/fingerprint
- reuse watcher infrastructure to invalidate search cache incrementally

## 8.2 Feature 2: Sessions / Recents / Reopen Last

### User value

The app now behaves like a persistent desktop process. Users should be able to get back to where they were.

### Scope

- recent files list
- recent folders / browse roots
- reopen last file on launch
- optional reopen last session
- pinned folders
- clear history action

### Definitions

**Session** in this phase means a lightweight persisted snapshot of:
- currently open file
- current mode
- left-pane section
- pane widths / collapsed state
- right-inspector state
- last browse root
- cursor/scroll position where feasible

This is not multi-tab state.

### UI

- left pane: Sessions
- command palette entries for recent files and reopen commands

### Suggested persistence

Use local config/state storage in `%APPDATA%\mdvw` or existing config location conventions.

## 8.3 Feature 3: Paste/Drop Image Attachments

### User value

This removes major friction from Markdown authoring and pairs naturally with `mdvw`’s local-relative-link model.

### Scope

- paste image from clipboard in Edit/Source
- drag image file into editor
- optional drag bitmap/screenshot into app
- store image under a predictable local folder
- insert relative Markdown link at cursor
- show resulting linked image in preview

### Default behavior

When inserting an image, `mdvw` should:

1. resolve the current document directory
2. ensure an attachment folder exists
3. save the image with a generated collision-safe filename
4. insert `![alt](relative/path.png)` at cursor

### Folder policy

Configurable, with default preference order:

1. `./images/`
2. `./assets/`
3. document directory root (fallback only)

### Naming policy

Default:
- `image-YYYYMMDD-HHMMSS.png`

Optional future enhancement:
- slug from clipboard source or prompt

### UI

- inline drop affordance
- right inspector shows last inserted asset and resolved path
- command palette command: Paste Image as Attachment

### Constraints

- do not support remote upload
- preserve offline-only posture
- sanitize paths and prevent writes outside allowed target tree unless user explicitly chooses a location

## 8.4 Feature 4: Export / Print

### User value

`mdvw` already has high-quality offline rendering. Export makes it useful for handoff and publication.

### Phase 1 scope

- Print
- Print Preview if supported cleanly by platform/webview
- Export to PDF
- Export to self-contained HTML

### Optional later scope

- Export with/without frontmatter card
- Export to DOCX (not in this phase)
- export theme variants

### UI

- right inspector: Export
- top-bar share/export entry
- command palette commands

### Export requirements

PDF:
- based on current rendered document
- preserve math, Mermaid, syntax highlighting
- preserve local image references in output

Self-contained HTML:
- produce a single portable file
- embed required CSS/JS/fonts/assets or otherwise guarantee offline portability
- no remote URLs introduced by export

### Constraints

- exported output must not weaken `mdvw`’s trust model when opened inside `mdvw`
- export is a file-generation workflow, not a publishing pipeline

## 8.5 Feature 5: Diagnostics

### User value

A diagnostics surface makes `mdvw` more trustworthy for documentation work.

### Phase 1 diagnostics

- invalid YAML frontmatter
- broken relative image paths
- broken relative document links
- duplicate heading ids / ambiguous anchors where determinable
- Mermaid render errors if surfaced
- unsupported or blocked remote resource references
- optional basic markdown warnings

### UI

- left pane: Diagnostics
- status bar diagnostics badge
- clicking a diagnostic navigates to location where possible
- diagnostics can be grouped by severity:
  - Error
  - Warning
  - Info

### Rules

- diagnostics must be non-destructive
- diagnostics should not block rendering unless safety requires it
- rendering and editing remain primary; diagnostics augment them

## 9. Interaction model

## 9.1 Predictable homes for features

Every new capability should first answer:
- Does it belong in the command palette?
- Does it belong in the left utility pane?
- Does it belong in the right inspector?
- Does it belong in the status bar?
- Does it really need a permanent toolbar button?

Default rule:
- navigation and discovery → left pane / palette
- document-scoped tools → right inspector / palette
- passive state → status bar
- frequently repeated commands → palette and shortcut first

## 9.2 Keyboard shortcut policy

Existing shortcuts remain unchanged.

### New proposed shortcuts

- `Ctrl+P` — command palette
- `Ctrl+F` — find in file
- `Ctrl+Shift+F` — search workspace
- `Ctrl+Shift+O` — go to heading
- `Ctrl+R` — recents / sessions quick switcher (optional)
- `Ctrl+.` — diagnostics pane (optional)
- `Ctrl+Alt+I` — toggle right inspector (optional)

Shortcut conflicts should be checked against pywebview/WebView2 behavior and text editing expectations.

## 9.3 Empty states

The new shell must have polished empty states:

- Search pane before first search
- Sessions pane before any history exists
- Diagnostics pane when no issues are present
- Export inspector when no file is open
- Files pane when launched without a file and no browse root is available

## 10. Technical design guidance

## 10.1 Architecture guidance

This PRD does not prescribe a full rewrite. It assumes incremental evolution from the current Python + pywebview architecture.

### Suggested new internal modules

- `commands.py` — command registry and palette actions
- `state.py` — UI/session state persistence
- `search.py` — current-doc and workspace search services
- `search_index.py` — optional cached workspace index
- `sessions.py` — recent files, pinned roots, reopen-last
- `attachments.py` — clipboard/drop image save + markdown insertion
- `export.py` — print/pdf/html export workflows
- `diagnostics.py` — diagnostics collection and normalization

These names are suggestions, not mandates.

## 10.2 State model

Persist at least:

- last open file
- last browse root
- recent files
- pinned roots
- active left pane section
- left pane collapsed state
- left pane width
- right inspector visibility
- right inspector width
- current mode
- preview width mode

Persist optionally:
- cursor position
- scroll position
- last palette query
- recent searches

## 10.3 Search indexing strategy

Recommended phased strategy:

### Phase A
- current-doc search only
- heading jump
- filename search in current browse root

### Phase B
- workspace text search via incremental scan
- basic caching keyed by file fingerprint

### Phase C
- lightweight persisted index with invalidation via watcher events

Do not over-engineer full-text search in v1 of this feature. Good-enough local search beats a heavy indexing subsystem.

## 10.4 Security requirements

All new features must preserve the current security posture.

### Specific rules

- image attachment writes must stay within explicit user-controlled local paths
- export must not introduce unexpected remote fetches
- diagnostics must not execute document content
- search indexing must not trust document HTML; index source Markdown or safe derived text
- palette commands must not bypass existing conflict-save logic

## 10.5 Performance requirements

### Startup

- startup regression from this UI shell work should be minimal
- no expensive workspace indexing on cold start unless explicitly enabled or amortized lazily

### Interactions

- command palette should feel instant
- pane switching should feel instant
- Search pane should render partial results progressively when needed
- large trees must not block the UI thread

## 11. User stories

### Search
- As a user, I want to find text in the current document without leaving the keyboard.
- As a user, I want to jump to a heading quickly.
- As a user, I want to search a Markdown workspace by filename and content.

### Sessions
- As a user, I want `mdvw` to remember what I was working on.
- As a user, I want to reopen recent files quickly.
- As a user, I want to pin important folders.

### Attachments
- As a user, I want to paste a screenshot directly into my Markdown doc.
- As a user, I want local image paths inserted automatically and correctly.

### Export
- As a user, I want to print or export a polished version of the current doc.
- As a user, I want to share an offline-safe HTML file.

### Diagnostics
- As a user, I want obvious document problems surfaced without breaking my flow.
- As a user, I want broken links and invalid frontmatter called out quickly.

## 12. Acceptance criteria

## 12.1 Shell

- A left utility pane exists with switchable sections.
- A right contextual inspector exists and can be toggled.
- A command palette exists and can invoke registered actions.
- A bottom status bar exists and displays current mode and save state.
- Existing Read / Edit / Source workflows still work.

## 12.2 Search Everywhere

- `Ctrl+F` opens current-document find.
- `Ctrl+Shift+O` can fuzzy-jump to headings.
- Search pane can search filenames.
- Search pane can search workspace contents under current browse root.
- Clicking a result opens the file in the existing instance and navigates to the result.
- Large workspaces do not freeze the UI.

## 12.3 Sessions

- Recent files persist across launches.
- Reopen Last File works.
- Pinned roots persist across launches.
- Left/right pane state persists across launches.

## 12.4 Image attachments

- Pasting an image into a Markdown doc creates a local file and inserts a relative Markdown reference.
- Dragging an image file into the app inserts a relative reference instead of a raw absolute path by default.
- If the document has not been saved yet, the user is prompted to choose a base location before attachment write.

## 12.5 Export

- Print works for the current document.
- Export PDF produces a readable document preserving math/code/diagrams.
- Export self-contained HTML works offline after creation.

## 12.6 Diagnostics

- Invalid YAML frontmatter is shown in Diagnostics.
- Broken local image/document links are shown in Diagnostics.
- Blocked remote resource references are shown as warnings or info.
- Clicking a diagnostic navigates to the relevant location when feasible.

## 13. Delivery plan

## Phase 1 — Shell foundation

Deliver:
- command palette
- left utility pane framework
- right inspector framework
- status bar
- state persistence for pane visibility and sizes

Definition of done:
- existing features continue working
- no noticeable startup regression
- shell is stable enough for additional features

## Phase 2 — Search and sessions

Deliver:
- current-doc find
- go to heading
- recent files
- reopen last file
- sessions pane
- filename search
- basic workspace text search

Definition of done:
- keyboard-first workflows feel fast
- recents/session persistence is reliable
- large tree search is usable

## Phase 3 — Export and diagnostics

Deliver:
- export inspector
- print / PDF / self-contained HTML
- diagnostics pane
- broken link/image checks
- frontmatter diagnostics normalization

Definition of done:
- exports are stable and offline-safe
- diagnostics are useful and non-noisy

## Phase 4 — Image attachments

Deliver:
- paste image from clipboard
- drag/drop image insertion
- attachment folder policy
- attachment inspector details

Definition of done:
- common screenshot workflow is frictionless
- path handling is safe and predictable

## 14. Testing requirements

## 14.1 Automated tests

Add tests for:

- command registry behavior
- persisted state load/save
- recent files/session persistence
- search result generation and ranking
- index invalidation logic if index is added
- relative path generation for attachments
- export file generation smoke tests
- diagnostics generation for broken links/frontmatter
- unsaved-document image attachment flow
- no-conflict regression with existing save/conflict logic

## 14.2 Manual test matrix

Test on:

- Windows 10
- Windows 11
- light theme / dark theme
- with tray / `--no-tray`
- launched with file
- launched without file
- reopened via single-instance handoff
- large folder tree
- unsaved buffer + external file change
- docs with Mermaid / KaTeX / many images / invalid YAML

## 15. Risks and mitigations

### Risk: UI bloat
Mitigation: route almost all new actions through pane + palette + inspector patterns.

### Risk: startup slowdown
Mitigation: keep indexing lazy and amortized; do not scan workspaces eagerly on startup.

### Risk: inconsistent state behavior
Mitigation: centralize UI/session persistence in one state service.

### Risk: attachment path surprises
Mitigation: clear folder policy, confirmation on first use, fallback prompt when base path is ambiguous.

### Risk: export complexity
Mitigation: phase export narrowly; prioritize print/PDF/self-contained HTML only.

### Risk: diagnostics false positives
Mitigation: severity levels, clear messages, and suppress low-confidence checks initially.

## 16. Open questions for implementer

These do not block the first implementation pass, but should be resolved explicitly in code or follow-up notes:

1. Which shortcut should own the command palette: `Ctrl+P` or `Ctrl+Shift+P`?
2. Should workspace search ship with a persisted index immediately or start with on-demand scan + cache?
3. Should self-contained HTML export inline fonts and scripts fully, or create a sibling asset folder in v1?
4. What exact config file format and location should be used for persisted state?
5. Should image attachment folder preference be global config, per-folder memory, or both?

## 17. Recommended implementation order inside the repo

1. Introduce command registry and palette.
2. Introduce shared pane state model.
3. Refactor existing Files and Outline onto the shared left-pane framework.
4. Add right inspector and status bar.
5. Add recent files and reopen-last.
6. Add current-doc find and heading jump.
7. Add filename and workspace search.
8. Add export inspector and export backends.
9. Add diagnostics framework.
10. Add image attachment workflow.

This order reduces rework because the shell is in place before feature complexity grows.

## 18. Definition of success

This initiative is successful when:

- `mdvw` still feels small and fast
- users can discover many more capabilities without UI clutter
- the app becomes materially more useful for daily Markdown work
- the product remains offline-first and safe by default
- future features now have obvious landing zones in the UI

## 19. Explicit implementation guidance for the coding agent

- Do not redesign `mdvw` into a heavy IDE shell.
- Preserve current shortcuts and behavior unless this PRD explicitly adds to them.
- Favor incremental refactors over rewrites.
- Reuse existing browse-root, watcher, and conflict-save concepts wherever possible.
- Keep feature flags or clear internal seams where complexity is introduced.
- Prefer simple, robust implementations over ambitious frameworks.
- Preserve offline guarantees and untrusted-input protections in every new feature path.
