"""pyz bootstrap: lxml loaded from the private cache when the interpreter has none (no network)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import zipapp
from pathlib import Path

import lxml

from conftest import PROJECT_ROOT


def build_pyz(tmp_path: Path) -> Path:
    """Build the pyz like Makefile does."""
    src = tmp_path / 'build'
    shutil.copytree(PROJECT_ROOT / 'kolang', src / 'kolang', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy(PROJECT_ROOT / 'kolang' / '__main__.py', src)
    pyz = tmp_path / 'kolang.pyz'
    zipapp.create_archive(src, pyz)
    return pyz


def test_lxml_from_cache(tmp_path: Path) -> None:
    """`python -S` (no site-packages, no lxml) runs the pyz with lxml from the cache, nothing is installed."""
    pyz = build_pyz(tmp_path)
    cache = tmp_path / 'cache'
    gil = 't' if sysconfig.get_config_var('Py_GIL_DISABLED') else ''
    target = cache / 'kolang' / f'py{sys.version_info[0]}{sys.version_info[1]}{gil}-{sysconfig.get_platform()}'
    shutil.copytree(Path(lxml.__file__).parent, target / 'lxml')
    env = {**os.environ, 'XDG_CACHE_HOME': str(cache), 'LOCALAPPDATA': str(cache)}
    res = subprocess.run([sys.executable, '-S', str(pyz), '--version'], env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert 'installing' not in res.stderr
    assert res.stdout.strip()
