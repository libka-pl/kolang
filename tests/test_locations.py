"""`#:` references (B23): style derived from the base language PO or `--locations`, kept order, free text → `#.`."""
from __future__ import annotations

from pathlib import Path

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
CONF = '{"options": {"addon-id": "t.test"}, "languages": ["en", "pl"], "sources": [{"addon": "."}]}\n'


def sources(addon: Path) -> None:
    """Alpha in main.py (line 2) and settings.xml (line 2), Beta in main.py (line 3)."""
    (addon / 'main.py').write_text("from kolang import L\na = L(30100, 'Alpha')\nb = L(30101, 'Beta')\n", encoding='utf-8')
    (addon / 'resources' / 'settings.xml').write_text(
        "<settings>\n  <!-- L[label](30100, 'Alpha') -->\n  <setting label=\"30100\"/>\n</settings>\n", encoding='utf-8')


def test_none_by_default(addon: Path, kolang_run, po_path: Path) -> None:
    """PO without `#:` stays without them (existing kolang addons unchanged)."""
    sources(addon)
    rc, out = kolang_run()
    assert rc == 0, out
    assert '#:' not in po_path.read_text(encoding='utf-8')


def test_option_line_all_languages(addon: Path, kolang_run, po_path: Path) -> None:
    """`--locations line`: sorted file:line references in all language files."""
    (addon / '.kolang.json').write_text(CONF, encoding='utf-8')
    sources(addon)
    rc, out = kolang_run('--locations', 'line')
    assert rc == 0, out
    pl = addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'
    for po in (po_path, pl):
        text = po.read_text(encoding='utf-8')
        assert '#: main.py:2\n#: resources/settings.xml:3\nmsgctxt "#30100"' in text, text
        assert '#: main.py:3\nmsgctxt "#30101"' in text
    rc, out = kolang_run()        # derived from en PO now: line
    assert rc == 0, out
    assert '#: main.py:2\n' in po_path.read_text(encoding='utf-8')


def test_derived_file_kept_order_free_text(addon: Path, kolang_run, po_path: Path) -> None:
    """Kodi style (`/` prefix, file only): existing order kept, gone files removed, new appended, free text → `#.`."""
    sources(addon)
    po_path.write_text(HEADER + '#: /resources/settings.xml /gone.py\n#: /main.py\nmsgctxt "#30100"\nmsgid "Alpha"\nmsgstr ""\n\n'
                       '#: Label of the second item\nmsgctxt "#30101"\nmsgid "Beta"\nmsgstr ""\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    text = po_path.read_text(encoding='utf-8')
    assert '#: /resources/settings.xml\n#: /main.py\nmsgctxt "#30100"' in text, text
    assert '#. Label of the second item\n#: /main.py\nmsgctxt "#30101"' in text, text
    rc, out = kolang_run()
    assert rc == 0, out
    assert po_path.read_text(encoding='utf-8') == text
