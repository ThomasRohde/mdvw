# mdvw

Quick, portable, fully offline Markdown viewer and editor for Windows.

- **Offline-first**: KaTeX, Mermaid, highlight.js, and fonts all bundled — no network required.
- **GFM + extensions**: tables, task lists, footnotes, `==highlight==`, `++underline++`, `{color:…}…{/color}`.
- **Native feel**: system tray, follow-system dark/light theme, `.md` file associations.
- **Live reload**: edits on disk reflect instantly.

## Install

```
pip install mdvw
```

Python 3.13+ required. Windows only.

Or grab the standalone `mdvw-win-x64.zip` from [Releases](https://github.com/ThomasRohde/mdvw/releases).

## Usage

```
mdvw notes.md              # open a file
mdvw --edit notes.md       # open in edit mode
mdvw --no-tray             # no system tray icon
mdvw --register            # associate .md with mdvw
mdvw --unregister          # remove association
```

Shortcuts: `E` toggle edit, `Ctrl+S` save, `Ctrl+O` open.

## License

MIT
