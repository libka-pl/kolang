"""Symlinked source leaving the addon is read-only (B30): scanned, never written; git sees a tracked link as the link."""
from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import run_kolang
from kolang import Translate, _git_clean_files, _git_tracked_files

SKIN_ADDON = ('<addon id="skin.t" name="t" version="1" provider-name="t">\n'
              '  <extension point="xbmc.gui.skin"><res width="1920" height="1080" folder="xml"/></extension>\n</addon>\n')
HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
OVERLAY = '<window>\n  <label>$ADDON[skin.t 31100]</label>\n  <label>Debug only</label>\n</window>\n'


def skin(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Skin `addon/` with `xml/Custom_Overlay.xml` linked to `custom/` outside, 31100 used only there. Return (addon, link target, PO)."""
    addon = tmp_path / 'addon'
    (addon / 'xml').mkdir(parents=True)
    (addon / 'addon.xml').write_text(SKIN_ADDON, encoding='utf-8')
    po = addon / 'language' / 'resource.language.en_gb' / 'strings.po'
    po.parent.mkdir(parents=True)
    po.write_text(HEADER + 'msgctxt "#31100"\nmsgid "Shown"\nmsgstr ""\n', encoding='utf-8')
    (addon / 'xml' / 'Home.xml').write_text('<window>\n  <label>Home text</label>\n</window>\n', encoding='utf-8')
    target = tmp_path / 'custom' / 'Custom_Overlay.xml'
    target.parent.mkdir()
    target.write_text(OVERLAY, encoding='utf-8')
    (addon / 'xml' / 'Custom_Overlay.xml').symlink_to(target)
    return addon, target, po


def test_symlink_outside_not_written(tmp_path: Path) -> None:
    """Link target unchanged, its new text gets no ID (no entry), its ID stays used; own file is written."""
    addon, target, po = skin(tmp_path)
    rc, out = run_kolang(addon, '--no-backup-pattern', '-L', 'en', '--obsolete', 'remove')
    assert rc == 0, out
    assert target.read_text(encoding='utf-8') == OVERLAY
    assert (addon / 'xml' / 'Custom_Overlay.xml').is_symlink()
    assert 'Read-only source' in out and "1 new text(s) not assigned" in out and "'Debug only'" in out, out
    text = po.read_text(encoding='utf-8')
    assert '"Shown"' in text and '#~' not in text      # used only in the read-only file
    assert 'Debug only' not in text                      # neither ID nor ID-less entry
    assert '"Home text"' in text
    assert '$ADDON[skin.t ' in (addon / 'xml' / 'Home.xml').read_text(encoding='utf-8')


def test_check_ignores_read_only(tmp_path: Path) -> None:
    """`--check` doesn't fail on a read-only source (no run could fix it)."""
    addon, target, po = skin(tmp_path)
    (addon / 'xml' / 'Home.xml').write_text('<window/>\n', encoding='utf-8')
    target.write_text('<window>\n  <label>Debug only</label>\n</window>\n', encoding='utf-8')
    rc, out = run_kolang(addon, '--check', '-L', 'en')
    assert 'Custom_Overlay' not in ''.join(line for line in out.splitlines(True) if line.startswith('would change')), out
    assert target.read_text(encoding='utf-8') == '<window>\n  <label>Debug only</label>\n</window>\n'


def test_symlink_inside_written(tmp_path: Path) -> None:
    """Link with target inside the addon is written through (same file)."""
    addon, target, po = skin(tmp_path)
    (addon / 'xml' / 'Custom_Overlay.xml').unlink()
    inner = addon / 'shared' / 'Inner.xml'
    inner.parent.mkdir()
    inner.write_text('<window>\n  <label>Inner text</label>\n</window>\n', encoding='utf-8')
    (addon / 'xml' / 'Inner.xml').symlink_to(Path('..') / 'shared' / 'Inner.xml')
    rc, out = run_kolang(addon, '--no-backup-pattern', '-L', 'en')
    assert rc == 0, out
    assert '$ADDON[skin.t ' in inner.read_text(encoding='utf-8')
    assert 'Read-only' not in out


def test_explicit_file_link_read_only(tmp_path: Path) -> None:
    """Explicitly given file follows the same rule: a link leaving its dir is read-only."""
    target = tmp_path / 'outside' / 'ext.py'
    target.parent.mkdir()
    target.write_text("from kolang import L\nx = L('Outside')\n", encoding='utf-8')
    link = tmp_path / 'lib' / 'ext.py'
    link.parent.mkdir()
    link.symlink_to(target)
    (tmp_path / 'lib' / 'own.py').write_text('x = 1\n', encoding='utf-8')
    trans = Translate(dry_run=True)
    trans.load_input(link)
    trans.load_input(tmp_path / 'lib' / 'own.py')
    assert [f.readonly for f in trans.py_inputs] == [True, False]


def test_git_tracked_link_is_the_link(tmp_path: Path) -> None:
    """Tracked symlink: git sets hold the link path, not its target (backup of the target isn't skipped as 'clean')."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    target = tmp_path / 'outside.xml'
    target.write_text('<window/>\n', encoding='utf-8')
    (repo / 'link.xml').symlink_to(target)
    (repo / 'own.xml').write_text('<window/>\n', encoding='utf-8')
    for args in (('init', '-q'), ('add', '-A'), ('-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'base')):
        subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True)
    root = repo.resolve()
    assert _git_tracked_files(root) == {root / 'link.xml', root / 'own.xml'}
    assert target.resolve() not in _git_clean_files(root)
