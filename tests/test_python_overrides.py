"""I.1: parser & walk-back for `:python=…:` directives."""
from lxml import etree

from kolang import _parse_python_comment, _python_override


def test_parse_simple():
    assert _parse_python_comment(':python=true:') == ('true', {})
    assert _parse_python_comment(':python=fstring:') == ('fstring', {})
    assert _parse_python_comment(':python=false:') == ('false', {})


def test_parse_granular():
    assert _parse_python_comment(':python[label]=true:') == (None, {'label': 'true'})
    assert _parse_python_comment(':python[]=fstring:') == (None, {'': 'fstring'})


def test_parse_invalid():
    assert _parse_python_comment(':python=invalid:') == (None, {})
    assert _parse_python_comment(':translate=true:') == (None, {})  # unrelated directive


def test_resolution_hierarchy():
    xml = (
        b'<root>'
        b'<!-- :python[label]=true: :python=fstring: -->'
        b'<a label="x"/>'
        b'</root>'
    )
    a = etree.fromstring(xml).find('a')
    assert _python_override(a, 'label') == 'true'
    assert _python_override(a, 'help') == 'fstring'  # falls back to general
    assert _python_override(a, None) == 'fstring'
