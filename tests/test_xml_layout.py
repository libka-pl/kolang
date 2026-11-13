"""XML layout: a written XML keeps the layout of its source.

Line breaks and spacing inside start tags, the whitespace around the top-level nodes (B41), `>` in text (B42),
empty elements (B44), BOM (B48), U+2000–U+200F (B49).
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
    pytest.param(f'\ufeff<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n{BODY}\n', id='bom'),
    pytest.param(f'\ufeff{BODY}\n', id='bom-no-declaration'),
])
def test_top_level_whitespace(addon, kolang_run, src):
    """Comments and PIs around the root keep their lines, the end keeps its newlines (or none), BOM stays."""
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


def test_text_gt_raw(addon, kolang_run):
    """`>` in the text stays as is (lxml writes `&gt;`), a comment is not touched."""
    src = f'<settings>\n  {MOVIES}/>\n  <x>a -> b, c > d</x>\n  <!-- p &gt; q -->\n</settings>\n'
    assert _run_settings(addon, kolang_run, src) == _translated(src)


def test_text_gt_escaped_kept(addon, kolang_run):
    """A file with an escaped `>` in its text keeps it; lxml escapes every `>` in such a file."""
    src = f'<settings>\n  {MOVIES}/>\n  <x>a &gt; b</x>\n</settings>\n'
    assert _run_settings(addon, kolang_run, src) == _translated(src)


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


def test_empty_element_kept(addon, kolang_run):
    """`<x></x>` stays (lxml writes `<x/>`), also with a prefix and with a translated attribute; `<x/>` stays."""
    src = ('<settings xmlns:ff="ff">\n'
           f'  {MOVIES}></setting>\n'
           '  <a></a>\n  <b x="1"\n     ></b>\n  <ff:c></ff:c>\n  <d/>\n'
           '</settings>\n')
    assert _run_settings(addon, kolang_run, src) == _translated(src)


def test_space_refs(addon, kolang_run):
    """U+2000–U+200F written as a reference stay so (lxml writes them raw), raw ones stay raw."""
    src = f'<settings>\n  {MOVIES}/>\n  <x>a&#x200b;b&#8204;c\u200dd\u2009e</x>\n</settings>\n'
    assert _run_settings(addon, kolang_run, src) == _translated(src)
