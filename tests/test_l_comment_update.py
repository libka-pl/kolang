"""Stale L() comments must be updated when text is edited.

Regression: previously `_ensure_L_comment` only checked existence and
skipped when any marker for the target was found, leaving stale ID/text
in the comment after `_add_label` resolved a conflict to a new ID.
"""


def write_settings(addon, body):
    (addon / 'resources' / 'settings.xml').write_text(
        f'<settings>\n{body}\n</settings>\n', encoding='utf-8'
    )


def test_edit_comment_text_renames_in_place_when_untranslated(addon, kolang_run, po_path):
    """Edit text → ID is reused (rename) since the old text had no translation."""
    write_settings(addon, '  <setting label="blada"/>')
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30100, 'blada')" in xml
    assert '<setting label="30100"/>' in xml

    # Edit comment text: 'blada' → 'blada-X'.
    xml = xml.replace("'blada'", "'blada-X'", 1)
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')

    rc, out = kolang_run()
    assert rc == 0
    assert 'mismatch' not in out.lower()
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    # Old ID 30100 reused for the new text; XML attr unchanged.
    assert "L[label](30100, 'blada-X')" in xml
    assert '<setting label="30100"/>' in xml
    # PO has the new msgid under the same ID, no orphan.
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "blada-X"' in po
    assert 'msgid "blada"' not in po

    # Idempotent.
    snap = xml
    rc, _ = kolang_run()
    assert rc == 0
    assert (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8') == snap


def test_edit_translated_text_assigns_new_id(addon, kolang_run, po_path):
    """If old text has a translation, rename is refused — new ID generated."""
    write_settings(addon, '  <setting label="blada"/>')
    rc, _ = kolang_run()
    assert rc == 0
    # Translator filled msgstr.
    po = po_path.read_text(encoding='utf-8')
    po = po.replace('msgctxt "#30100"\nmsgid "blada"\nmsgstr ""',
                    'msgctxt "#30100"\nmsgid "blada"\nmsgstr "translated"')
    po_path.write_text(po, encoding='utf-8')

    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    xml = xml.replace("'blada'", "'blada-X'", 1)
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')

    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    # Translation preserved → new ID for the new text.
    assert "L[label](30101, 'blada-X')" in xml
    assert '<setting label="30101"/>' in xml
    po = po_path.read_text(encoding='utf-8')
    assert 'msgid "blada"' in po       # old kept (with its translation)
    assert 'msgid "blada-X"' in po     # new


def test_no_rename_flag_disables_rename(addon, kolang_run):
    """`--no-rename` keeps the old (split) behavior even when safe to rename."""
    write_settings(addon, '  <setting label="blada"/>')
    rc, _ = kolang_run('--no-rename')
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    xml = xml.replace("'blada'", "'blada-X'", 1)
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')

    rc, _ = kolang_run('--no-rename')
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30101, 'blada-X')" in xml
    assert '<setting label="30101"/>' in xml


def test_edit_one_of_three_same_text(addon, kolang_run):
    """Three labels share the same text; editing one comment splits only
    that one to a new ID, comment is refreshed, others are untouched."""
    write_settings(addon,
        '  <setting label="test1"/>\n'
        '  <setting label="test1"/>\n'
        '  <setting label="test1"/>'
    )
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert xml.count("L[label](30100, 'test1')") == 3
    assert xml.count('<setting label="30100"/>') == 3

    # Edit only the first comment: test1 → test2.
    xml = xml.replace("'test1'", "'test2'", 1)
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')

    rc, out = kolang_run()
    assert rc == 0
    assert 'mismatch' not in out.lower()
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    # Edited one got a new ID; other two unchanged.
    assert "L[label](30101, 'test2')" in xml
    assert xml.count("L[label](30100, 'test1')") == 2
    assert xml.count('<setting label="30100"/>') == 2
    assert '<setting label="30101"/>' in xml
    # Stale "L[label](30100, 'test2')" must not exist.
    assert "L[label](30100, 'test2')" not in xml

    # Idempotent.
    snap = xml
    rc, out = kolang_run()
    assert rc == 0
    assert 'mismatch' not in out.lower()
    assert (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8') == snap
