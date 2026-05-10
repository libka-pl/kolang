"""H.9: write-side L() comments — fresh, migration, idempotency."""
PO_BASE = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n'


def test_fresh_extraction_adds_comment(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="Movies"/></settings>', encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30100, 'Movies')" in xml
    assert '<setting label="30100"/>' in xml


def test_migration_from_po(addon, kolang_run):
    (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').write_text(
        PO_BASE + 'msgctxt "#30100"\nmsgid "Movies"\nmsgstr ""\n', encoding='utf-8'
    )
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="30100"/></settings>', encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    xml = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30100, 'Movies')" in xml


def test_idempotency(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="Movies"/></settings>', encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    snap1 = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    rc, _ = kolang_run()
    assert rc == 0
    snap2 = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert snap1 == snap2


def test_dashes_in_text_idempotent(addon, kolang_run):
    (addon / 'resources' / 'settings.xml').write_text(
        '<settings><setting label="--- sekcja ---"/></settings>', encoding='utf-8'
    )
    rc, _ = kolang_run()
    assert rc == 0
    snap1 = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "'\\u002d\\u002d\\u002d sekcja \\u002d\\u002d\\u002d'" in snap1
    rc, _ = kolang_run()
    assert rc == 0
    snap2 = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert snap1 == snap2
