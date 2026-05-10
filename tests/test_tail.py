"""H.11: node.tail in xml_py (skin) — L() in tail discovered."""


def test_tail_l_call(addon, kolang_run, po_path):
    (addon / 'resources' / 'skins' / 'Default' / '720p').mkdir(parents=True, exist_ok=True)
    (addon / 'resources' / 'skins' / 'Default' / '720p' / 'D.xml').write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<window>\n'
        "  <controls><inner/>{L('text-in-tail')}<other/></controls>\n"
        '</window>\n',
        encoding='utf-8',
    )
    rc, _ = kolang_run()
    assert rc == 0
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "text-in-tail"' in po
