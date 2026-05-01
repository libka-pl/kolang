"""I.2: python mode resolver — defaults + whitelist + override."""
from lxml import etree

from kolang import Translate


def make_tree(xml: bytes):
    root = etree.fromstring(xml)
    return {Translate._tag_local(n): n for n in root.iter() if isinstance(n.tag, str)}


def test_default_whitelist_present():
    t = Translate()
    assert 'ff:vars' in t.python_tags
    assert ('ff:define', 'args') in t.python_attrs
    assert ('ff:include', 'ff:args') in t.python_attrs
    assert ('ff:set', 'value') in t.python_attrs


def test_skin_default_fstring():
    t = Translate()
    nodes = make_tree(b'<root xmlns:ff="ff"><label>X</label></root>')
    assert t._python_mode(nodes['label'], '', is_skin=True) == 'fstring'


def test_settings_default_false():
    t = Translate()
    nodes = make_tree(b'<root xmlns:ff="ff"><label>X</label></root>')
    assert t._python_mode(nodes['label'], '', is_skin=False) == 'false'


def test_whitelist_tag_active_in_settings():
    t = Translate()
    nodes = make_tree(b'<root xmlns:ff="ff"><ff:vars>X</ff:vars></root>')
    assert t._python_mode(nodes['ff:vars'], '', is_skin=False) == 'true'


def test_whitelist_attr_per_tag():
    t = Translate()
    nodes = make_tree(b'<root xmlns:ff="ff"><ff:set value="X"/></root>')
    assert t._python_mode(nodes['ff:set'], 'value', is_skin=True) == 'true'
    # other attrs on ff:set fall back to skin default
    assert t._python_mode(nodes['ff:set'], 'other', is_skin=True) == 'fstring'


def test_override_wins_over_whitelist():
    t = Translate()
    xml = b'<root xmlns:ff="ff"><!-- :python=false: --><ff:vars>X</ff:vars></root>'
    nodes = make_tree(xml)
    assert t._python_mode(nodes['ff:vars'], '', is_skin=True) == 'false'


def test_config_extends_defaults():
    t = Translate(python_tags=['custom:tag'], python_attrs=['always'])
    assert 'ff:vars' in t.python_tags
    assert 'custom:tag' in t.python_tags
    assert (None, 'always') in t.python_attrs
    # default still present
    assert ('ff:vars', ) == ('ff:vars',) and 'ff:vars' in t.python_tags
