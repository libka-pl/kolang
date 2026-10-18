"""XML layout: line breaks and spacing inside start tags survive the rewrite."""


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
