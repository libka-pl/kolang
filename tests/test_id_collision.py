"""Same ID with different texts in sources (e.g. after merging branches) is a collision, not a rename.

The text matching PO keeps the ID, the other one gets a new ID without the colliding translation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MAIN = "m = L(30100, 'From main')\n"
OTHER = "o = L(30100, 'From branch')\n"


def write_py(addon: Path, body: str) -> Path:
    """Write `body` as the addon python source, return its path."""
    path = addon / 'resources' / 'lib' / 'main.py'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'from kolang import L\n{body}', encoding='utf-8')
    return path


def collide(addon: Path, kolang_run, order: str) -> Path:
    """Create PO with 30100='From main', then add colliding 'From branch' (before or after)."""
    write_py(addon, MAIN)
    assert kolang_run()[0] == 0
    return write_py(addon, OTHER + MAIN if order == 'before' else MAIN + OTHER)


@pytest.mark.parametrize('order', ['before', 'after'])
def test_py_collision_keeps_both(addon: Path, kolang_run, po_path: Path, order: str) -> None:
    """Both texts survive, PO text keeps its ID, the other gets a new one."""
    py = collide(addon, kolang_run, order)
    rc, out = kolang_run()
    assert rc == 0, out
    src = py.read_text(encoding='utf-8')
    assert "L(30100, 'From main')" in src
    assert "L(30101, 'From branch')" in src
    po = po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "From main"' in po
    assert 'msgctxt "#30101"\nmsgid "From branch"' in po


def test_collision_does_not_copy_translation(addon: Path, kolang_run, po_path: Path) -> None:
    """New ID of the colliding text doesn't inherit translation of the other text."""
    collide(addon, kolang_run, 'after')
    po = po_path.read_text(encoding='utf-8')
    po_path.write_text(po.replace('msgid "From main"\nmsgstr ""', 'msgid "From main"\nmsgstr "Z maina"'), encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "From main"\nmsgstr "Z maina"' in po
    assert 'msgid "From branch"\nmsgstr ""' in po


def test_xml_py_collision(addon: Path, kolang_run, po_path: Path) -> None:
    """Collision between settings.xml (L[] comment) and python keeps both texts."""
    write_py(addon, MAIN)
    assert kolang_run()[0] == 0
    (addon / 'resources' / 'settings.xml').write_text(
        "<settings>\n  <!-- L[label](30100, 'Setting') -->\n  <setting label=\"30100\"/>\n</settings>\n", encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30101, 'Setting')" in xml
    assert '<setting label="30101"/>' in xml
    po = po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "From main"' in po
    assert 'msgctxt "#30101"\nmsgid "Setting"' in po


def test_py_edit_still_renames(addon: Path, kolang_run, po_path: Path) -> None:
    """Single edited text (old one not referenced anymore) keeps the ID."""
    py = write_py(addon, MAIN)
    assert kolang_run()[0] == 0
    write_py(addon, "m = L(30100, 'From main, edited')\n")
    rc, out = kolang_run()
    assert rc == 0, out
    assert "L(30100, 'From main, edited')" in py.read_text(encoding='utf-8')
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "From main, edited"' in po
    assert 'msgid "From main"\n' not in po
