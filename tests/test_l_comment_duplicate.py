"""Two L[] comments for the same target above one element (e.g. git merged two identical elements into one)."""
from __future__ import annotations

from pathlib import Path

XML = ("<settings>\n  <!-- L[label](30100, 'Setting A') -->\n  <!-- L[label](30100, 'Setting B') -->\n"
       '  <setting label="30100"/>\n</settings>\n')


def test_duplicate_marker_is_error(addon: Path, kolang_run) -> None:
    """Kolang refuses to guess which text belongs to the element, reports the line and changes nothing."""
    settings = addon / 'resources' / 'settings.xml'
    settings.write_text(XML, encoding='utf-8')
    rc, out = kolang_run()
    assert rc != 0
    assert 'settings.xml:4:' in out and 'Setting B' in out, out
    assert settings.read_text(encoding='utf-8') == XML


def test_other_target_marker_is_fine(addon: Path, kolang_run) -> None:
    """Markers for different targets of the same element are not duplicates."""
    (addon / 'resources' / 'settings.xml').write_text(
        "<settings>\n  <!-- L[label](30100, 'Label') -->\n  <!-- L[help](30101, 'Help') -->\n"
        '  <setting label="30100" help="30101"/>\n</settings>\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
