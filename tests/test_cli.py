from mdvw.cli import build_parser


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.file is None
    assert args.edit is False
    assert args.no_tray is False


def test_parser_file_and_edit():
    args = build_parser().parse_args(["notes.md", "--edit"])
    assert str(args.file) == "notes.md"
    assert args.edit is True
