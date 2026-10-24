"""`--generate-kolang-py` (B37): new file, up to date check, overwrite with backup unless git restores it."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from conftest import PROJECT_ROOT

HELPER = (PROJECT_ROOT / 'kolang' / 'kolang.py').read_text(encoding='utf-8')


def run_kolang(target: Path, *args: str) -> tuple[int, str]:
    """Run kolang from the project root (`python -m kolang` in `target` would import the generated `kolang.py`)."""
    res = subprocess.run([sys.executable, '-m', 'kolang', *args, str(target)], cwd=str(PROJECT_ROOT),
                         capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def test_generate(tmp_path: Path) -> None:
    """New file, second run is up to date, changed file is overwritten with `kolang.py~` backup."""
    target = tmp_path / 'kolang.py'
    assert run_kolang(tmp_path, '--generate-kolang-py')[0] == 0
    assert target.read_text(encoding='utf-8') == HELPER
    rc, out = run_kolang(tmp_path, '--generate-kolang-py')
    assert rc == 0 and 'up to date' in out, out
    target.write_text('# old\n', encoding='utf-8')
    rc, out = run_kolang(tmp_path, '--generate-kolang-py')
    assert rc == 0 and 'updated' in out, out
    assert target.read_text(encoding='utf-8') == HELPER
    assert (tmp_path / 'kolang.py~').read_text(encoding='utf-8') == '# old\n'


def test_generate_git_clean_no_backup(tmp_path: Path) -> None:
    """Changed file committed in git: overwritten without backup (git restores it)."""
    target = tmp_path / 'kolang.py'
    target.write_text('# old\n', encoding='utf-8')
    git = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-C', str(tmp_path)]
    subprocess.run([*git, 'init', '-q'], check=True)
    subprocess.run([*git, 'add', 'kolang.py'], check=True)
    subprocess.run([*git, 'commit', '-qm', 'old'], check=True)
    rc, out = run_kolang(tmp_path, '--generate-kolang-py')
    assert rc == 0, out
    assert target.read_text(encoding='utf-8') == HELPER
    assert not (tmp_path / 'kolang.py~').exists()
