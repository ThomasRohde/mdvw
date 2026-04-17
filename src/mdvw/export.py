"""Export workflows for mdvw.

Produces self-contained HTML files and supports print/PDF via the WebView.
"""

from __future__ import annotations

import base64
import re
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote

from .frontmatter import split_frontmatter
from .render import render_frontmatter_card, render_markdown

_ASSETS = files("mdvw") / "assets"

# Cap per-image inline size; above this we leave the relative src intact so
# the export doesn't balloon to hundreds of megabytes on photo-heavy docs.
_INLINE_IMG_MAX_BYTES = 10 * 1024 * 1024

_INLINE_IMG_MIME: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "svg": "image/svg+xml",
}

_IMG_SRC_RE = re.compile(
    r'(<img\b[^>]*?\bsrc=")([^"]+)("[^>]*>)',
    re.IGNORECASE,
)


def _inline_local_image(src: str, doc_dir: Path) -> str | None:
    """Return a data-URI replacement for a relative image src, or None.

    Accepts only strictly-relative paths (matching the sanitizer's img-src
    policy). Rejects absolute paths, schemes, authorities, and anything
    that resolves outside *doc_dir*. Size- and extension-capped.
    """
    if not src:
        return None
    # Decode percent-escapes BEFORE the scheme / authority / drive-letter
    # checks — otherwise `%5C%5Cserver…` or `C%3A%5CWindows` slip past the
    # prefix/scheme guards as innocuous-looking relative paths and reach
    # ``Path.resolve()`` on a hostile absolute/UNC target, which during
    # export can hang on an unreachable share.
    decoded = unquote(src)
    low = decoded.lower()
    if low.startswith(("data:", "http:", "https:", "file:", "mailto:", "ftp:")):
        return None
    if decoded.startswith(("#", "/", "\\", "//", "\\\\")):
        return None
    # Reject any scheme that passed the prefix checks above. Check both
    # `/` and `\` so `C:\x` (no forward slash) is still classified as a
    # drive-qualified path rather than a bare filename.
    first_slash = min(
        (i for i in (decoded.find("/"), decoded.find("\\")) if i != -1),
        default=-1,
    )
    first_colon = decoded.find(":")
    if first_colon != -1 and (first_slash == -1 or first_colon < first_slash):
        return None

    ext = Path(decoded).suffix.lower().lstrip(".")
    mime = _INLINE_IMG_MIME.get(ext)
    if mime is None:
        return None

    try:
        doc_dir_resolved = doc_dir.resolve()
        target = (doc_dir / decoded).resolve()
    except OSError:
        return None
    if not target.is_relative_to(doc_dir_resolved):
        return None
    if not target.is_file():
        return None
    try:
        if target.stat().st_size > _INLINE_IMG_MAX_BYTES:
            return None
        data = target.read_bytes()
    except OSError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _inline_relative_images(html: str, doc_dir: Path) -> str:
    def _sub(m: re.Match[str]) -> str:
        inlined = _inline_local_image(m.group(2), doc_dir)
        if inlined is None:
            return m.group(0)
        return f"{m.group(1)}{inlined}{m.group(3)}"

    return _IMG_SRC_RE.sub(_sub, html)


_KATEX_FONT_URL_RE = re.compile(r"url\(fonts/(KaTeX_[A-Za-z_-]+)\.woff2\)")
_HLJS_LANG_RE = re.compile(r'language-([A-Za-z0-9_+\-]{1,32})')


def _read_asset(*parts: str) -> str:
    return (_ASSETS.joinpath(*parts)).read_text(encoding="utf-8")


def _katex_css_with_inlined_fonts() -> str:
    """Return KaTeX CSS with woff2 ``url(fonts/…)`` rewritten to data URIs.

    The CSS lists woff2/woff/ttf as fallbacks; only woff2 ships in the
    vendor tree, so leaving bare ``url(fonts/…)`` paths in an exported
    HTML file would 404 in every browser and the math would fall back to
    system fonts. Inlining just the woff2 variants keeps math rendering
    correctly without bundling three font formats we don't have.
    """
    css = _read_asset("vendor", "katex", "katex.min.css")
    fonts_dir = _ASSETS / "vendor" / "katex" / "fonts"

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        font_path = fonts_dir / f"{name}.woff2"
        if not font_path.is_file():
            return m.group(0)
        data = base64.b64encode(font_path.read_bytes()).decode("ascii")
        return f"url(data:font/woff2;base64,{data})"

    return _KATEX_FONT_URL_RE.sub(_sub, css)


def _hljs_language_files(html: str) -> list[Path]:
    """Pick only the hljs language bundles referenced in *html*.

    Exports rarely need the full 20-language pack, so we inline just the
    ones that appear as ``language-…`` classes in the rendered body.
    """
    langs_dir = _ASSETS / "vendor" / "hljs" / "languages"
    seen: set[str] = set()
    paths: list[Path] = []
    for lang in _HLJS_LANG_RE.findall(html):
        lang = lang.lower()
        if lang in seen:
            continue
        seen.add(lang)
        candidate = langs_dir / f"{lang}.min.js"
        if candidate.is_file():
            paths.append(candidate)
    return paths


# Self-contained initialization script for the export. Mirrors app.js
# render paths but drops the theme / preview-scoped wiring — the export
# is a single <article>, not the full mdvw UI.
_EXPORT_BOOTSTRAP_JS = """
(function(){
  function renderMath(){
    if (window.renderMathInElement) {
      try {
        window.renderMathInElement(document.body, {
          delimiters: [
            {left: '$$', right: '$$', display: true},
            {left: '$', right: '$', display: false}
          ],
          throwOnError: false,
          ignoredTags: ['script','noscript','style','textarea','pre','code'],
          ignoredClasses: ['mermaid']
        });
      } catch(e) {}
    }
    if (window.katex) {
      document.querySelectorAll('.math').forEach(function(el){
        try {
          window.katex.render(el.textContent, el, {
            displayMode: el.classList.contains('math-display'),
            throwOnError: false
          });
        } catch(e) {}
      });
    }
  }
  function renderMermaid(){
    if (!window.mermaid) return;
    try {
      window.mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'strict'
      });
    } catch(e) { return; }
    var blocks = document.querySelectorAll('pre.mermaid');
    blocks.forEach(function(el, i){
      var id = 'mermaid-' + Date.now() + '-' + i;
      window.mermaid.render(id, el.textContent).then(function(r){
        el.innerHTML = r.svg;
      }).catch(function(e){
        el.textContent = 'Mermaid error: ' + (e && e.message ? e.message : e);
      });
    });
  }
  function highlight(){
    if (!window.hljs) return;
    document.querySelectorAll('pre.code-block > code[class*="language-"]').forEach(function(code){
      try { window.hljs.highlightElement(code); } catch(e) {}
    });
  }
  renderMath();
  renderMermaid();
  highlight();
})();
"""


def build_standalone_html(
    source: str,
    doc_dir: Path | None = None,
    title: str = "mdvw export",
) -> str:
    """Render *source* to a self-contained HTML file.

    Inlines the app CSS, local images (data URIs, size- and type-capped),
    and — when the document needs them — the KaTeX, Mermaid, and
    highlight.js runtimes plus an init script. Only the enhancements a
    given document actually uses are embedded, so a plain-prose export
    stays small while a math/diagram-heavy one still renders fully
    offline.

    *doc_dir* is the filesystem directory containing the source document;
    it's used only to resolve relative image references. No ``file://``
    URIs are embedded in the output — earlier versions passed a
    ``doc_base`` URI through ``render_markdown`` and leaked absolute local
    paths (and thus usernames / directory layouts) into every shared
    export.
    """
    from .frontmatter import parse_frontmatter

    raw_yaml, body = split_frontmatter(source)
    card = ""
    if raw_yaml is not None:
        _meta, _body, err = parse_frontmatter(source)
        card = render_frontmatter_card(raw_yaml, err)
    # Deliberately no doc_base: relative href/src stay relative in the
    # exported HTML. Links keep working if the file sits next to the
    # source tree; images get inlined below.
    html_body = card + render_markdown(body)
    if doc_dir is not None:
        html_body = _inline_relative_images(html_body, doc_dir)

    # Read and inline the app CSS
    css = _read_asset("app.css")

    # Detect which client-side renderers the body actually needs.
    needs_math = 'class="math' in html_body
    needs_mermaid = 'class="mermaid"' in html_body
    needs_hljs = '<code class="language-' in html_body

    styles: list[str] = []
    scripts: list[str] = []
    if needs_math:
        styles.append(f"<style>{_katex_css_with_inlined_fonts()}</style>")
        scripts.append(f"<script>{_read_asset('vendor', 'katex', 'katex.min.js')}</script>")
        scripts.append(
            f"<script>{_read_asset('vendor', 'katex', 'auto-render.min.js')}</script>"
        )
    if needs_hljs:
        styles.append(f"<style>{_read_asset('vendor', 'hljs', 'github.min.css')}</style>")
        scripts.append(f"<script>{_read_asset('vendor', 'hljs', 'highlight.min.js')}</script>")
        for lang_path in _hljs_language_files(html_body):
            scripts.append(f"<script>{lang_path.read_text(encoding='utf-8')}</script>")
    if needs_mermaid:
        scripts.append(f"<script>{_read_asset('vendor', 'mermaid', 'mermaid.min.js')}</script>")
    if needs_math or needs_mermaid or needs_hljs:
        scripts.append(f"<script>{_EXPORT_BOOTSTRAP_JS}</script>")

    extra_styles = "\n".join(styles)
    extra_scripts = "\n".join(scripts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_escape(title)}</title>
{extra_styles}
<style>{css}</style>
<style>
  /* Export overrides: hide app chrome */
  #toolbar, #main, #left-pane, #right-pane, #status-bar,
  .pane-resize-handle, #find-bar, #command-palette,
  .palette-backdrop, #toast {{ display: none !important; }}
  body {{ display: block; padding: 40px clamp(24px, 5vw, 72px); }}
</style>
</head>
<body>
<article class="markdown-body">
{html_body}
</article>
{extra_scripts}
</body>
</html>"""


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
