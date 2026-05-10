"""I.4 + I.5: skin templates (raw + fstring), automat=false on fstring+{}."""
import textwrap


def write_skin(addon, body):
    (addon / 'resources' / 'skins' / 'Default' / '720p').mkdir(parents=True, exist_ok=True)
    (addon / 'resources' / 'skins' / 'Default' / '720p' / 'D.xml').write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n<window xmlns:ff="ff">\n{body}\n</window>\n',
        encoding='utf-8',
    )


def po_msgids(po_path):
    if not po_path.exists():
        return []
    return [
        line.split(' ', 1)[1].strip().strip('"')
        for line in po_path.read_text(encoding='utf-8').splitlines()
        if line.startswith('msgid "') and line != 'msgid ""'
    ]


def test_fstring_label_no_full_translate(addon, kolang_run, po_path):
    """Label with `{L(...)}` — only inner string registered, NOT whole label."""
    write_skin(addon, "  <controls><label>Welcome {L('user')}</label></controls>")
    rc, _ = kolang_run()
    assert rc == 0
    msgids = po_msgids(po_path)
    assert 'user' in msgids
    assert "Welcome {L(30100, 'user')}" not in msgids


def test_plain_skin_label_translated_normally(addon, kolang_run, po_path):
    write_skin(addon, '  <controls><label>Plain text</label></controls>')
    rc, _ = kolang_run()
    assert rc == 0
    assert 'Plain text' in po_msgids(po_path)


def test_raw_python_in_ff_vars(addon, kolang_run, po_path):
    write_skin(addon, "  <controls><ff:vars>x = L('vars')</ff:vars></controls>")
    rc, _ = kolang_run()
    assert rc == 0
    assert 'vars' in po_msgids(po_path)


def test_raw_python_in_ff_set_value(addon, kolang_run, po_path):
    write_skin(addon, "  <controls><ff:set value=\"L('attr')\"/></controls>")
    rc, _ = kolang_run()
    assert rc == 0
    assert 'attr' in po_msgids(po_path)


def test_translate_false_skips_python_too_for_label(addon, kolang_run, po_path):
    """:translate=false: blocks label-translation but :python=fstring: still scans {…}.
    Note: per spec, :translate doesn't disable python — only :python=false: does."""
    write_skin(addon, textwrap.dedent('''
          <controls>
            <!-- :translate=false: -->
            <label>Welcome {L('user')}</label>
          </controls>
    '''))
    rc, _ = kolang_run()
    assert rc == 0
    # `{L('user')}` still scanned by fstring → 'user' in PO
    assert 'user' in po_msgids(po_path)


def test_python_false_skips_template_scan(addon, kolang_run, po_path):
    write_skin(addon, textwrap.dedent('''
          <controls>
            <!-- :python=false: -->
            <ff:vars>x = L('blocked')</ff:vars>
          </controls>
    '''))
    rc, _ = kolang_run()
    assert rc == 0
    assert 'blocked' not in po_msgids(po_path)
