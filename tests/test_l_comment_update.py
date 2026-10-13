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
    assert '\nmsgid "blada"\n' not in po

    # Idempotent.
    snap = xml
    rc, _ = kolang_run()
    assert rc == 0
    assert (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8') == snap


def edit_translated(addon, kolang_run, po_path, msgstr, *args):
    """Create 30100 'blada' with `msgstr`, edit text to 'blada-X', return (xml, po)."""
    write_settings(addon, '  <setting label="blada"/>')
    rc, _ = kolang_run(*args)
    assert rc == 0
    po = po_path.read_text(encoding='utf-8')
    po = po.replace('msgctxt "#30100"\nmsgid "blada"\nmsgstr ""',
                    f'msgctxt "#30100"\nmsgid "blada"\nmsgstr "{msgstr}"')
    po_path.write_text(po, encoding='utf-8')
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    xml = xml.replace("'blada'", "'blada-X'", 1)
    (addon / 'resources' / 'settings.xml').write_text(xml, encoding='utf-8')
    rc, out = kolang_run(*args)
    assert rc == 0
    assert 'fuzzy: 1' in out or msgstr == 'blada'
    return (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8'), po_path.read_text(encoding='utf-8')


def test_edit_translated_text_keeps_id_fuzzy(addon, kolang_run, po_path):
    """Edited translated text keeps its ID, translation becomes fuzzy with the previous msgid."""
    xml, po = edit_translated(addon, kolang_run, po_path, 'translated')
    assert "L[label](30100, 'blada-X')" in xml
    assert '<setting label="30100"/>' in xml
    assert '#, fuzzy\n#| msgid "blada"\nmsgctxt "#30100"\nmsgid "blada-X"\nmsgstr "translated"' in po
    assert '\nmsgid "blada"\n' not in po


def test_edit_twice_keeps_reviewed_previous_msgid(addon, kolang_run, po_path):
    """Second edit before review keeps `#| msgid` of the text the translation was made for."""
    xml, _ = edit_translated(addon, kolang_run, po_path, 'translated')
    (addon / 'resources' / 'settings.xml').write_text(xml.replace("'blada-X'", "'blada-Y'", 1), encoding='utf-8')
    rc, _ = kolang_run()
    assert rc == 0
    assert '#| msgid "blada"\nmsgctxt "#30100"\nmsgid "blada-Y"' in po_path.read_text(encoding='utf-8')


def test_edit_copied_text_follows(addon, kolang_run, po_path):
    """A msgstr that is a copy of msgid (base language) follows the new text, not fuzzy."""
    _, po = edit_translated(addon, kolang_run, po_path, 'blada')
    assert 'msgctxt "#30100"\nmsgid "blada-X"\nmsgstr "blada-X"' in po
    assert 'fuzzy' not in po


def test_no_rename_translated_copy_is_fuzzy(addon, kolang_run, po_path):
    """`--no-rename`: new ID gets the old translation as fuzzy."""
    xml, po = edit_translated(addon, kolang_run, po_path, 'translated', '--no-rename')
    assert "L[label](30101, 'blada-X')" in xml
    assert '#, fuzzy\n#| msgid "blada"\nmsgctxt "#30101"\nmsgid "blada-X"\nmsgstr "translated"' in po


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
