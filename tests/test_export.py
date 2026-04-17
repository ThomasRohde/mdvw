"""Tests for the export module."""

from __future__ import annotations

import base64
from pathlib import Path

from mdvw.export import build_standalone_html


def test_standalone_html_contains_body():
    html = build_standalone_html("# Hello\n\nWorld", title="Test")
    assert "<h1>" in html
    assert "World" in html
    assert "<title>Test</title>" in html


def test_standalone_html_is_self_contained():
    html = build_standalone_html("Some text")
    # Should not reference external files
    assert 'src="' not in html
    assert 'href="vendor/' not in html


def test_export_never_embeds_file_uris(tmp_path: Path):
    """A self-contained export must not bake in local ``file://`` paths.

    Earlier versions passed the document directory to render_markdown as a
    ``file://`` base, which embedded absolute paths including usernames
    into every exported document — a privacy leak when the file was
    shared.
    """
    doc_dir = tmp_path / "notes"
    doc_dir.mkdir()
    source = "[link](other.md)\n"
    html = build_standalone_html(source, doc_dir=doc_dir)
    assert "file://" not in html
    # The href should stay relative so it still works if the HTML sits
    # next to the source tree.
    assert 'href="other.md"' in html


def test_export_inlines_local_images(tmp_path: Path):
    """Local images referenced by relative paths should be inlined as
    data URIs so the export is self-contained."""
    # 1x1 red PNG
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    doc_dir = tmp_path / "doc"
    doc_dir.mkdir()
    (doc_dir / "pic.png").write_bytes(png_bytes)

    html = build_standalone_html("![pic](pic.png)\n", doc_dir=doc_dir)
    assert "data:image/png;base64," in html
    # Original relative src should no longer be in an img tag.
    assert 'src="pic.png"' not in html


def test_export_rejects_image_path_traversal(tmp_path: Path):
    """A markdown doc trying to reach outside its directory with `../`
    must not resolve and inline that content."""
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    (secret_dir / "key.png").write_bytes(b"\x89PNG\r\n\x1a\n-sensitive-")

    doc_dir = tmp_path / "notes"
    doc_dir.mkdir()

    html = build_standalone_html(
        "![leak](../secrets/key.png)\n", doc_dir=doc_dir,
    )
    assert "sensitive" not in html
    assert "data:image/png" not in html


def test_export_rejects_percent_encoded_absolute_image(tmp_path: Path, monkeypatch):
    """Percent-encoded absolute / drive / UNC image sources must not
    reach the filesystem during export. Without decoding before the
    scheme/prefix checks, ``%5C%5Cserver…`` or ``C%3A%5CWindows…`` pass
    the validator and hit ``Path.resolve()``, which on Windows can hang
    export on an unreachable share."""
    from mdvw.export import _inline_local_image

    calls: list[Path] = []
    orig_resolve = Path.resolve

    def spy_resolve(self, *a, **kw):
        calls.append(Path(self))
        return orig_resolve(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", spy_resolve)

    doc_dir = tmp_path / "notes"
    doc_dir.mkdir()

    encoded_sources = [
        "%2Fetc%2Fpasswd.png",                              # /etc/passwd.png
        "C%3A%5CWindows%5CSystem32%5Cdrivers%5Chosts.png",  # C:\Windows\...
        "%5C%5Cevil.example%5Cshare%5Cx.png",               # \\evil.example\...
        "%2F%2Fevil.example%2Fshare%2Fx.png",               # //evil.example/...
    ]
    for src in encoded_sources:
        assert _inline_local_image(src, doc_dir) is None

    probed = [str(p) for p in calls]
    assert not any("etc" in p and "passwd" in p for p in probed)
    assert not any("Windows" in p for p in probed)
    assert not any("evil.example" in p for p in probed)


def test_export_leaves_remote_images_untouched(tmp_path: Path):
    """Remote (http/https) image URLs are already stripped by the
    sanitizer policy, so there's nothing to inline — just make sure we
    don't crash on them."""
    html = build_standalone_html(
        "![remote](https://example.com/x.png)\n", doc_dir=tmp_path,
    )
    assert "data:image" not in html


def test_standalone_html_includes_css():
    html = build_standalone_html("# Test")
    # The inlined CSS should contain our design tokens
    assert "--fg:" in html or "--bg:" in html


def test_standalone_html_with_frontmatter():
    source = "---\ntitle: My Doc\n---\n\n# Content"
    html = build_standalone_html(source)
    assert "Content" in html
    assert "md-frontmatter" in html


def test_html_escapes_title():
    html = build_standalone_html("test", title='<script>alert("xss")</script>')
    assert "&lt;script&gt;" in html
    assert "<script>alert" not in html


def test_export_bundles_katex_when_math_present():
    """Inline math must ship a KaTeX runtime so the export renders offline.

    Without this, exports would display raw TeX where the preview shows
    rendered equations.
    """
    html = build_standalone_html("Equation: $x^2 + y^2 = z^2$")
    # The rendered HTML contains a .math span the bootstrap will target.
    assert 'class="math' in html
    # KaTeX runtime + CSS must be inlined.
    assert "katex" in html.lower()
    # The primary (woff2) font format is baked in as a data URI so math
    # renders with correct glyphs offline. woff/ttf fallbacks stay as
    # relative paths — browsers pick the first working format (woff2
    # data URI) and never look further, so they harmlessly stay dormant.
    assert "data:font/woff2;base64," in html
    assert "url(fonts/KaTeX_Main-Regular.woff2)" not in html


def test_export_bundles_mermaid_when_diagram_present():
    """Mermaid diagrams need the mermaid runtime or they ship as raw source."""
    source = "```mermaid\ngraph TD; A-->B\n```\n"
    html = build_standalone_html(source)
    assert 'class="mermaid"' in html
    # The mermaid runtime is bulky; only verify a distinctive marker from
    # the library so we don't couple the test to its build details.
    assert "mermaid" in html.lower()
    # Bootstrap must call mermaid.render; if it's missing the diagram
    # stays as literal text.
    assert "mermaid.render" in html or "mermaid.initialize" in html


def test_export_bundles_hljs_for_code_blocks():
    """Fenced code with a language needs highlight.js to match the preview."""
    source = "```python\ndef hi():\n    return 1\n```\n"
    html = build_standalone_html(source)
    assert 'class="language-python"' in html
    assert "hljs" in html.lower()
    # The python language pack must be present.
    assert "highlightElement" in html


def test_export_skips_runtimes_when_not_needed():
    """Plain prose must not pay the KaTeX/Mermaid/hljs size tax.

    A 2 MB mermaid bundle dropped into every prose export would be a
    serious regression. Verifies the conditional-inline path actually
    excludes runtimes when none are referenced. We check for markers
    distinctive to each *runtime* (not their CSS selectors, which live
    in app.css regardless).
    """
    html = build_standalone_html("Just a paragraph of text.")
    # Distinctive API surface from each runtime. If any of these is
    # present, we've inlined the library unnecessarily.
    assert "katex.render" not in html
    assert "mermaid.initialize" not in html
    assert "hljs.highlightElement" not in html
    # And the bootstrap script only ships alongside a runtime.
    assert "function renderMath()" not in html


def test_export_only_bundles_referenced_hljs_languages():
    """Full hljs language pack is ~400 KB. Only ship what the doc needs."""
    source = "```python\npass\n```\n"
    html = build_standalone_html(source)
    # Sanity: python really is present.
    assert 'class="language-python"' in html
    # Unreferenced languages (rust, ruby) must not be inlined wholesale.
    # Check for a distinctive hljs-internal marker from those bundles.
    assert "hljs.registerLanguage(\"rust\"" not in html
    assert "hljs.registerLanguage(\"ruby\"" not in html
