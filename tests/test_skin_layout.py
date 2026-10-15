"""Skin addon layout (B25): XML folders from addon.xml `<res folder=…>`, guard for `--obsolete` without sources."""
from __future__ import annotations

from pathlib import Path

from conftest import run_kolang

SKIN_ADDON = ('<addon id="skin.t" name="t" version="1" provider-name="t">\n'
              '  <extension point="xbmc.gui.skin"><res width="1920" height="1080" folder="xml"/>'
              '<res width="1280" height="720" folder="xml"/></extension>\n</addon>\n')
HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def skin(tmp_path: Path) -> Path:
    """Create skin addon with language/ en_gb PO (31000 used by $LOCALIZE, 31001 unused) and xml/ folder."""
    (tmp_path / 'addon.xml').write_text(SKIN_ADDON, encoding='utf-8')
    po = tmp_path / 'language' / 'resource.language.en_gb' / 'strings.po'
    po.parent.mkdir(parents=True)
    po.write_text(HEADER + 'msgctxt "#31000"\nmsgid "Used"\nmsgstr ""\n\nmsgctxt "#31001"\nmsgid "Unused"\nmsgstr ""\n',
                  encoding='utf-8')
    (tmp_path / 'xml').mkdir()
    (tmp_path / 'xml' / 'Home.xml').write_text('<window>\n  <label>$LOCALIZE[31000]</label>\n</window>\n', encoding='utf-8')
    (tmp_path / 'shortcuts').mkdir()
    (tmp_path / 'shortcuts' / 'menu.DATA.xml').write_text('<shortcuts>\n  <label>$LOCALIZE[31001]</label>\n</shortcuts>\n',
                                                          encoding='utf-8')
    return po


def test_skin_folders_scanned(tmp_path: Path) -> None:
    """References in `<res folder>` and `shortcuts/` keep the strings; nothing is obsolete."""
    po = skin(tmp_path)
    rc, out = run_kolang(tmp_path, '--no-backup-pattern', '-L', 'en', '--obsolete', 'mark')
    assert rc == 0, out
    assert '#~' not in po.read_text(encoding='utf-8')
    assert 'obsolete: 0' in out, out


def test_obsolete_without_sources_is_error(tmp_path: Path) -> None:
    """No source file scanned: `--obsolete mark/remove` stops, PO untouched; `keep` runs."""
    po = skin(tmp_path)
    for name in ('xml', 'shortcuts'):
        for f in (tmp_path / name).iterdir():
            f.unlink()
    before = po.read_text(encoding='utf-8')
    rc, out = run_kolang(tmp_path, '--no-backup-pattern', '-L', 'en', '--obsolete', 'remove')
    assert rc == 1 and 'No source file scanned' in out, out
    assert po.read_text(encoding='utf-8') == before
    rc, out = run_kolang(tmp_path, '--no-backup-pattern', '-L', 'en')
    assert rc == 0, out


def test_includes_and_skin_attributes(tmp_path: Path) -> None:
    """`<includes>` is scanned like a window; `viewtype@label`, `fontset@idloc` numbers are references."""
    po = skin(tmp_path)
    po.write_text(po.read_text(encoding='utf-8') + '\nmsgctxt "#31002"\nmsgid "Icons"\nmsgstr ""\n\n'
                  'msgctxt "#31003"\nmsgid "Arial"\nmsgstr ""\n', encoding='utf-8')
    (tmp_path / 'xml' / 'Includes.xml').write_text('<includes>\n  <viewtype label="31002">icon</viewtype>\n'
                                                   '  <label>Plain text</label>\n</includes>\n', encoding='utf-8')
    (tmp_path / 'xml' / 'Font.xml').write_text('<fonts>\n  <fontset id="Arial" idloc="31003"/>\n</fonts>\n', encoding='utf-8')
    rc, out = run_kolang(tmp_path, '--no-backup-pattern', '-L', 'en', '--obsolete', 'mark')
    assert rc == 0, out
    text = po.read_text(encoding='utf-8')
    assert '#~' not in text, text
    assert 'msgid "Plain text"' in text
    assert '<label>$ADDON[skin.t 31004]</label>' in (tmp_path / 'xml' / 'Includes.xml').read_text(encoding='utf-8')
