"""Kodi PO comments without space after `#` (B22): `#empty strings …`, `#.Item label …` are read like `# …`, `#. …`."""
from __future__ import annotations

from pathlib import Path

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def test_comments_without_space(addon: Path, kolang_run, po_path: Path) -> None:
    """PO in Kodi core/Estuary style is parsed, comments kept (normalized), obsolete `#~` entries untouched."""
    (addon / 'main.py').write_text("from kolang import L\na = L(30100, 'A')\nb = L(30103, 'B')\n", encoding='utf-8')
    po_path.write_text(HEADER + 'msgctxt "#30100"\nmsgid "A"\nmsgstr ""\n\n'
                       '#empty strings from id 30101 to 30102\n\n'
                       '#.Item label\n#:xbmc/x.cpp\nmsgctxt "#30103"\nmsgid "B"\nmsgstr ""\n\n'
                       '#~ msgctxt "#30104"\n#~ msgid "Old"\n#~ msgstr ""\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    po = po_path.read_text(encoding='utf-8')
    assert '# empty strings from id 30101 to 30102\n#. Item label\n#: xbmc/x.cpp\nmsgctxt "#30103"\nmsgid "B"' in po, po
    assert '#~ msgid "Old"' in po
