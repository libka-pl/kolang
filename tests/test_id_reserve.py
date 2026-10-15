"""`--id-reserve` (B19): labels move out of a reserved range with their translations."""
from __future__ import annotations

from pathlib import Path

CONF = ('{"options": {"addon-id": "t.test", "id-from": 30100}, '
        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n')


def setup(addon: Path, kolang_run, body: str) -> tuple[Path, Path]:
    """Write config and python source, run kolang, return (source, pl PO)."""
    (addon / '.kolang.json').write_text(CONF, encoding='utf-8')
    py = addon / 'main.py'
    py.write_text(f'from kolang import L\n{body}', encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern')
    assert rc == 0, out
    return py, addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def translate(po: Path, text: str, tr: str) -> None:
    """Set translation of `text`."""
    po.write_text(po.read_text(encoding='utf-8').replace(f'msgid "{text}"\nmsgstr ""', f'msgid "{text}"\nmsgstr "{tr}"'),
                  encoding='utf-8')


def test_move_keeps_translation(addon: Path, kolang_run, po_path: Path) -> None:
    """Moved labels keep translation, flags and context; new IDs in ID order; sources and XML rewritten."""
    (addon / 'resources' / 'settings.xml').write_text('<settings>\n  <setting label="Gamma"/>\n</settings>\n', encoding='utf-8')
    py, pl = setup(addon, kolang_run, "a = L('Alpha')\nb = L('Beta', ctx='verb')\nc = L('Other')\n")
    assert "a = L(30101, 'Alpha')" in py.read_text(encoding='utf-8')   # settings.xml first: Gamma 30100
    translate(pl, 'Alpha', 'Alfa')
    translate(pl, 'Beta', 'Beta-pl')
    pl.write_text(pl.read_text(encoding='utf-8').replace('msgctxt "#30101"', '#, fuzzy\nmsgctxt "#30101"'), encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern', '--id-reserve', '30100-30102')
    assert rc == 0, out
    assert py.read_text(encoding='utf-8') == "from kolang import L\na = L(30105, 'Alpha')\nb = L(30106, 'Beta', ctx='verb')\nc = L(30103, 'Other')\n"
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30104, 'Gamma')" in xml and 'label="30104"' in xml
    text = pl.read_text(encoding='utf-8')
    assert '#, fuzzy\nmsgctxt "#30105"\nmsgid "Alpha"\nmsgstr "Alfa"' in text
    assert '#. context: verb\nmsgctxt "#30106"\nmsgid "Beta"\nmsgstr "Beta-pl"' in text
    for mid in (30100, 30101, 30102):
        assert f'"#{mid}"' not in text and f'"#{mid}"' not in po_path.read_text(encoding='utf-8')


def test_unreferenced_removed(addon: Path, kolang_run) -> None:
    """Label only in PO (obsolete) in the reserved range is removed, not moved."""
    py, pl = setup(addon, kolang_run, "a = L('Alpha')\nb = L('Beta')\n")
    py.write_text("from kolang import L\nb = L(30101, 'Beta')\n", encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern', '--id-reserve', '30100')
    assert rc == 0, out
    text = pl.read_text(encoding='utf-8')
    assert 'Alpha' not in text and 'msgctxt "#30102"' not in text


def test_numeric_reference_is_error(addon: Path, kolang_run) -> None:
    """Reserved ID used by number is not moved: error, nothing written."""
    py, pl = setup(addon, kolang_run, "a = L('Alpha')\n")
    py.write_text("from kolang import L\na = L(30100, 'Alpha')\nx = getLocalizedString(30100)\n", encoding='utf-8')
    before = pl.read_text(encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern', '--id-reserve', '30100')
    assert rc == 1 and '[30100]' in out, out
    assert "a = L(30100, 'Alpha')" in py.read_text(encoding='utf-8')
    assert pl.read_text(encoding='utf-8') == before
