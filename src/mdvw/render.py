from __future__ import annotations

import html as _html
import re
from pathlib import Path

import nh3
from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .frontmatter import split_frontmatter
from .links import build_link_index, parse_wiki_inner, resolve_wiki_link
from .note_excerpt import heading_excerpt


def _mark_rule(state: StateInline, silent: bool) -> bool:
    # ==highlight==
    return _pair_rule(state, silent, "==", "mdvw_mark_open", "mdvw_mark_close")


def _ins_rule(state: StateInline, silent: bool) -> bool:
    # ++underline++
    return _pair_rule(state, silent, "++", "mdvw_ins_open", "mdvw_ins_close")


def _pair_rule(state: StateInline, silent: bool, delim: str, open_tag: str, close_tag: str) -> bool:
    src = state.src
    pos = state.pos
    n = len(delim)
    if src[pos : pos + n] != delim:
        return False
    end = src.find(delim, pos + n)
    if end == -1 or end == pos + n:
        return False
    # no whitespace immediately inside delimiters
    inner = src[pos + n : end]
    if inner[0].isspace() or inner[-1].isspace() or "\n" in inner:
        return False
    if not silent:
        state.push(open_tag, "", 1)
        text_tok = state.push("text", "", 0)
        text_tok.content = inner
        state.push(close_tag, "", -1)
    state.pos = end + n
    return True


_COLOR_RE = re.compile(r"\{color:([a-zA-Z]+|#[0-9a-fA-F]{3,8})\}")
_TRANSCLUDE_LINE_RE = re.compile(r"^\s{0,3}!\[\[([^\]\n]+?)\]\]\s*$")
_TRANSCLUDE_FENCE_RE = re.compile(r"^\s{0,3}((`{3,})|(~{3,})).*$")
_MAX_TRANSCLUSION_DEPTH = 4


def _color_open_rule(state: StateInline, silent: bool) -> bool:
    src = state.src
    pos = state.pos
    if src[pos] != "{":
        return False
    m = _COLOR_RE.match(src, pos)
    if not m:
        return False
    close = src.find("{/color}", m.end())
    if close == -1:
        return False
    if not silent:
        tok = state.push("mdvw_color_open", "", 1)
        tok.attrs = {"data-color": m.group(1)}
        # parse inner via nested inline tokens
        inner_end = close
        saved_pos = state.pos
        saved_pos_max = state.posMax
        state.pos = m.end()
        state.posMax = inner_end
        state.md.inline.tokenize(state)
        state.pos = saved_pos
        state.posMax = saved_pos_max
        state.push("mdvw_color_close", "", -1)
    state.pos = close + len("{/color}")
    return True


def _wiki_link_rule(state: StateInline, silent: bool) -> bool:
    src = state.src
    pos = state.pos
    if src[pos : pos + 2] != "[[":
        return False
    if pos > 0 and src[pos - 1] == "!":
        return False
    end = src.find("]]", pos + 2, state.posMax)
    if end == -1:
        return False
    inner = src[pos + 2 : end].strip()
    if not inner or "\n" in inner:
        return False
    parsed = parse_wiki_inner(inner)
    if parsed is None:
        return False
    target, heading, _alias, display = parsed
    if not silent:
        tok = state.push("mdvw_wikilink_open", "a", 1)
        attrs = {
            "href": "#",
            "class": "mdvw-wikilink",
            "data-wikilink": inner,
        }
        if target:
            attrs["data-wikilink-target"] = target
        if heading:
            attrs["data-wikilink-heading"] = heading
        tok.attrs = attrs
        text_tok = state.push("text", "", 0)
        text_tok.content = display
        state.push("mdvw_wikilink_close", "a", -1)
    state.pos = end + 2
    return True


def _render_mark_open(self, tokens, idx, options, env):
    return "<mark>"


def _render_mark_close(self, tokens, idx, options, env):
    return "</mark>"


def _render_ins_open(self, tokens, idx, options, env):
    return "<u>"


def _render_ins_close(self, tokens, idx, options, env):
    return "</u>"


def _render_color_open(self, tokens, idx, options, env):
    color = tokens[idx].attrs.get("data-color", "")
    safe = re.sub(r"[^a-zA-Z0-9#]", "", str(color))[:16]
    return f'<span class="mdvw-color" data-color="{safe}">'


def _render_color_close(self, tokens, idx, options, env):
    return "</span>"


def _render_wikilink_open(self, tokens, idx, options, env):
    attrs = tokens[idx].attrs or {}
    attr_text = []
    for name in ("href", "class", "data-wikilink", "data-wikilink-target", "data-wikilink-heading"):
        value = attrs.get(name)
        if value is None:
            continue
        safe = _html.escape(str(value), quote=True)
        attr_text.append(f'{name}="{safe}"')
    return f'<a {" ".join(attr_text)}>'


def _render_wikilink_close(self, tokens, idx, options, env):
    return "</a>"


def _render_math_inline(self, tokens, idx, options, env):
    content = tokens[idx].content
    return f'<span class="math math-inline">{nh3.clean_text(content)}</span>'


def _render_math_block(self, tokens, idx, options, env):
    content = tokens[idx].content
    return f'<div class="math math-display">{nh3.clean_text(content)}</div>\n'


def _render_fence(self, tokens, idx, options, env):
    token = tokens[idx]
    info = (token.info or "").strip()
    lang = info.split(None, 1)[0] if info else ""
    content = nh3.clean_text(token.content)
    if lang == "mermaid":
        return f'<pre class="mermaid">{content}</pre>\n'
    if lang:
        safe_lang = re.sub(r"[^a-zA-Z0-9_+-]", "", lang)[:32]
        return (
            f'<pre class="code-block"><code class="language-{safe_lang}">'
            f"{content}</code></pre>\n"
        )
    return f'<pre class="code-block"><code>{content}</code></pre>\n'


_SANITIZE_TAGS = {
    *nh3.ALLOWED_TAGS,
    "mark", "u", "span", "div", "pre", "code", "table", "thead", "tbody",
    "tr", "th", "td", "sup", "sub", "img", "input", "br", "hr", "details", "s", "del",
    "summary", "dl", "dt", "dd", "section", "h1", "h2", "h3", "h4", "h5", "h6",
}

# NOTE: `id` is deliberately NOT allowed on user content. Letting users pick
# DOM ids lets a hostile .md shadow bootstrap elements like
# `<script id="md-source">` and corrupt saves. IDs on *generated* elements
# (e.g. headings via anchor plugin) are added after sanitization.
_SANITIZE_ATTRS: dict[str, set[str]] = {
    "*": {"class", "data-color"},
    "a": {
        "href", "title", "target",
        "data-wikilink", "data-wikilink-target", "data-wikilink-heading",
    },
    "img": {"src", "alt", "title", "width", "height"},
    "input": {"type", "checked", "disabled"},
    "code": {"class"},
    "pre": {"class"},
    "span": {"class", "data-color"},
    "div": {"class"},
    "th": {"align", "colspan", "rowspan"},
    "td": {"align", "colspan", "rowspan"},
}


def _build_md() -> MarkdownIt:
    md = (
        MarkdownIt("gfm-like", {"html": True, "linkify": True, "typographer": True})
        .enable("table")
        .enable("strikethrough")
        .use(footnote_plugin)
        .use(deflist_plugin)
        .use(tasklists_plugin, enabled=True, label=True)
        .use(dollarmath_plugin, allow_labels=True, double_inline=True)
        .use(front_matter_plugin)
    )

    md.inline.ruler.before("emphasis", "mdvw_mark", _mark_rule)
    md.inline.ruler.before("emphasis", "mdvw_ins", _ins_rule)
    md.inline.ruler.before("emphasis", "mdvw_color", _color_open_rule)
    md.inline.ruler.before("link", "mdvw_wikilink", _wiki_link_rule)

    md.add_render_rule("mdvw_mark_open", _render_mark_open)
    md.add_render_rule("mdvw_mark_close", _render_mark_close)
    md.add_render_rule("mdvw_ins_open", _render_ins_open)
    md.add_render_rule("mdvw_ins_close", _render_ins_close)
    md.add_render_rule("mdvw_color_open", _render_color_open)
    md.add_render_rule("mdvw_color_close", _render_color_close)
    md.add_render_rule("mdvw_wikilink_open", _render_wikilink_open)
    md.add_render_rule("mdvw_wikilink_close", _render_wikilink_close)
    md.add_render_rule("math_inline", _render_math_inline)
    md.add_render_rule("math_block", _render_math_block)
    md.add_render_rule("math_inline_double", _render_math_block)
    md.add_render_rule("fence", _render_fence)

    return md


_MD = _build_md()


def _is_safe_img_src(value: str) -> bool:
    """Image `src` is auto-fetched by the WebView, so anything that could
    reach out over the network, a UNC share, or an arbitrary local drive
    must be rejected. Only two shapes are accepted:

    1. `data:` URIs (inline bytes — cannot leak)
    2. Pure relative paths with no scheme, no authority, no leading
       separator. They resolve against the document's file URL, which the
       app rewrites to the Markdown file's own directory.
    """
    if not isinstance(value, str):
        return False
    # Strip ASCII whitespace and C0 control chars from both ends — some
    # parsers trim these and hidden-prefix tricks have bypassed filters
    # before (e.g., "\u0001//attacker/pixel").
    stripped = value.strip().lstrip("\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\x0c\r\x0e\x0f ")
    if not stripped:
        return False
    low = stripped.lower()
    if low.startswith("data:"):
        return True
    # Reject schemes (http/https/file/ftp/anything:).
    # A scheme is letters+digits then ':' before any '/'.
    first_slash = stripped.find("/")
    first_colon = stripped.find(":")
    if first_colon != -1 and (first_slash == -1 or first_colon < first_slash):
        return False
    # Reject authority-shaped paths: '//host/…' (protocol-relative) and
    # '\\\\server\\share' (Windows UNC).
    if stripped.startswith(("//", "\\\\")):
        return False
    # Reject absolute local paths that escape the document directory:
    # leading '/' or '\\'. Windows drive-letters ('C:\\…') were rejected
    # above by the scheme check.
    return not stripped.startswith(("/", "\\"))


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    """Per-attribute policy applied on top of the tag/attribute allowlist.

    `<img src>` is locked down: only `data:` and strictly-relative paths
    pass. Everything else (http(s), file, protocol-relative `//`, UNC
    `\\\\server\\share`, absolute paths) is dropped to preserve the
    offline posture and keep a hostile Markdown file from leaking
    document-open telemetry.
    """
    if tag == "img" and attr == "src" and not _is_safe_img_src(value):
        return None
    return value


_RELATIVE_HREF_RE = re.compile(
    r'(href|src)="([^"#][^":]*?)"'
)


def _rewrite_relative_urls(html: str, doc_base: str) -> str:
    """Rewrite user-markdown relative `href`/`src` to absolute URLs rooted
    at the markdown document's directory.

    Only touches strictly-relative values — anything with a scheme
    (http(s)/data/mailto/etc.), a fragment prefix `#`, or an authority
    marker `//` is left alone so the sanitizer's scheme rules still apply.
    For `src`, the img filter has already dropped the unsafe ones.
    """
    base = doc_base if doc_base.endswith("/") else doc_base + "/"

    def _sub(m: re.Match[str]) -> str:
        attr = m.group(1)
        val = m.group(2)
        # Guard-rails: relative means no scheme, no '//' authority, no leading '/'.
        low = val.lower()
        if (
            val.startswith(("#", "/", "\\"))
            or val.startswith("//")
            or low.startswith(("http:", "https:", "data:", "mailto:", "file:"))
            or ":" in val.split("/", 1)[0]
        ):
            return m.group(0)
        return f'{attr}="{base}{val}"'

    return _RELATIVE_HREF_RE.sub(_sub, html)


def _expand_transclusions(
    text: str,
    *,
    current_path: Path | None,
    browse_root: Path | None,
    index,
    stack: tuple[Path, ...],
    depth: int,
) -> tuple[str, list[tuple[str, str]]]:
    if (
        "![[" not in text
        or current_path is None
        or browse_root is None
        or depth >= _MAX_TRANSCLUSION_DEPTH
    ):
        return text, []

    out: list[str] = []
    replacements: list[tuple[str, str]] = []
    fence_char = ""
    fence_len = 0
    token_id = 0

    for line in text.splitlines(keepends=True):
        line_body = line.rstrip("\r\n")
        newline = line[len(line_body) :]
        stripped = line_body.lstrip()
        if fence_char:
            out.append(line)
            if (
                stripped.startswith(fence_char * fence_len)
                and not stripped[fence_len:].strip(fence_char).strip()
            ):
                fence_char = ""
                fence_len = 0
            continue

        fence_match = _TRANSCLUDE_FENCE_RE.match(line_body)
        if fence_match:
            fence = fence_match.group(1)
            fence_char = fence[0]
            fence_len = len(fence)
            out.append(line)
            continue

        match = _TRANSCLUDE_LINE_RE.match(line_body)
        if not match:
            out.append(line)
            continue

        fragment = _render_transclusion_fragment(
            match.group(1).strip(),
            browse_root=browse_root,
            current_path=current_path,
            depth=depth,
            index=index,
            stack=stack,
        )
        if fragment is None:
            out.append(line)
            continue

        token = f"__MDVW_TRANSCLUSION_{depth}_{token_id}__"
        token_id += 1
        slot = f'<div class="mdvw-transclusion-slot">{token}</div>'
        out.append(slot + newline)
        replacements.append((slot, fragment))

    return "".join(out), replacements


def _render_transclusion_fragment(
    raw_target: str,
    *,
    browse_root: Path,
    current_path: Path,
    depth: int,
    index,
    stack: tuple[Path, ...],
) -> str | None:
    resolved = resolve_wiki_link(raw_target, current_path, index)
    target = resolved.target_path
    if resolved.status != "ok" or target is None:
        return None

    try:
        target_key = target.resolve()
        source = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    if target_key in stack:
        return None

    _meta, body = split_frontmatter(source)
    excerpt = heading_excerpt(body, resolved.heading) if resolved.heading else body.strip()
    excerpt = excerpt.strip() or f"# {target.stem}\n"
    doc_base = target.parent.resolve().as_uri() + "/"
    html = render_markdown(
        excerpt,
        doc_base=doc_base,
        current_path=target,
        browse_root=browse_root,
        _transclude_depth=depth + 1,
        _transclude_index=index,
        _transclude_stack=(*stack, target_key),
    )
    return f'<section class="mdvw-transclusion">{html}</section>'


def render_frontmatter_card(raw_yaml: str | None, error: str | None) -> str:
    """Render a sanitized HTML card for YAML frontmatter.

    *raw_yaml* is the verbatim text between the fences (no ``---``).
    Pass ``(None, None)`` for "no frontmatter" — returns ``""``.
    """
    if error:
        body = (
            '<p class="md-frontmatter-title">Frontmatter error</p>'
            f"<pre>{nh3.clean_text(error)}</pre>"
        )
        html = f'<section class="md-frontmatter md-frontmatter--error">{body}</section>'
    elif raw_yaml is not None:
        escaped = nh3.clean_text(raw_yaml.strip())
        html = f'<section class="md-frontmatter"><pre>{escaped}</pre></section>'
    else:
        return ""
    return nh3.clean(
        html,
        tags=_SANITIZE_TAGS,
        attributes=_SANITIZE_ATTRS,
        attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto", "data"},
    )


def render_markdown(
    text: str,
    doc_base: str | None = None,
    current_path: Path | None = None,
    browse_root: Path | None = None,
    _transclude_depth: int = 0,
    _transclude_index=None,
    _transclude_stack: tuple[Path, ...] = (),
) -> str:
    """Render markdown to sanitized HTML.

    `doc_base` is an optional absolute URL (with trailing slash) that
    user-markdown relative `href`/`src` values are resolved against.
    """
    replacements: list[tuple[str, str]] = []
    if current_path is not None and browse_root is not None and "![[" in text:
        index = _transclude_index or build_link_index(browse_root)
        text, replacements = _expand_transclusions(
            text,
            browse_root=browse_root,
            current_path=current_path,
            depth=_transclude_depth,
            index=index,
            stack=_transclude_stack,
        )
    html = _MD.render(text)
    clean = nh3.clean(
        html,
        tags=_SANITIZE_TAGS,
        attributes=_SANITIZE_ATTRS,
        attribute_filter=_attribute_filter,
        # `file:` deliberately excluded: a Markdown doc could otherwise link
        # to a local .exe/.lnk and drive ShellExecute via the click handler.
        url_schemes={"http", "https", "mailto", "data"},
    )
    if doc_base:
        clean = _rewrite_relative_urls(clean, doc_base)
    for slot, fragment in replacements:
        clean = clean.replace(slot, fragment)
    return clean
