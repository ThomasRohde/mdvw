"""Cut a release with a single commit that bumps the version, renames the
CHANGELOG's `[Unreleased]` section, and applies the `vX.Y.Z` tag.

    python scripts/release.py 0.2.0        # cut 0.2.0 (requires clean tree)
    python scripts/release.py 0.2.0 --dry  # show what would change

Then push with:

    git push origin main v0.2.0

After the release lands, open a follow-up dev cycle:

    python scripts/release.py --post-release 0.3.0.dev0

which bumps `__version__` to `0.3.0.dev0` and re-opens an empty
`[Unreleased]` section.

The pattern: release commit and its tag point at the same SHA, so the
PyPI/GitHub artifact's source corresponds exactly to the tag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "mdvw" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"

VERSION_RE = re.compile(r'__version__ = "([^"]+)"')
UNRELEASED_HEADER = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)


def _current_version() -> str:
    m = VERSION_RE.search(INIT.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("Could not find __version__ in src/mdvw/__init__.py")
    return m.group(1)


def _set_version(new: str) -> None:
    text = INIT.read_text(encoding="utf-8")
    text = VERSION_RE.sub(f'__version__ = "{new}"', text, count=1)
    INIT.write_text(text, encoding="utf-8")


def _rename_unreleased(version: str, today: str) -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if not UNRELEASED_HEADER.search(text):
        raise SystemExit("No `## [Unreleased]` section in CHANGELOG.md")
    new = UNRELEASED_HEADER.sub(f"## [{version}] — {today}", text, count=1)
    CHANGELOG.write_text(new, encoding="utf-8")


def _add_unreleased() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    if UNRELEASED_HEADER.search(text):
        return  # already present
    # Insert after the first heading (`# Changelog`).
    parts = text.split("\n", 2)
    if len(parts) < 3:
        raise SystemExit("CHANGELOG.md has unexpected layout")
    head = parts[0] + "\n" + parts[1] + "\n"
    rest = parts[2]
    new = head + "\n## [Unreleased]\n\n" + rest
    CHANGELOG.write_text(new, encoding="utf-8")


def _git(*args: str, check: bool = True, capture: bool = False) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=check, capture_output=capture, text=True,
    )
    return result.stdout.strip() if capture else ""


def _require_clean_tree() -> None:
    dirty = _git("status", "--porcelain", capture=True)
    if dirty:
        raise SystemExit("Working tree not clean:\n" + dirty)


def cut(version: str, dry: bool) -> int:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\.[a-z0-9]+)?", version):
        raise SystemExit(f"Refusing non-semver version: {version!r}")
    current = _current_version()
    if not current.endswith(".dev0") and not dry:
        raise SystemExit(
            f"Current version is {current!r}; expected an in-progress "
            f"`.devN` suffix. Run --post-release first or amend manually."
        )
    today = dt.date.today().isoformat()
    if dry:
        print(f"would bump {current} -> {version}")
        print(f"would rename `## [Unreleased]` -> `## [{version}] — {today}`")
        print(f"would commit + tag v{version}")
        return 0
    _require_clean_tree()
    _set_version(version)
    _rename_unreleased(version, today)
    _git("add", str(INIT.relative_to(ROOT)), str(CHANGELOG.relative_to(ROOT)))
    _git("commit", "-m", f"Release {version}")
    _git("tag", "-a", f"v{version}", "-m", f"mdvw {version}")
    print(f"cut v{version}. Push with:")
    print(f"  git push origin main v{version}")
    return 0


def post_release(dev_version: str, dry: bool) -> int:
    if not re.fullmatch(r"\d+\.\d+\.\d+\.dev\d+", dev_version):
        raise SystemExit(
            f"Expected a dev version like `0.3.0.dev0`, got {dev_version!r}"
        )
    if dry:
        print(f"would bump to {dev_version} and re-open `## [Unreleased]`")
        return 0
    _require_clean_tree()
    _set_version(dev_version)
    _add_unreleased()
    _git("add", str(INIT.relative_to(ROOT)), str(CHANGELOG.relative_to(ROOT)))
    _git("commit", "-m", f"Open {dev_version} dev cycle")
    print(f"bumped to {dev_version}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "version",
        help="Release version (e.g. 0.2.0) or next dev version with --post-release",
    )
    p.add_argument("--dry", action="store_true", help="Show changes without writing")
    p.add_argument(
        "--post-release", action="store_true",
        help="After a release lands: bump to the given .devN and re-open [Unreleased]",
    )
    args = p.parse_args(argv)
    if args.post_release:
        return post_release(args.version, args.dry)
    return cut(args.version, args.dry)


if __name__ == "__main__":
    sys.exit(main())
