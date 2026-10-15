"""Obsolete PO entries with an old text of an active ID (B27): they don't rename the base text, stay obsolete."""
from __future__ import annotations

from pathlib import Path

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
CONF = '{"options": {"addon-id": "t.test"}, "languages": ["en", "pl"], "sources": [{"addon": "."}]}\n'


def test_obsolete_old_text_with_numeric_reference(addon: Path, kolang_run, po_path: Path) -> None:
    """ID used only by number, pl keeps `#~` entry with the old text: en text kept, pl obsolete entry stays obsolete."""
    (addon / '.kolang.json').write_text(CONF, encoding='utf-8')
    (addon / 'main.py').write_text('x = getLocalizedString(30100)\n', encoding='utf-8')
    po_path.write_text(HEADER + 'msgctxt "#30100"\nmsgid "Subtitle codec"\nmsgstr ""\n', encoding='utf-8')
    pl = addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'
    pl.parent.mkdir(parents=True)
    pl.write_text(HEADER + 'msgctxt "#30100"\nmsgid "Subtitle codec"\nmsgstr "Kodek"\n\n'
                  '#~ msgctxt "#30100"\n#~ msgid "Set default"\n#~ msgstr "Ustaw"\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'msgctxt "#30100"\nmsgid "Subtitle codec"\nmsgstr ""' in po_path.read_text(encoding='utf-8')
    text = pl.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Subtitle codec"\nmsgstr "Kodek"' in text
    assert '#~ msgctxt "#30100"\n#~ msgid "Set default"' in text
    assert 'fuzzy' not in text


def test_edit_of_numeric_referenced_text_is_collision(addon: Path, kolang_run, po_path: Path) -> None:
    """New text under an ID used also by number is a collision (new ID), not an edit of the referenced text."""
    (addon / 'main.py').write_text("x = getLocalizedString(30100)\na = L(30100, 'Other')\n", encoding='utf-8')
    po_path.write_text(HEADER + 'msgctxt "#30100"\nmsgid "Subtitle codec"\nmsgstr ""\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    po = po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Subtitle codec"' in po
    assert "a = L(30101, 'Other')" in (addon / 'main.py').read_text(encoding='utf-8')
