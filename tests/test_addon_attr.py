"""`$ADDON[addon N]` / `$ADDON[addon text]` in an attribute value of a window XML is used like in a text (B55)."""
from __future__ import annotations

from pathlib import Path

from test_skin_localize import run, skin

BUTTONS = ('  <gui:push_button name="rescan" text="$ADDON[skin.t 31000]"/>\n'
           '  <gui:combo_box name="title" label="$ADDON[skin.t Original Title:]" hint="Title"/>\n')


def test_addon_in_attributes(tmp_path: Path) -> None:
    """The number stays used (not obsolete), gets its `L[text]` comment; the text gets an ID; idempotent."""
    xml, po = skin(tmp_path, BUTTONS)
    xml.write_text(xml.read_text(encoding='utf-8').replace('<window>', '<window xmlns:gui="gui">'), encoding='utf-8')
    run(tmp_path)
    out = xml.read_text(encoding='utf-8')
    assert "<!-- L[text](31000, 'Bitrate') -->" in out
    assert "<!-- L[label](31100, 'Original Title:') -->" in out
    assert 'label="$ADDON[skin.t 31100]"' in out and 'hint="Title"' in out
    po_src = po.read_text(encoding='utf-8')
    assert '#~' not in po_src and 'msgid "Original Title:"' in po_src, po_src
    run(tmp_path)
    assert xml.read_text(encoding='utf-8') == out
    assert po.read_text(encoding='utf-8') == po_src
