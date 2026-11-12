"""B32: a skin label with `$LOCALIZE[N]` / `$NUMBER[…]` stays literal (not resolved in an `$ADDON` string)."""
from __future__ import annotations

from pathlib import Path

from conftest import run_kolang

SKIN_ADDON = ('<addon id="skin.t" name="t" version="1" provider-name="t">\n'
              '  <extension point="xbmc.gui.skin"><res width="1920" height="1080" folder="xml"/></extension>\n'
              '</addon>\n')
HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
MIXED = ('  <label>$LOCALIZE[31000] kbps</label>\n'
         '  <label>$NUMBER[5] items</label>\n'
         '  <label>$INFO[VideoPlayer.VideoBitrate,[COLOR c]$LOCALIZE[31000]:[/COLOR] , kb/s]</label>\n')


def skin(tmp_path: Path, labels: str) -> tuple[Path, Path]:
    """Create a skin addon with string 31000 in the en_gb PO and `xml/Home.xml` of `labels`; return (xml, po)."""
    (tmp_path / 'addon.xml').write_text(SKIN_ADDON, encoding='utf-8')
    po = tmp_path / 'language' / 'resource.language.en_gb' / 'strings.po'
    po.parent.mkdir(parents=True)
    po.write_text(HEADER + 'msgctxt "#31000"\nmsgid "Bitrate"\nmsgstr ""\n', encoding='utf-8')
    xml = tmp_path / 'xml' / 'Home.xml'
    xml.parent.mkdir()
    xml.write_text(f'<window>\n{labels}</window>\n', encoding='utf-8')
    return xml, po


def run(tmp_path: Path, *args: str) -> str:
    """Run kolang on the skin (English only, obsolete strings marked); return its output."""
    rc, out = run_kolang(tmp_path, '--no-backup-pattern', '-L', 'en', '--obsolete', 'mark', *args)
    assert rc == 0, out
    return out


def test_mixed_labels_stay_literal(tmp_path: Path) -> None:
    """No `$ADDON`, no new PO entry, 31000 stays used; a second run changes nothing."""
    xml, po = skin(tmp_path, MIXED)
    src = xml.read_text(encoding='utf-8')
    run(tmp_path)
    assert xml.read_text(encoding='utf-8') == src
    po_src = po.read_text(encoding='utf-8')
    assert po_src.count('msgid') == 2 and '#~' not in po_src, po_src  # header, 31000
    run(tmp_path)
    assert xml.read_text(encoding='utf-8') == src
    assert po.read_text(encoding='utf-8') == po_src


def test_addon_piece_translated(tmp_path: Path) -> None:
    """A piece marked `$ADDON[text]` gets its ID, the `$LOCALIZE` next to it stays."""
    xml, po = skin(tmp_path, '  <label>$LOCALIZE[31000] $ADDON[kbps]</label>\n')
    run(tmp_path)
    expected = "<!-- L(31100, 'kbps') -->\n  <label>$LOCALIZE[31000] $ADDON[skin.t 31100]</label>"
    assert expected in xml.read_text(encoding='utf-8')
    assert 'msgid "kbps"' in po.read_text(encoding='utf-8')


def test_forced_translate_warns(tmp_path: Path) -> None:
    """`:translate=true:` is obeyed, with a warning: Kodi shows `$LOCALIZE[…]` of the string literally."""
    xml, _ = skin(tmp_path, '  <!-- :translate=true: -->\n  <label>$LOCALIZE[31000] kbps</label>\n')
    out = run(tmp_path)
    assert '$ADDON[skin.t 31100]' in xml.read_text(encoding='utf-8')
    assert 'Home.xml:3:' in out and '$LOCALIZE' in out, out


def test_cleanup_redundant_skip(tmp_path: Path) -> None:
    """`:translate=false:` before such a label is redundant now: `--cleanup-translate-comments` removes it."""
    xml, _ = skin(tmp_path, '  <!-- :translate=false: -->\n  <label>$LOCALIZE[31000] kbps</label>\n')
    run(tmp_path, '--cleanup-translate-comments')
    assert xml.read_text(encoding='utf-8') == '<window>\n  <label>$LOCALIZE[31000] kbps</label>\n</window>\n'
