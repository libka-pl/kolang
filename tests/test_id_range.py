"""B28: ID range defaults from addon type (skin 31000-31999), CLI options win over `.kolang.json`."""
from __future__ import annotations

from pathlib import Path

from conftest import run_kolang
from test_skin_layout import HEADER, SKIN_ADDON


def skin(tmp_path: Path, window: str) -> Path:
    """Create skin addon with own strings #31000 and #30500 and `xml/Home.xml` with `window` body. Return PO path."""
    (tmp_path / 'addon.xml').write_text(SKIN_ADDON, encoding='utf-8')
    po = tmp_path / 'language' / 'resource.language.en_gb' / 'strings.po'
    po.parent.mkdir(parents=True)
    po.write_text(HEADER + 'msgctxt "#31000"\nmsgid "Used"\nmsgstr ""\n\nmsgctxt "#30500"\nmsgid "Low"\nmsgstr ""\n',
                  encoding='utf-8')
    (tmp_path / 'xml').mkdir()
    (tmp_path / 'xml' / 'Home.xml').write_text(f'<window>\n  <label>$LOCALIZE[31000]</label>\n{window}</window>\n', encoding='utf-8')
    return po


def test_skin_new_id_in_skin_range(tmp_path: Path) -> None:
    """New skin text gets ID from 31100, #31000 is not reported as below `id-min`."""
    po = skin(tmp_path, '  <label>Brand new</label>\n')
    rc, out = run_kolang(tmp_path)
    assert rc == 0, out
    assert 'msgctxt "#31100"\nmsgid "Brand new"' in po.read_text(encoding='utf-8')
    assert 'Label #31000 <' not in out


def test_skin_numeric_ref_outside_range_warns(tmp_path: Path) -> None:
    """Own string used by number outside 31000-31999 isn't found by Kodi — warning with location."""
    skin(tmp_path, '  <label>$LOCALIZE[30500]</label>\n')
    rc, out = run_kolang(tmp_path)
    assert rc == 0, out
    assert 'Skin string #30500 is used by number' in out
    assert 'Home.xml:3' in out
    assert '#31000 is used' not in out


def test_cli_id_from_wins_over_config(addon: Path) -> None:
    """`--id-from` beats `id-from` in `.kolang.json` (30100 in the fixture)."""
    (addon / 'x.py').write_text("L('Hello')\n", encoding='utf-8')
    rc, out = run_kolang(addon, '--id-from', '30500')
    assert rc == 0, out
    assert "L(30500, 'Hello')" in (addon / 'x.py').read_text(encoding='utf-8')
