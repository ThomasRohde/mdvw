from mdvw.render import render_frontmatter_card, render_markdown


def test_basic_heading():
    assert "<h1>Hello</h1>" in render_markdown("# Hello")


def test_table():
    html = render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in html and "<td>1</td>" in html


def test_highlight():
    html = render_markdown("this is ==important==")
    assert "<mark>important</mark>" in html


def test_underline():
    html = render_markdown("tap ++here++")
    assert "<u>here</u>" in html


def test_color():
    html = render_markdown("{color:orange}hot{/color}")
    assert 'class="mdvw-color"' in html
    assert 'data-color="orange"' in html
    assert "hot" in html


def test_color_nested_formatting():
    html = render_markdown("{color:cyan}**bold** word{/color}")
    assert "<strong>bold</strong>" in html
    assert 'data-color="cyan"' in html


def test_inline_math():
    html = render_markdown("Euler: $e^{i\\pi}+1=0$")
    assert 'class="math math-inline"' in html


def test_block_math():
    html = render_markdown("$$\nx = 1\n$$")
    assert 'class="math math-display"' in html


def test_mermaid_fence():
    html = render_markdown("```mermaid\ngraph LR\nA-->B\n```")
    assert '<pre class="mermaid">' in html


def test_code_fence_language():
    html = render_markdown("```python\nprint('hi')\n```")
    assert 'class="language-python"' in html


def test_task_list():
    html = render_markdown("- [x] done\n- [ ] todo\n")
    assert 'type="checkbox"' in html and "checked" in html


def test_wiki_link_renders_internal_anchor():
    html = render_markdown("[[Note#Heading|Read this]]")
    assert 'class="mdvw-wikilink"' in html
    assert 'data-wikilink="Note#Heading|Read this"' in html
    assert 'data-wikilink-target="Note"' in html
    assert 'data-wikilink-heading="Heading"' in html
    assert ">Read this</a>" in html


def test_wiki_link_not_rendered_inside_code():
    html = render_markdown("`[[Note]]`")
    assert 'class="mdvw-wikilink"' not in html
    assert "[[Note]]" in html


def test_strikethrough():
    html = render_markdown("~~gone~~")
    assert "<s>gone</s>" in html or "<del>gone</del>" in html


def test_xss_sanitized():
    html = render_markdown('<script>alert(1)</script>Hello')
    assert "<script>" not in html
    assert "Hello" in html


def test_frontmatter_fence_hidden_from_body():
    html = render_markdown("---\ntitle: Hi\n---\n# Body\n")
    # Plugin should mark fence hidden so no stray <hr> or raw key text.
    assert "<hr" not in html
    assert "title:" not in html
    assert "<h1>Body</h1>" in html


def test_frontmatter_card_basic():
    html = render_frontmatter_card("title: Hi\ntags: [a, b]", None)
    assert 'class="md-frontmatter"' in html
    assert "<pre>" in html
    assert "title: Hi" in html
    assert "tags: [a, b]" in html


def test_frontmatter_card_error():
    html = render_frontmatter_card(None, "bad yaml: x")
    assert "md-frontmatter--error" in html
    assert "bad yaml: x" in html


def test_frontmatter_card_escapes_html_in_values():
    html = render_frontmatter_card("evil: <script>alert(1)</script>", None)
    assert "<script>" not in html
    assert "alert(1)" in html


def test_frontmatter_card_empty_returns_empty_string():
    assert render_frontmatter_card(None, None) == ""
