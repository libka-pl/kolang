"""Notes for translators (B17): `Translators:` comments in Python and XML → `#. Translators: …` in PO."""
from __future__ import annotations

from pathlib import Path


def write_py(addon: Path, body: str) -> None:
    """Write `body` as the addon python source."""
    (addon / 'main.py').write_text(f'from kolang import L\n{body}', encoding='utf-8')


def run(kolang_run, po_path: Path) -> str:
    """Run kolang, return en PO text."""
    rc, out = kolang_run()
    assert rc == 0, out
    return po_path.read_text(encoding='utf-8')


def test_py_block_and_trailing(addon: Path, kolang_run, po_path: Path) -> None:
    """Comment block above the line (continued lines joined) or trailing comment; other comments ignored."""
    write_py(addon, '# Translators: button in the main menu,\n'
                    '#   keep it short\n'
                    "a = L('Open')\n"
                    "b = L('Close')  # translators: closes: the dialog\n"
                    '# just a comment\n'
                    "c = L('Plain')\n"
                    '# Translators: not adjacent\n'
                    '\n'
                    "d = L('Far')\n")
    po = run(kolang_run, po_path)
    assert '#. Translators: button in the main menu, keep it short\nmsgctxt "#30100"\nmsgid "Open"' in po
    assert '#. Translators: closes: the dialog\nmsgctxt "#30101"\nmsgid "Close"' in po
    assert 'msgctxt "#30102"' in po and po.count('Translators') == 2


def test_notes_joined_and_order(addon: Path, kolang_run, po_path: Path) -> None:
    """Same text in more places: notes joined without duplicates; context line first, plural note last."""
    write_py(addon, "# Translators: first\na = L('{n} file|||{n} files', n=1, ctx='disk')\n"
                    "# Translators: second\nb = L('{n} file|||{n} files', n=2, ctx='disk')\n"
                    "# Translators: first\nc = L('{n} file|||{n} files', n=3, ctx='disk')\n")
    po = run(kolang_run, po_path)
    assert ('#. context: disk\n#. Translators: first\n#. Translators: second\n#. 2 plural forms separated by |||\n'
            in po), po
    assert run(kolang_run, po_path) == po    # idempotent


def test_note_removed_with_source_comment(addon: Path, kolang_run, po_path: Path) -> None:
    """Note follows the source: removed comment → removed PO line; hand-written `#.` lines are kept."""
    write_py(addon, "# Translators: old\na = L('Open')\n")
    po = run(kolang_run, po_path)
    po_path.write_text(po.replace('#. Translators: old\n', '#. Translators: old\n#. Hand note\n'), encoding='utf-8')
    write_py(addon, "a = L(30100, 'Open')\n")
    po = run(kolang_run, po_path)
    assert 'Translators' not in po
    assert '#. Hand note\nmsgctxt "#30100"' in po


def test_xml_notes(addon: Path, kolang_run, po_path: Path) -> None:
    """XML: general note for all targets, `[attr]` for one, also L() in raw Python values of the element."""
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings>\n'
        '  <!-- Translators: video settings -->\n'
        '  <!-- Translators[help]: shown under: the label -->\n'
        '  <setting label="Movies" help="Help text"/>\n'
        '  <!-- Translators: raw python value -->\n'
        '  <ff:set xmlns:ff="ff" value="L(\'Raw\')"/>\n'
        '</settings>\n', encoding='utf-8')
    po = run(kolang_run, po_path)
    assert '#. Translators: video settings\nmsgctxt "#30101"\nmsgid "Movies"' in po, po
    assert '#. Translators: video settings\n#. Translators: shown under: the label\nmsgctxt "#30102"\nmsgid "Help text"' in po
    assert '#. Translators: raw python value\nmsgctxt "#30100"\nmsgid "Raw"' in po
