"""H.2: parser & walk-back for `:translate=…:` directives."""
from lxml import etree

from kolang import (
    _parse_translate_comment,
    _get_translate_overrides,
    _translation_enabled,
)


def test_parse_simple():
    assert _parse_translate_comment(':translate=false:') == (False, {})
    assert _parse_translate_comment(':translate=true:') == (True, {})


def test_parse_granular():
    assert _parse_translate_comment(':translate[label]=true:') == (None, {'label': True})
    assert _parse_translate_comment(':translate[]=true:') == (None, {'': True})
    assert _parse_translate_comment(':translate[lvalues#0]=false:') == (None, {'lvalues#0': False})


def test_parse_multiple():
    g, p = _parse_translate_comment(':translate=false: :translate[help]=true:')
    assert g is False and p == {'help': True}


def test_parse_invalid_skipped():
    assert _parse_translate_comment(':translate=garbage:') == (None, {})
    assert _parse_translate_comment('not a directive') == (None, {})


def test_walkback_skips_unrelated_comments():
    xml = (
        b'<root>'
        b'<!-- :translate[label]=true: -->'
        b'<!-- random TODO -->'
        b'<!-- :translate[help]=false: -->'
        b'<a label="x" help="y"/>'
        b'</root>'
    )
    a = etree.fromstring(xml).find('a')
    g, p = _get_translate_overrides(a)
    assert g is None
    assert p == {'label': True, 'help': False}


def test_resolution_hierarchy():
    xml = b'<root><!-- :translate=false: --><a/></root>'
    a = etree.fromstring(xml).find('a')
    assert _translation_enabled(a, None) is False
    assert _translation_enabled(a, 'label') is False  # falls back to general
    xml = b'<root><!-- :translate=false: :translate[label]=true: --><a/></root>'
    a = etree.fromstring(xml).find('a')
    assert _translation_enabled(a, 'label') is True
    assert _translation_enabled(a, 'help') is False
