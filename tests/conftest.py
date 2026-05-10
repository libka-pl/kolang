"""Shared pytest fixtures for kolang tests."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PY = PROJECT_ROOT / '.venv' / 'bin' / 'python'

# Ensure `kolang` is importable from the project source.
sys.path.insert(0, str(PROJECT_ROOT))


ADDON_XML = textwrap.dedent('''
    <?xml version="1.0" encoding="UTF-8"?>
    <addon id="t.test" name="t" version="0.0.1" provider-name="t">
      <extension point="xbmc.python.pluginsource" library="x.py">
        <provides>video</provides>
      </extension>
      <extension point="xbmc.addon.metadata">
        <summary lang="en_GB">test</summary>
      </extension>
    </addon>
''').strip()


@pytest.fixture
def addon(tmp_path: Path):
    """Create a fresh addon skeleton in `tmp_path`. Returns the addon path."""
    (tmp_path / 'resources' / 'language' / 'resource.language.en_gb').mkdir(parents=True)
    (tmp_path / 'addon.xml').write_text(ADDON_XML, encoding='utf-8')
    (tmp_path / '.kolang.json').write_text(
        '{"options": {"addon-id": "t.test", "id-from": 30100}, '
        '"languages": ["en"], "sources": [{"addon": "."}]}\n',
        encoding='utf-8',
    )
    return tmp_path


def run_kolang(addon_dir: Path, *args: str) -> tuple[int, str]:
    """Run `python -m kolang [args] <addon_dir>` from project root.
    Returns (returncode, combined stdout+stderr)."""
    res = subprocess.run(
        [str(PY), '-m', 'kolang', *args, '.'],
        cwd=str(addon_dir), capture_output=True, text=True,
    )
    return res.returncode, res.stdout + res.stderr


@pytest.fixture
def kolang_run(addon):
    """Returns a callable that runs kolang in the addon's dir."""
    def _run(*args: str):
        return run_kolang(addon, *args)
    return _run


@pytest.fixture
def po_path(addon: Path) -> Path:
    return addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po'
