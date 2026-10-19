"""B31: `max` policy fills gaps when the top of the range is full, readable error, `--compact-ids` renumbering."""
from __future__ import annotations

import subprocess
from pathlib import Path

CONF = ('{"options": {"addon-id": "t.test", "id-from": 30100, "id-max": 30120}, '
        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n')
SOURCE = ("from kolang import L\n"
          "a = L(30100, 'Alpha')\n"
          "b = L(30105, 'Beta')\n"
          "c = L(30110, 'Gamma', ctx='verb')\n"
          "p = getLocalizedString(30103)\n")


def git(addon: Path, *args: str) -> None:
    """Run git in addon dir."""
    subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=addon, check=True, capture_output=True)


def commit(addon: Path) -> None:
    """Commit everything (git restores it, `--compact-ids` may run)."""
    if not (addon / '.git').exists():
        git(addon, 'init', '-q')
    git(addon, 'add', '-A')
    git(addon, 'commit', '-qm', 'x', '--allow-empty')


def pl_po(addon: Path) -> Path:
    """Path of the pl PO file."""
    return addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def setup(addon: Path, kolang_run, source: str = SOURCE) -> Path:
    """Write config, python source (gaps between IDs) and PO (pinned 30103, translations), run kolang. Return source."""
    (addon / '.kolang.json').write_text(CONF, encoding='utf-8')
    py = addon / 'main.py'
    py.write_text(source, encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern')
    assert rc == 0, out
    for path in (addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po', pl_po(addon)):
        path.write_text(path.read_text(encoding='utf-8') + '\nmsgctxt "#30103"\nmsgid "Pinned"\nmsgstr ""\n', encoding='utf-8')
    pl = pl_po(addon)
    text = pl.read_text(encoding='utf-8')
    for src, tr in (('Beta', 'Beta-pl'), ('Gamma', 'Gamma-pl'), ('Pinned', 'Przypięty')):
        text = text.replace(f'msgid "{src}"\nmsgstr ""', f'msgid "{src}"\nmsgstr "{tr}"')
    pl.write_text(text, encoding='utf-8')
    return py


def test_max_policy_fills_gaps(addon: Path, kolang_run) -> None:
    """Top of the range used: new text gets the lowest gap, with a warning."""
    py = setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nz = L(30120, 'Top')\nn = L('New')\n")
    assert "n = L(30101, 'New')" in py.read_text(encoding='utf-8')
    py.write_text(py.read_text(encoding='utf-8') + "m = L('More')\n", encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern')
    assert rc == 0, out
    assert "m = L(30102, 'More')" in py.read_text(encoding='utf-8')
    assert 'new IDs fill gaps from #30100' in out, out


def test_no_free_id_error(addon: Path, kolang_run) -> None:
    """Range really full: error with hint, no traceback, nothing written."""
    (addon / '.kolang.json').write_text(CONF.replace('"id-max": 30120', '"id-max": 30101'), encoding='utf-8')
    py = addon / 'main.py'
    py.write_text("from kolang import L\na = L(30100, 'A')\nb = L(30101, 'B')\nc = L('C')\n", encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern')
    assert rc == 1 and 'No free label ID in 30100-30101' in out and '--compact-ids' in out, out
    assert 'Traceback' not in out
    assert "c = L('C')" in py.read_text(encoding='utf-8')


def test_compact_ids(addon: Path, kolang_run) -> None:
    """IDs renumbered in order, translations move along, ID used by number stays, new text after; second run no change."""
    py = setup(addon, kolang_run, SOURCE + "n = L('New')\n")
    (addon / 'resources' / 'settings.xml').write_text('<settings>\n  <setting label="30112"/>\n'
                                                      '  <!-- L[label](30115, \'Delta\') -->\n  <setting label="30115"/>\n'
                                                      '</settings>\n', encoding='utf-8')
    rc, out = kolang_run('--no-backup-pattern')
    assert rc == 0, out
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 1 and 'commit first' in out, out          # not in git
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 0, out
    # 30103 (getLocalizedString) and 30112 (settings number without L()) stay, the rest in ID order around them:
    # Alpha 30100, Beta 30105, Gamma 30110, New 30111 (got at the first run), Delta 30115
    assert py.read_text(encoding='utf-8') == ("from kolang import L\n"
                                              "a = L(30100, 'Alpha')\n"
                                              "b = L(30101, 'Beta')\n"
                                              "c = L(30102, 'Gamma', ctx='verb')\n"
                                              "p = getLocalizedString(30103)\n"
                                              "n = L(30104, 'New')\n")
    settings = (addon / 'resources' / 'settings.xml').read_text(encoding='utf-8')
    assert "L[label](30105, 'Delta')" in settings and 'label="30105"' in settings and 'label="30112"' in settings
    text = pl_po(addon).read_text(encoding='utf-8')
    assert 'msgctxt "#30101"\nmsgid "Beta"\nmsgstr "Beta-pl"' in text
    assert '#. context: verb\nmsgctxt "#30102"\nmsgid "Gamma"\nmsgstr "Gamma-pl"' in text
    assert 'msgctxt "#30103"\nmsgid "Pinned"\nmsgstr "Przypięty"' in text
    assert '"#30110"' not in text and '"#30111"' not in text and '"#30115"' not in text
    commit(addon)
    before = py.read_text(encoding='utf-8'), text
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 0, out
    assert (py.read_text(encoding='utf-8'), pl_po(addon).read_text(encoding='utf-8')) == before


def test_compact_unused(addon: Path, kolang_run) -> None:
    """Unused PO entry: after used IDs (keep), removed with `--obsolete remove`."""
    py = setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nb = L(30105, 'Beta')\nc = L(30110, 'Gamma')\n")
    py.write_text("from kolang import L\na = L(30100, 'Alpha')\nc = L(30110, 'Gamma')\n", encoding='utf-8')   # Beta unused
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids', '--dry-run')
    assert rc == 0, out
    # used first (Gamma), then unused in ID order (Pinned only in PO, Beta)
    assert ' move id: 30110 → 30101' in out and ' move id: 30103 → 30102' in out and ' move id: 30105 → 30103' in out, out
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 0, out
    text = pl_po(addon).read_text(encoding='utf-8')      # chain: new 30103 is the old ID of Pinned
    assert 'msgctxt "#30102"\nmsgid "Pinned"\nmsgstr "Przypięty"' in text
    assert 'msgctxt "#30103"\nmsgid "Beta"\nmsgstr "Beta-pl"' in text
    assert text.count('msgctxt "#30103"') == 1 and '"#30105"' not in text and '"#30110"' not in text
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids', '--obsolete', 'remove')
    assert rc == 0, out
    text = pl_po(addon).read_text(encoding='utf-8')
    assert 'Beta' not in text and 'Pinned' not in text and 'msgctxt "#30101"\nmsgid "Gamma"\nmsgstr "Gamma-pl"' in text


def test_addon_xml_label_is_reference(addon: Path, kolang_run) -> None:
    """`<label>N</label>` in addon.xml (context menu) is a numeric reference: kept, not obsolete, not compacted."""
    xml = addon / 'addon.xml'
    xml.write_text(xml.read_text(encoding='utf-8').replace(
        '</addon>', '<extension point="kodi.context.item"><menu><item library="c.py"><label>30105</label></item></menu></extension>\n</addon>'),
        encoding='utf-8')
    py = setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nb = L(30105, 'Beta')\n")
    py.write_text("from kolang import L\na = L(30100, 'Alpha')\n", encoding='utf-8')
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids', '--obsolete', 'remove')
    assert rc == 0, out
    assert 'msgctxt "#30105"\nmsgid "Beta"\nmsgstr "Beta-pl"' in pl_po(addon).read_text(encoding='utf-8')


def test_compact_new_text_takes_freed_id(addon: Path, kolang_run) -> None:
    """New text in the same run gets an ID freed by the compaction: both entries stay, translation follows its text."""
    py = setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nb = L(30102, 'Beta')\n")
    py.write_text(py.read_text(encoding='utf-8') + "n = L('New')\n", encoding='utf-8')
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids', '--obsolete', 'remove')
    assert rc == 0, out
    assert py.read_text(encoding='utf-8').endswith("b = L(30101, 'Beta')\nn = L(30102, 'New')\n")
    text = pl_po(addon).read_text(encoding='utf-8')
    assert 'msgctxt "#30101"\nmsgid "Beta"\nmsgstr "Beta-pl"' in text
    assert 'msgctxt "#30102"\nmsgid "New"\nmsgstr ""' in text


def test_compact_rewrites_xml_number(addon: Path, kolang_run) -> None:
    """`label="N"` of a known ID (node attached, gets the `L()` comment) is rewritten, not pinned; one run is enough."""
    setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nb = L(30105, 'Beta')\n")
    settings = addon / 'resources' / 'settings.xml'
    settings.write_text('<settings>\n  <setting label="30105"/>\n</settings>\n', encoding='utf-8')
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 0, out
    assert "L[label](30101, 'Beta')" in settings.read_text(encoding='utf-8') and 'label="30101"' in settings.read_text(encoding='utf-8')
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids')
    assert rc == 0 and 'moved' not in out, out


def test_localize_in_text_is_reference(addon: Path, kolang_run) -> None:
    """`$LOCALIZE[N]` inside a used text keeps N in place (Kodi resolves it by number)."""
    setup(addon, kolang_run, "from kolang import L\na = L(30100, 'Alpha')\nb = L(30105, 'Beta')\n"
                             "c = L(30110, 'Speed: $LOCALIZE[30105]')\n")
    commit(addon)
    rc, out = kolang_run('--no-backup-pattern', '--compact-ids', '--dry-run')
    assert rc == 0, out
    assert 'move id: 30105' not in out and ' move id: 30110 → 30101' in out, out
