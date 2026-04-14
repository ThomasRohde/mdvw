"""Vendor fetcher with SHA256 integrity verification.

Modes:
    python scripts/fetch_vendor.py --update   # fetch fresh, overwrite manifest (human bootstrap)
    python scripts/fetch_vendor.py --verify   # verify committed files match manifest (CI default)
    python scripts/fetch_vendor.py            # smart: fetch missing files, verify the rest

Release builds must use --verify so a compromised CDN or changed upstream
package can't quietly inject executable JS into release artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "src" / "mdvw" / "assets" / "vendor"
MANIFEST = VENDOR / "manifest.json"

KATEX_VERSION = "0.16.22"
MERMAID_VERSION = "11.4.1"
HLJS_VERSION = "11.11.1"

HLJS_LANGS = [
    "python", "typescript", "javascript", "rust", "go", "java",
    "c", "cpp", "csharp", "ruby", "bash", "json", "yaml",
    "sql", "xml", "css", "markdown",
]

KATEX_FONTS = [
    "KaTeX_AMS-Regular.woff2", "KaTeX_Caligraphic-Bold.woff2",
    "KaTeX_Caligraphic-Regular.woff2", "KaTeX_Fraktur-Bold.woff2",
    "KaTeX_Fraktur-Regular.woff2", "KaTeX_Main-Bold.woff2",
    "KaTeX_Main-BoldItalic.woff2", "KaTeX_Main-Italic.woff2",
    "KaTeX_Main-Regular.woff2", "KaTeX_Math-BoldItalic.woff2",
    "KaTeX_Math-Italic.woff2", "KaTeX_SansSerif-Bold.woff2",
    "KaTeX_SansSerif-Italic.woff2", "KaTeX_SansSerif-Regular.woff2",
    "KaTeX_Script-Regular.woff2", "KaTeX_Size1-Regular.woff2",
    "KaTeX_Size2-Regular.woff2", "KaTeX_Size3-Regular.woff2",
    "KaTeX_Size4-Regular.woff2", "KaTeX_Typewriter-Regular.woff2",
]


def _sources() -> dict[str, str]:
    """Map of vendor-relative path -> upstream URL. Single source of truth for what we ship."""
    srcs: dict[str, str] = {}
    katex_base = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist"
    srcs["katex/katex.min.js"] = f"{katex_base}/katex.min.js"
    srcs["katex/katex.min.css"] = f"{katex_base}/katex.min.css"
    srcs["katex/auto-render.min.js"] = f"{katex_base}/contrib/auto-render.min.js"
    for font in KATEX_FONTS:
        srcs[f"katex/fonts/{font}"] = f"{katex_base}/fonts/{font}"
    srcs["mermaid/mermaid.min.js"] = (
        f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"
    )
    hljs_base = f"https://cdn.jsdelivr.net/npm/@highlightjs/cdn-assets@{HLJS_VERSION}"
    srcs["hljs/highlight.min.js"] = f"{hljs_base}/highlight.min.js"
    srcs["hljs/github.min.css"] = f"{hljs_base}/styles/github.min.css"
    srcs["hljs/github-dark.min.css"] = f"{hljs_base}/styles/github-dark.min.css"
    for lang in HLJS_LANGS:
        srcs[f"hljs/languages/{lang}.min.js"] = f"{hljs_base}/languages/{lang}.min.js"
    return srcs


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest() -> dict[str, str]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _save_manifest(manifest: dict[str, str]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def verify(strict: bool = True) -> int:
    manifest = _load_manifest()
    if not manifest:
        print("ERROR: manifest.json missing — run --update first.", file=sys.stderr)
        return 2
    sources = _sources()
    missing_from_manifest = set(sources) - set(manifest)
    unknown_in_manifest = set(manifest) - set(sources)
    if missing_from_manifest:
        print(
            f"ERROR: manifest is missing entries: {sorted(missing_from_manifest)}",
            file=sys.stderr,
        )
        return 2
    if unknown_in_manifest:
        print(f"ERROR: manifest has stale entries: {sorted(unknown_in_manifest)}", file=sys.stderr)
        return 2
    bad = []
    for rel in sorted(sources):
        p = VENDOR / rel
        if not p.exists():
            bad.append((rel, "missing"))
            continue
        got = _sha256(p.read_bytes())
        want = manifest[rel]
        if got != want:
            bad.append((rel, f"sha256 mismatch\n    expected {want}\n    got      {got}"))
    if bad:
        for rel, why in bad:
            print(f"FAIL {rel}: {why}", file=sys.stderr)
        print(f"\n{len(bad)} file(s) failed verification.", file=sys.stderr)
        return 1
    print(f"OK  verified {len(sources)} vendor files against manifest.")
    return 0


def update() -> int:
    """Fetch all vendor files fresh and write a new manifest."""
    sources = _sources()
    manifest: dict[str, str] = {}
    for rel, url in sorted(sources.items()):
        print(f"fetch {rel}")
        data = _download(url)
        _write(VENDOR / rel, data)
        manifest[rel] = _sha256(data)
    _save_manifest(manifest)
    _report_sizes()
    print(f"\nWrote manifest with {len(manifest)} entries to {MANIFEST.relative_to(ROOT)}")
    return 0


def smart() -> int:
    """Fetch any missing files, verify the rest, update manifest for fetched items."""
    sources = _sources()
    manifest = _load_manifest()
    changed = False
    for rel, url in sorted(sources.items()):
        p = VENDOR / rel
        if not p.exists():
            print(f"fetch {rel}")
            data = _download(url)
            _write(p, data)
            manifest[rel] = _sha256(data)
            changed = True
    if changed:
        _save_manifest(manifest)
    return verify()


def _report_sizes() -> None:
    print("\n[sizes]")
    total = 0
    for sub in ("katex", "mermaid", "hljs"):
        d = VENDOR / sub
        if not d.exists():
            continue
        size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
        total += size
        print(f"  {sub:<10} {size / 1024:>8.1f} KiB")
    print(f"  {'total':<10} {total / 1024:>8.1f} KiB")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    grp = p.add_mutually_exclusive_group()
    grp.add_argument(
        "--verify", action="store_true",
        help="Verify vendor files against manifest (CI mode)",
    )
    grp.add_argument(
        "--update", action="store_true",
        help="Fetch fresh and overwrite manifest",
    )
    args = p.parse_args(argv)
    if args.verify:
        return verify()
    if args.update:
        return update()
    return smart()


if __name__ == "__main__":
    sys.exit(main())
