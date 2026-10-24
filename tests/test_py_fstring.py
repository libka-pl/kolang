"""Python `L()` inside f-strings (B40): IDs inserted in `{…}` code, PEP 701 nesting, literal braces skipped."""
from __future__ import annotations

from pathlib import Path

import pytest

from kolang import _extract_fstring_blocks, _scan_str

SOURCE = '''from kolang import L
a = f'{L("A")}: {y}'
b = f"{L('B')}: {y}"
c = f'{L("C", n=y)}'
d = f'pre {L("D")}' + L('E')
e = f'{{L("no")}}'
f = rf'{L("F")!r:>{w}}'
g = f'{f"{L("G")}"}'
h = f\'\'\'{L("H")
# comment
}\'\'\'
i = f'{L('I')}'
# Translators: note for J
j = t'{L("J")}'
k = 'plain {L("no")}'
'''

EXPECTED = '''from kolang import L
a = f'{L(30100, "A")}: {y}'
b = f"{L(30101, 'B')}: {y}"
c = f'{L(30102, "C", n=y)}'
d = f'pre {L(30103, "D")}' + L(30104, 'E')
e = f'{{L("no")}}'
f = rf'{L(30105, "F")!r:>{w}}'
g = f'{f"{L(30106, "G")}"}'
h = f\'\'\'{L(30107, "H")
# comment
}\'\'\'
i = f'{L(30108, 'I')}'
# Translators: note for J
j = t'{L(30109, "J")}'
k = 'plain {L("no")}'
'''


def test_fstring_scan(addon: Path, kolang_run, po_path: Path) -> None:
    """All f-string shapes get IDs, locations and notes; second run changes nothing."""
    py = addon / 'main.py'
    py.write_text(SOURCE, encoding='utf-8')
    rc, out = kolang_run('--locations', 'line')
    assert rc == 0, out
    assert py.read_text(encoding='utf-8') == EXPECTED
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "no"' not in po
    assert '#: main.py:9\nmsgctxt "#30107"\nmsgid "H"' in po, po
    assert '#. Translators: note for J\n#: main.py:14\nmsgctxt "#30109"' in po, po
    rc, out = kolang_run('--check', '--locations', 'line')
    assert rc == 0, out


@pytest.mark.parametrize('src, blocks', [
    ("'plain {x}'", []),
    ("f'{x}'", ['x']),
    ("f'{{x}}'", []),
    ("f'{a!=b}'", ['a!=b']),
    ("f'{x!r:>{w}}'", ['x', 'w']),
    ("f'{x=}'", ['x=']),
    ('f\'{d["}"]}\'', ['d["}"]']),
    ("f'{L('x')}'", ["L('x')"]),
    ("f'\\N{DASH}{x}'", ['x']),
    ("rf'\\N{x}'", ['x']),
    ("rb'\\''", []),
    ("t'{x}'", ['x']),
])
def test_scan_str(src: str, blocks: list[str]) -> None:
    """Literal end and `{…}` code of the literal."""
    stop, found = _scan_str(src + ' + tail', 0, len(src) + 7)
    assert stop == len(src)
    assert [src[a:b] for a, b in found] == blocks


@pytest.mark.parametrize('src', ["f'{x'", "f'abc", "'abc\n'", "f'{x!r'"])
def test_scan_str_unterminated(src: str) -> None:
    """Broken literal: no end (caller keeps the old behaviour)."""
    assert _scan_str(src, 0, len(src))[0] is None


def test_xml_blocks_string_with_brace() -> None:
    """XML f-string mode: `}` inside a string of the expression doesn't end it, spec has own blocks."""
    assert _extract_fstring_blocks('{d["}"]} tail {x}') == [(1, 7, 'd["}"]'), (15, 16, 'x')]
    assert _extract_fstring_blocks('{x:>{w}}') == [(1, 2, 'x'), (5, 6, 'w')]
