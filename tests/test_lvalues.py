"""H.10: lvalues per-value support (comments + override)."""
import textwrap

PO_BASE = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n'


def test_mixed_text_numeric(addon, kolang_run):
    (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').write_text(
        PO_BASE + 'msgctxt "#30100"\nmsgid "Comedy"\nmsgstr ""\n', encoding='utf-8'
    )
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting type="enum" lvalues="Action|Drama|30100"/></settings>',
        encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    # Each lvalues index gets its own comment
    assert 'L[lvalues#0](' in xml
    assert 'L[lvalues#1](' in xml
    assert 'L[lvalues#2](30100,' in xml  # migration from PO


def test_override_per_index(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        textwrap.dedent('''
            <settings>
              <!-- :translate[lvalues#1]=false: -->
              <setting type="enum" lvalues="Action|Drama|Comedy"/>
            </settings>
        ''').strip(),
        encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    # Drama (index 1) is excluded — stays as text
    assert 'Drama' in xml
    # Action and Comedy got IDs
    po = (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').read_text(encoding='utf-8')
    assert 'msgid "Action"' in po
    assert 'msgid "Comedy"' in po
    assert 'msgid "Drama"' not in po
