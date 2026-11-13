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


def test_comment_without_id_is_new_text(addon, kolang_run, po_path):
    """`L[label]('text')` (ID removed, new text) next to the old number: new text gets its ID, XML and comment too."""
    po_path.write_text(PO_BASE + 'msgctxt "#30100"\nmsgid "Accounts"\nmsgstr ""\n\n'
                       'msgctxt "#30101"\nmsgid "Configuration"\nmsgstr ""\n', encoding='utf-8')
    (addon / 'resources' / 'lib').mkdir(parents=True)
    main = addon / 'resources' / 'lib' / 'main.py'
    main.write_text("from kolang import L\nL(30101, 'Configuration')\n", encoding='utf-8')
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- L[label]('Configuration') -->
              <!-- L[help]('Open the window.') -->
              <setting label="30100" help="30100"/>
            </settings>
        ''').strip(), encoding='utf-8'
    )
    rc, out = kolang_run()
    assert rc == 0, out
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "<!-- L[label](30101, 'Configuration') -->" in xml       # existing text → its ID
    assert "<!-- L[help](30102, 'Open the window.') -->" in xml     # new text → new ID
    assert '<setting label="30101" help="30102"/>' in xml
    assert "'Accounts'" not in xml
    assert 'msgid "Open the window."' in po_path.read_text(encoding='utf-8')
    rc, out2 = kolang_run()   # idempotent
    assert rc == 0 and (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8') == xml


def test_comment_without_id_and_old_comment(addon, kolang_run):
    """A new-text comment and the old one for the same attribute: error naming both, nothing written."""
    xml = textwrap.dedent('''
        <settings>
          <!-- L[label]('Configuration') -->
          <!-- L[label](30100, 'Accounts') -->
          <setting label="30100"/>
        </settings>
    ''').strip()
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 1
    assert "L[label]('Configuration')" in out and "L[label](30100, 'Accounts')" in out and 'keep one' in out
    assert (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8') == xml


def test_comment_without_id_text_differs_hard_error(addon, kolang_run):
    """XML text other than the new-text comment: two sources of truth, error."""
    (addon / 'resources' / 'settings.xml').write_text(
        "<settings>\n  <!-- L[label]('Configuration') -->\n  <setting label=\"Setup\"/>\n</settings>",
        encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 1 and 'mismatch' in out, out
