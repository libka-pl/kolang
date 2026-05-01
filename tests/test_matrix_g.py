"""H.8: matrix G (read-side) — XML value vs L() comment."""
import textwrap


PO_BASE = (
    'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n'
)


def test_number_no_comment_is_reference(addon, kolang_run):
    (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').write_text(
        PO_BASE + 'msgctxt "#30100"\nmsgid "Movies"\nmsgstr ""\n', encoding='utf-8'
    )
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="30100"/></settings>', encoding='utf-8'
    )
    rc, _out = kolang_run()
    assert rc == 0


def test_text_no_comment_new_declaration(addon, kolang_run, po_path):
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="Movies"/></settings>', encoding='utf-8'
    )
    rc, _out = kolang_run()
    assert rc == 0
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "Movies"' in po


def test_number_matching_comment(addon, kolang_run):
    (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').write_text(
        PO_BASE + 'msgctxt "#30100"\nmsgid "Movies"\nmsgstr ""\n', encoding='utf-8'
    )
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- L[label](30100, 'Movies') -->
              <setting label="30100"/>
            </settings>
        ''').strip(), encoding='utf-8'
    )
    rc, out = kolang_run()
    assert rc == 0
    assert 'mismatch' not in out.lower()


def test_id_mismatch_warning_comment_wins(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- L[label](30200, 'Movies') -->
              <setting label="30100"/>
            </settings>
        ''').strip(), encoding='utf-8'
    )
    rc, out = kolang_run()
    assert rc == 0
    assert 'mismatch' in out.lower()
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert '<setting label="30200"/>' in xml


def test_text_same_as_comment_warning_replaced(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- L[label](30100, 'Movies') -->
              <setting label="Movies"/>
            </settings>
        ''').strip(), encoding='utf-8'
    )
    rc, out = kolang_run()
    assert rc == 0
    assert 'duplicate' in out.lower() or 'duplicates' in out.lower()
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert '<setting label="30100"/>' in xml


def test_text_differs_from_comment_hard_error(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- L[label](30100, 'Movies') -->
              <setting label="Other"/>
            </settings>
        ''').strip(), encoding='utf-8'
    )
    rc, out = kolang_run()
    assert rc == 1
    assert 'mismatch' in out.lower()
