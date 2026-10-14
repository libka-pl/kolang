"""H.6 + H.7: L() comment parser and serializer."""
import pytest

from kolang import _parse_L_comment as _parse_l_comment, _format_L_comment


@pytest.mark.parametrize('comment, expected', [
    ("L(30100, 'Movies')", (None, 30100, 'Movies', '')),
    (" L(30100, 'Movies') ", (None, 30100, 'Movies', '')),
    ("L[label](30100, 'Movies')", ('label', 30100, 'Movies', '')),
    ("L[help](30200, 'Help text')", ('help', 30200, 'Help text', '')),
    ("L[lvalues#0](30100, 'A')", ('lvalues#0', 30100, 'A', '')),
    ("L[font-size](30100, 'X')", ('font-size', 30100, 'X', '')),
    ("L[xmlns:foo](30100, 'X')", ('xmlns:foo', 30100, 'X', '')),
    ('L(30100, "double quoted")', (None, 30100, 'double quoted', '')),
    # - round-trip
    ("L(30100, 'A\\u002d\\u002dB')", (None, 30100, 'A--B', '')),
    # Polish letters preserved
    ("L(30100, 'Filmy żółte')", (None, 30100, 'Filmy żółte', '')),
    # context
    ("L[label](30100, 'Open', ctx='verb')", ('label', 30100, 'Open', 'verb')),
    ("L(30100, 'Open', ctx = \"menu: file\")", (None, 30100, 'Open', 'menu: file')),
])
def test_parse(comment, expected):
    assert _parse_l_comment(comment) == expected


@pytest.mark.parametrize('comment', [
    "L[](30100, 'x')",       # empty bracket
    "L(30100)",              # missing text
    "not L",
    "",
])
def test_parse_invalid(comment):
    assert _parse_l_comment(comment) is None


@pytest.mark.parametrize('attr, label_id, text', [
    (None, 30100, 'Movies'),
    ('label', 30100, 'Movies'),
    ('help', 30200, 'Help text'),
    ('lvalues#0', 30100, 'A'),
    (None, 30100, "with 'apostrophe'"),
    (None, 30100, 'with "double" quotes'),
    (None, 30100, 'A--B'),
    (None, 30100, 'A---B'),
    (None, 30100, '--- sekcja ---'),
    (None, 30100, 'with\nnewline'),
    (None, 30100, 'A\\B'),
    (None, 30100, 'Filmy żółte'),
    (None, 30100, ''),
])
def test_roundtrip(attr, label_id, text):
    body = _format_L_comment(attr, label_id, text)
    assert '--' not in body, f'serialized comment must not contain "--": {body!r}'
    parsed = _parse_l_comment(body)
    assert parsed == (attr, label_id, text, '')


@pytest.mark.parametrize('ctx', ['verb', 'a--b', "it's"])
def test_roundtrip_ctx(ctx):
    body = _format_L_comment('label', 30100, 'Open', ctx)
    assert '--' not in body
    assert _parse_l_comment(body) == ('label', 30100, 'Open', ctx)
