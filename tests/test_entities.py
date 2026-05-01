"""I.6: XML entities round-trip — ensure they land as plain text in PO."""


def test_entities_in_attribute(addon, kolang_run, po_path):
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings>\n'
        '  <setting label="A &amp; B"/>\n'
        '  <setting label="Cena: 10&#x2026;"/>\n'              # u2026 — outside invisible range
        '  <setting label="C&#x2009;D"/>\n'                     # u2009 — inside u2000-u200f
        '  <setting label="&lt;tag&gt; html"/>\n'
        '</settings>\n',
        encoding='utf-8',
    )
    rc, _ = kolang_run()
    assert rc == 0
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "A & B"' in po
    assert 'msgid "Cena: 10…"' in po
    assert 'msgid "C D"' in po
    assert 'msgid "<tag> html"' in po


def test_settings_xml_re_encodes_invisible_range(addon, kolang_run):
    """Invisible-range char in :translate=false: stays as literal in XML, re-encoded."""
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings>'
        '<!-- :translate=false: -->'
        '<setting label="C D"/>'
        '</settings>\n', encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    out = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert '&#x2009;' in out
    assert ' ' not in out
