from mdvw.frontmatter import parse_frontmatter, split_frontmatter


def test_no_frontmatter_returns_none():
    meta, body, err = parse_frontmatter("# Hello\n\nbody")
    assert meta is None
    assert body == "# Hello\n\nbody"
    assert err is None


def test_basic_mapping():
    src = "---\ntitle: Hi\ntags: [a, b]\n---\n# Body\n"
    meta, body, err = parse_frontmatter(src)
    assert err is None
    assert meta == {"title": "Hi", "tags": ["a", "b"]}
    assert body == "# Body\n"


def test_dotted_close_terminator():
    src = "---\nk: v\n...\nbody\n"
    meta, body, err = parse_frontmatter(src)
    assert err is None
    assert meta == {"k": "v"}
    assert body == "body\n"


def test_missing_close_yields_no_frontmatter():
    src = "---\ntitle: Hi\nstill unclosed"
    meta, body, err = parse_frontmatter(src)
    assert meta is None
    assert err is None
    assert body == src


def test_empty_frontmatter_body():
    src = "---\n---\nhello\n"
    meta, body, _err = parse_frontmatter(src)
    assert meta == {}
    assert body == "hello\n"


def test_crlf_line_endings():
    src = "---\r\ntitle: Hi\r\n---\r\nbody\r\n"
    meta, body, err = parse_frontmatter(src)
    assert err is None
    assert meta == {"title": "Hi"}
    assert body == "body\r\n"


def test_mid_document_hr_is_not_frontmatter():
    src = "# Heading\n\n---\n\nmore text\n"
    meta, body, err = parse_frontmatter(src)
    assert meta is None
    assert err is None
    assert body == src


def test_invalid_yaml_returns_error():
    src = "---\ntitle: [unclosed\n---\n\nbody\n"
    meta, body, err = parse_frontmatter(src)
    assert meta is None
    assert err is not None
    assert body == "\nbody\n"


def test_non_mapping_returns_error():
    src = "---\n- one\n- two\n---\nbody\n"
    meta, body, err = parse_frontmatter(src)
    assert meta is None
    assert err is not None and "mapping" in err
    assert body == "body\n"


def test_fence_must_be_exact():
    # '----' is not a valid opening fence.
    src = "----\ntitle: Hi\n----\nbody\n"
    meta, body, err = parse_frontmatter(src)
    assert meta is None
    assert err is None
    assert body == src


def test_split_frontmatter_no_newline():
    assert split_frontmatter("---") == (None, "---")


def test_yaml_safe_load_does_not_execute_tags():
    # safe_load rejects !!python/object tags; we should surface as error,
    # not raise.
    src = "---\n!!python/object/apply:os.system ['echo pwn']\n---\n"
    meta, _body, err = parse_frontmatter(src)
    assert meta is None
    assert err is not None
