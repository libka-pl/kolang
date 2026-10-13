"""Only changed files are written; backup only if git can't restore the file; warning if backup isn't ignored."""
from __future__ import annotations

import subprocess
from pathlib import Path


def git(addon: Path, *args: str) -> None:
    """Run git in addon dir."""
    subprocess.run(['git', *args], cwd=addon, check=True, capture_output=True)


def sources(addon: Path) -> tuple[Path, Path]:
    """Write main.py (with label) and other.py (no label), return paths."""
    lib = addon / 'resources' / 'lib'
    lib.mkdir(parents=True)
    (lib / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    (lib / 'other.py').write_text('x = 1\n', encoding='utf-8')
    return lib / 'main.py', lib / 'other.py'


def test_unchanged_not_written(addon: Path, kolang_run) -> None:
    """File without changes keeps mtime and gets no backup, changed one gets a backup (no git)."""
    main, other = sources(addon)
    mtime = other.stat().st_mtime_ns
    assert kolang_run()[0] == 0
    assert other.stat().st_mtime_ns == mtime
    assert not other.with_name('other.py~').exists()
    assert main.with_name('main.py~').exists()
    main.with_name('main.py~').unlink()
    mtime = main.stat().st_mtime_ns
    assert kolang_run()[0] == 0   # nothing to change now
    assert main.stat().st_mtime_ns == mtime
    assert not main.with_name('main.py~').exists()


def test_git_backup_policy(addon: Path, kolang_run) -> None:
    """Tracked clean file: no backup; tracked with local changes or untracked: backup and warning (not ignored)."""
    main, other = sources(addon)
    git(addon, 'init', '-q')
    git(addon, 'add', '-A')
    git(addon, '-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'base')
    other.write_text("from kolang import L\nb = L('Beta')\n", encoding='utf-8')     # tracked, changed
    new = main.with_name('new.py')
    new.write_text("from kolang import L\nc = L('Gamma')\n", encoding='utf-8')     # untracked
    rc, out = kolang_run()
    assert rc == 0, out
    assert "L(301" in main.read_text(encoding='utf-8')   # ID inserted, no backup (git has it)
    assert not main.with_name('main.py~').exists()
    assert other.with_name('other.py~').exists()
    assert new.with_name('new.py~').exists()
    assert out.count('is not ignored by git') == 1, out


def test_git_ignored_backup_no_warning(addon: Path, kolang_run) -> None:
    """No warning if backups are ignored."""
    sources(addon)
    git(addon, 'init', '-q')
    (addon / '.gitignore').write_text('*~\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'not ignored' not in out
