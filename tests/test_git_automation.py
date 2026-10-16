"""`--check` and `--git-setup` (B20): CI exit code, merge driver + post-merge hook on the default branch only."""
from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import run_kolang
from test_merge_po import git


def test_check(addon: Path, kolang_run, po_path: Path) -> None:
    """`--check` writes nothing, lists files and exits 1 when something would change, 0 when in sync."""
    py = addon / 'main.py'
    py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    rc, out = kolang_run('--check')
    assert rc == 1, out
    assert 'would change:' in out and 'main.py' in out and 'strings.po' in out, out
    assert "L('Alpha')" in py.read_text(encoding='utf-8') and not po_path.exists()
    assert kolang_run()[0] == 0
    rc, out = kolang_run('--check')
    assert rc == 0, out
    assert 'would change' not in out


def test_git_setup_and_hook(addon: Path) -> None:
    """Setup writes .gitattributes, driver and hook; the hook assigns IDs after merge on main, not on a feature branch."""
    py = addon / 'main.py'
    git(addon, 'init', '-q', '-b', 'main')
    git(addon, 'config', 'user.email', 't@t')
    git(addon, 'config', 'user.name', 't')
    py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    assert run_kolang(addon)[0] == 0
    rc, out = run_kolang(addon, '--git-setup')
    assert rc == 0, out
    assert 'strings.po merge=kolang' in (addon / '.gitattributes').read_text(encoding='utf-8')
    assert '--merge-po %O %A %B' in git(addon, 'config', 'merge.kolang.driver')
    hook = addon / '.git' / 'hooks' / 'post-merge'
    assert 'kolang post-merge hook' in hook.read_text(encoding='utf-8')
    git(addon, 'add', '-A')
    git(addon, 'commit', '-qm', 'base')

    git(addon, 'checkout', '-qb', 'feat')
    py.write_text("from kolang import L\na = L(30100, 'Alpha')\nb = L('Beta')\n", encoding='utf-8')   # text without ID
    git(addon, 'commit', '-qam', 'feat')
    git(addon, 'checkout', '-q', 'main')
    (addon / 'other.py').write_text("x = 1\n", encoding='utf-8')
    git(addon, 'add', '-A')
    git(addon, 'commit', '-qm', 'main')

    git(addon, 'checkout', '-q', 'feat')
    git(addon, 'merge', '-q', '-m', 'main into feat', 'main')
    assert "b = L('Beta')" in py.read_text(encoding='utf-8')               # feature branch: hook does nothing

    git(addon, 'checkout', '-q', 'main')
    res = subprocess.run(['git', 'merge', '-m', 'feat into main', 'feat'], cwd=addon, capture_output=True, text=True, check=True)
    out = res.stdout + res.stderr                                         # hook output goes to stderr
    assert "b = L(30101, 'Beta')" in py.read_text(encoding='utf-8')       # default branch: IDs assigned
    assert 'commit the result' in out, out

    rc, out = run_kolang(addon, '--git-setup')                            # again: own hook is rewritten, no dup
    assert rc == 0, out
    assert (addon / '.gitattributes').read_text(encoding='utf-8').count('merge=kolang') == 1
