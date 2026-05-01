"""I.3: f-string `{…}` extraction with `{{` / `}}` escape."""
import pytest

from kolang import _extract_fstring_blocks


@pytest.mark.parametrize('text, expected', [
    ('plain text', []),
    ('{x}', [(1, 2, 'x')]),
    ('a {x} b', [(3, 4, 'x')]),
    ('{a}{b}', [(1, 2, 'a'), (4, 5, 'b')]),
    ('a {{ literal }} b', []),       # both escaped
    ('{{x}}', []),                   # literal {x}
    ('{', []),                       # unmatched
    ('}}', []),
])
def test_basic(text, expected):
    assert _extract_fstring_blocks(text) == expected


def test_nested_dict_literal():
    blocks = _extract_fstring_blocks('{ {1: 2} }')
    assert blocks == [(1, 9, ' {1: 2} ')]


def test_nested_fstring():
    blocks = _extract_fstring_blocks('{f"{x}{y}"}')
    # outer { at 0; inner code is f"{x}{y}" length 9; positions 1..10 (exclusive)
    assert blocks == [(1, 10, 'f"{x}{y}"')]
