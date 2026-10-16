"""Python `L()` scan (B18): multi-line calls, adjacent literals, ID-only references, non-literal warning."""
from __future__ import annotations

from pathlib import Path

SOURCE = '''from kolang import L
a = L('Multi',
      n=1)
b = L(
    'Open paren')
c = L('Part one '  # it's a comment
      "part two", ctx='verb')
d = L(30200)
e = L(30201, n=2)
f = L(f'Dynamic {x}')
g = L('Plus ' + x)
h = L('Nested', n=len(x))
i = L(var)
'''

EXPECTED = '''from kolang import L
a = L(30202, 'Multi',
      n=1)
b = L(
    30203, 'Open paren')
c = L(30204, 'Part one '  # it's a comment
      "part two", ctx='verb')
d = L(30200)
e = L(30201, n=2)
f = L(f'Dynamic {x}')
g = L('Plus ' + x)
h = L(30205, 'Nested', n=len(x))
i = L(var)
'''

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def test_scan(addon: Path, kolang_run, po_path: Path) -> None:
    """All call shapes: IDs inserted before the text, ID-only calls are used, warnings for non-literal text."""
    py = addon / 'main.py'
    py.write_text(SOURCE, encoding='utf-8')
    po_path.write_text(HEADER + ''.join(f'msgctxt "#{n}"\nmsgid "Ref {n}"\nmsgstr ""\n\n' for n in (30200, 30201)), encoding='utf-8')
    rc, out = kolang_run('--obsolete', 'mark')
    assert rc == 0, out
    assert py.read_text(encoding='utf-8') == EXPECTED
    po = po_path.read_text(encoding='utf-8')
    assert '#~' not in po, po                                             # L(30200), L(30201, n=2) are used
    assert 'msgid "Part one part two"' in po and '#. context: verb\nmsgctxt "#30204"' in po
    assert 'main.py:10: L() text is not a plain string literal' in out and 'main.py:11:' in out, out
    assert out.count('not a plain string literal') == 2, out
    rc, out = kolang_run('--obsolete', 'mark')
    assert rc == 0, out
    assert py.read_text(encoding='utf-8') == EXPECTED                     # idempotent


def test_reset_concatenated(addon: Path, kolang_run) -> None:
    """`id_end` of a multi-line / concatenated call removes exactly `ID, ` (B15 rewrite span)."""
    from kolang import Translate
    t = Translate(dry_run=True)
    data = "c = L(30204, 'Part one '\n      'part two')\n"
    t._replace_py(data, file=None)
    tr = t._by_id[30204].trans[0]
    assert data[:tr.start] + data[tr.id_end:] == "c = L('Part one '\n      'part two')\n"
