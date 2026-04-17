"""Tests for the diagnostics module."""

from __future__ import annotations

from pathlib import Path

from mdvw.diagnostics import check_document


def test_valid_document():
    issues = check_document("# Hello\n\nWorld")
    assert issues == []


def test_invalid_frontmatter():
    source = "---\ninvalid: [unclosed\n---\n\n# Hello"
    issues = check_document(source)
    assert any(i["severity"] == "error" and "YAML" in i["message"] for i in issues)


def test_broken_image(tmp_path):
    source = "![alt](nonexistent.png)"
    issues = check_document(source, doc_dir=str(tmp_path))
    assert any(i["severity"] == "warning" and "Broken image" in i["message"] for i in issues)


def test_broken_link(tmp_path):
    source = "[text](missing.md)"
    issues = check_document(source, doc_dir=str(tmp_path))
    assert any(i["severity"] == "warning" and "Broken link" in i["message"] for i in issues)


def test_existing_image(tmp_path):
    (tmp_path / "exists.png").write_bytes(b"fake")
    source = "![alt](exists.png)"
    issues = check_document(source, doc_dir=str(tmp_path))
    assert not any("Broken" in i["message"] for i in issues)


def test_remote_image_info():
    source = "![alt](https://example.com/img.png)"
    issues = check_document(source)
    assert any(i["severity"] == "info" and "Remote" in i["message"] for i in issues)


def test_blocked_scheme():
    source = "[click](javascript:alert(1))"
    issues = check_document(source)
    assert any(i["severity"] == "warning" and "Blocked" in i["message"] for i in issues)


def test_anchor_links_ignored():
    source = "[section](#heading)"
    issues = check_document(source)
    assert issues == []


def test_line_numbers():
    source = "line one\n![img](broken.png)\nline three"
    issues = check_document(source, doc_dir="/nonexistent")
    assert issues[0]["line"] == 2


def test_absolute_path_is_not_probed(tmp_path, monkeypatch):
    """A crafted href to an absolute path must not touch the filesystem.

    The diagnostics run automatically on every edit; without this guard
    a hostile doc could use broken/non-broken reports to detect whether
    arbitrary absolute or UNC paths exist on the user's machine.
    """
    calls: list[Path] = []
    orig_exists = Path.exists

    def spy_exists(self, *a, **kw):
        calls.append(Path(self))
        return orig_exists(self, *a, **kw)

    monkeypatch.setattr(Path, "exists", spy_exists)

    source = "[a](/etc/passwd)\n[b](C:/Windows/System32/drivers/etc/hosts)\n"
    issues = check_document(source, doc_dir=str(tmp_path))
    # No Broken warnings for any of the out-of-tree paths.
    assert not any("Broken" in i["message"] for i in issues)
    # And no filesystem probe ever reached those paths.
    probed = [str(p) for p in calls]
    assert not any(p.startswith(("/etc", "C:")) for p in probed)


def test_unc_path_is_not_probed(tmp_path, monkeypatch):
    """UNC-style hrefs (``\\\\server\\share``) must never be probed — a
    slow/unreachable server would otherwise stall diagnostics."""
    calls: list[Path] = []
    orig_exists = Path.exists

    def spy_exists(self, *a, **kw):
        calls.append(Path(self))
        return orig_exists(self, *a, **kw)

    monkeypatch.setattr(Path, "exists", spy_exists)

    source = "[x](//evil.example/share/file)\n"
    issues = check_document(source, doc_dir=str(tmp_path))
    assert not any("Broken" in i["message"] for i in issues)
    assert not any("evil.example" in str(p) for p in calls)


def test_parent_traversal_stays_inside_doc_dir(tmp_path, monkeypatch):
    """``../`` references resolving outside doc_dir must not be probed."""
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    secret = secret_dir / "key.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")

    doc_dir = tmp_path / "notes"
    doc_dir.mkdir()

    source = "[leak](../secrets/key.txt)\n"
    issues = check_document(source, doc_dir=str(doc_dir))
    # The file exists on disk, but it's outside doc_dir → no Broken
    # warning AND no positive warning either. We simply don't probe it.
    assert not any("Broken" in i["message"] for i in issues)


def test_relative_path_still_validated(tmp_path):
    """In-tree relative paths keep working exactly as before."""
    (tmp_path / "exists.md").write_text("hi", encoding="utf-8")
    source = "[ok](exists.md)\n[bad](missing.md)\n"
    issues = check_document(source, doc_dir=str(tmp_path))
    messages = [i["message"] for i in issues]
    assert not any("exists.md" in m and "Broken" in m for m in messages)
    assert any("Broken" in m and "missing.md" in m for m in messages)


def test_percent_encoded_relative_path_resolved(tmp_path):
    """Spaces in hrefs are percent-encoded; the diagnostic must decode
    before hitting the filesystem or every such link looks broken."""
    (tmp_path / "my file.md").write_text("hi", encoding="utf-8")
    source = "[ok](my%20file.md)\n"
    issues = check_document(source, doc_dir=str(tmp_path))
    assert not any("Broken" in i["message"] for i in issues)


def test_percent_encoded_absolute_paths_not_probed(tmp_path, monkeypatch):
    """Percent-encoded absolute / drive / UNC hrefs must not reach the
    filesystem. If the safety check runs before decoding, values like
    ``%2Fetc%2Fpasswd``, ``C%3A%5CWindows``, or ``%5C%5Cserver%5Cshare``
    look like bare filenames and sneak past the precheck, letting a
    hostile doc trigger arbitrary local/UNC path resolution during
    automatic diagnostics."""
    calls: list[Path] = []
    orig_resolve = Path.resolve
    orig_exists = Path.exists

    def spy_resolve(self, *a, **kw):
        calls.append(Path(self))
        return orig_resolve(self, *a, **kw)

    def spy_exists(self, *a, **kw):
        calls.append(Path(self))
        return orig_exists(self, *a, **kw)

    monkeypatch.setattr(Path, "resolve", spy_resolve)
    monkeypatch.setattr(Path, "exists", spy_exists)

    source = (
        "[a](%2Fetc%2Fpasswd)\n"
        "[b](C%3A%5CWindows%5CSystem32%5Cdrivers%5Cetc%5Chosts)\n"
        "[c](%5C%5Cevil.example%5Cshare%5Cfile)\n"
        "[d](%2F%2Fevil.example%2Fshare%2Ffile)\n"
    )
    issues = check_document(source, doc_dir=str(tmp_path))
    assert not any("Broken" in i["message"] for i in issues)

    probed = [str(p) for p in calls]
    # Only doc_dir itself may be resolved; no probe of any of the decoded
    # hostile targets is allowed.
    assert not any("etc" in p and "passwd" in p for p in probed)
    assert not any("Windows" in p for p in probed)
    assert not any("evil.example" in p for p in probed)
