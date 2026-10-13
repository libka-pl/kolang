"""Language PO out of sync with the model (same ID, other msgid), e.g. merge driver renumbered languages differently."""
from __future__ import annotations

from pathlib import Path

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def entry(mid: int, text: str, tr: str = '') -> str:
    """Return PO entry text."""
    return f'msgctxt "#{mid}"\nmsgid "{text}"\nmsgstr "{tr}"\n\n'


def test_realign_by_text(addon: Path, kolang_run) -> None:
    """Translations under a wrong ID are moved to the ID of their text, warning is printed."""
    (addon / '.kolang.json').write_text('{"options": {"addon-id": "t.test", "id-from": 30100}, '
                                        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n', encoding='utf-8')
    py = addon / 'resources' / 'lib' / 'main.py'
    py.parent.mkdir(parents=True)
    py.write_text("from kolang import L\na = L(30100, 'A')\nb = L(30101, 'B')\nc = L(30102, 'C')\n", encoding='utf-8')
    lang = addon / 'resources' / 'language'
    en = lang / 'resource.language.en_gb' / 'strings.po'
    en.write_text(HEADER + entry(30100, 'A') + entry(30101, 'B') + entry(30102, 'C'), encoding='utf-8')
    pl = lang / 'resource.language.pl_pl' / 'strings.po'
    pl.parent.mkdir()
    pl.write_text(HEADER + entry(30100, 'A', 'a') + entry(30101, 'C', 'c'), encoding='utf-8')   # C under B's ID, B missing
    rc, out = kolang_run()
    assert rc == 0, out
    assert '#30101' in out and 'realign' in out, out
    text = pl.read_text(encoding='utf-8')
    assert entry(30100, 'A', 'a').rstrip() in text
    assert entry(30101, 'B').rstrip() in text
    assert entry(30102, 'C', 'c').rstrip() in text
