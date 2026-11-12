"""XML layout: a written XML keeps the layout of its source.

Line breaks and spacing inside start tags, the whitespace around the top-level nodes (B41).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from kolang import Translate

SETTINGS = 'resources/settings.xml'


def test_multiline_start_tag_kept(addon, kolang_run):
    """Unchanged multi-line tag stays as written; translated attribute is patched in place."""
    src = (
        '<settings>\n'
        '  <!-- <fake a="1"> -->\n'
        '  <setting id="a"\n'
        '    label="Hello there"\n'
        "    other='x'\n"
        '    />\n'
        '  <group  x="1"\n'
        '         y="2">text</group>\n'
        '</settings>\n'
    )
    (addon / 'resources' / 'settings.xml').write_text(src, encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert '  <group  x="1"\n         y="2">text</group>\n' in xml
    assert '  <setting id="a"\n    label=' in xml
    assert "\n    other='x'\n    />\n" in xml
    assert 'label="Hello there"' not in xml


def _run_settings(addon: Path, kolang_run, src: str) -> str:
    """Write `src` as settings.xml, run kolang (it translates `Movies`) and return the written file."""
    path = addon / SETTINGS
    path.write_bytes(src.encode('utf-8'))
    rc, out = kolang_run()
    assert rc == 0, out
    return path.read_bytes().decode('utf-8')


def _translated(src: str) -> str:
    """Return `src` as kolang writes it: `Movies` gets ID 30100 and its L() comment."""
    return src.replace(MOVIES, "<!-- L[label](30100, 'Movies') -->\n  <setting id=\"m\" label=\"30100\"")


MOVIES = '<setting id="m" label="Movies"'
BODY = f'<settings>\n  {MOVIES}/>\n</settings>'


@pytest.mark.parametrize('src', [
    pytest.param(f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- a -->\n\n<!--\n  b\n-->\n{BODY}\n', id='prolog'),
    pytest.param(f'{BODY}\n\n<!-- after -->\n<?pi x?>\n\n', id='epilog'),
    pytest.param(f'<?xml version="1.0"?>\n{BODY}', id='no-final-newline'),
    pytest.param(f'<?xml version="1.0"?>\n<!-- a -->{BODY}<!-- z -->', id='glued-kept'),
])
def test_top_level_whitespace(addon, kolang_run, src):
    """Comments and PIs around the root keep their lines, the end of the file keeps its newlines (or none)."""
    assert _run_settings(addon, kolang_run, src) == _translated(src)


def test_start_tags(addon, kolang_run):
    """Unchanged values keep their lines, `>`, references and the place of xmlns:* (lxml puts it first)."""
    src = ('<?xml version="1.0"?>\n'
           '<settings version="1" xmlns:x="x">\n'
           f'  {MOVIES} cond="a >= b\n'
           '                                        and c" other="&gt; &amp;\tx"/>\n'
           '  <x:set value="f(a,\n'
           '                 b) > 0"/>\n'
           '</settings>\n')
    assert _run_settings(addon, kolang_run, src) == _translated(src)


def test_changed_attribute_is_written(addon, kolang_run):
    """A translated value is patched in place, the rest of a multi-line tag stays."""
    src = f'<settings>\n  {MOVIES}\n           cond="a\n  b"/>\n</settings>\n'
    xml = _run_settings(addon, kolang_run, src)
    assert xml == _translated(src)
    assert 'label="30100"\n           cond="a\n  b"/>' in xml


def test_new_top_level_comment(tmp_path):
    """A new node before the root takes the whitespace before the root, the root gets a line of its own."""
    path = tmp_path / 'a.xml'
    path.write_bytes(b'<?xml version="1.0"?>\n<r>\n  <x/>\n</r>\n\n')
    tr = Translate()
    tree = tr.load_xml(path)
    tree.getroot().addprevious(etree.Comment(' new '))
    tree.getroot().addnext(etree.Comment(' end '))
    tr._write_xml(tr.xml_inputs[-1])
    assert path.read_bytes() == b'<?xml version="1.0"?>\n<!-- new -->\n<r>\n  <x/>\n</r>\n<!-- end -->\n\n'
