"""`.kolang.json` of the add-on is used when PATH are files or `-t` is given (B50), CLI options win over it (B52)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import PY


def run(cwd: Path, *args: str) -> tuple[int, str]:
    """Run `python -m kolang ARGS` in `cwd`, return (returncode, stdout+stderr)."""
    res = subprocess.run([str(PY), '-m', 'kolang', *args], cwd=cwd, capture_output=True, text=True)
    return res.returncode, res.stdout + res.stderr


def setup(addon: Path, **options: object) -> tuple[Path, Path]:
    """Config with en+pl, `id-from` 30500, no backups (+ `options`); main.py and other.py with a label each."""
    conf = {'options': {'addon-id': 't.test', 'id-from': 30500, 'backup-pattern': False, **options},
            'languages': ['en', 'pl'], 'sources': [{'addon': '.'}]}
    (addon / '.kolang.json').write_text(json.dumps(conf), encoding='utf-8')
    lib = addon / 'resources' / 'lib'
    lib.mkdir(parents=True)
    (lib / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    (lib / 'other.py').write_text("from kolang import L\nb = L('Beta')\n", encoding='utf-8')
    return lib / 'main.py', lib / 'other.py'


def pl_po(addon: Path) -> Path:
    """Path of the pl PO."""
    return addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def test_file_path_reads_config(addon: Path) -> None:
    """A file as PATH (no `-t`, run from elsewhere): languages, `id-from`, `backup-pattern` come from the config."""
    main, _ = setup(addon)
    rc, out = run(main.parent, 'main.py')
    assert rc == 0, out
    assert "L(30500, 'Alpha')" in main.read_text(encoding='utf-8')
    assert not main.with_name('main.py~').exists()
    assert pl_po(addon).exists()   # PO of the add-on, not of the current folder
    assert not (main.parent / 'resources').exists()


def test_translation_option_reads_config(addon: Path) -> None:
    """`-t .` with files: the config is read too."""
    main, _ = setup(addon)
    rc, out = run(addon, '-t', '.', 'resources/lib/main.py')
    assert rc == 0, out
    assert "L(30500, 'Alpha')" in main.read_text(encoding='utf-8')
    assert not main.with_name('main.py~').exists()
    assert pl_po(addon).exists()


def test_some_files_keep_obsolete(addon: Path) -> None:
    """Config `obsolete: mark`, some files scanned: other strings stay (warning); `--obsolete mark` marks them."""
    main, other = setup(addon, obsolete='mark')
    assert run(addon, '.')[0] == 0
    rc, out = run(addon, 'resources/lib/main.py')
    assert rc == 0, out
    assert 'Only some files scanned' in out
    assert '#~' not in pl_po(addon).read_text(encoding='utf-8')
    rc, out = run(addon, '--obsolete', 'mark', 'resources/lib/main.py')
    assert rc == 0, out
    assert 'Only some files scanned' not in out
    assert '#~ msgid "Beta"' in pl_po(addon).read_text(encoding='utf-8')


def test_explicit_untracked_file_with_git_only(addon: Path) -> None:
    """Config `git-only`: a file given on the command line is scanned even if git doesn't track it."""
    main, _ = setup(addon, **{'git-only': True})
    subprocess.run(['git', 'init', '-q'], cwd=addon, check=True)
    rc, out = run(addon, 'resources/lib/main.py')
    assert rc == 0, out
    assert "L(30500, 'Alpha')" in main.read_text(encoding='utf-8')


def test_cli_wins_over_config(addon: Path) -> None:
    """`--backup-pattern` on the command line wins over config `backup-pattern: false` (only `id-*` did before)."""
    main, _ = setup(addon)
    rc, out = run(addon, '--backup-pattern', '{}.bak', '.')
    assert rc == 0, out
    assert main.with_name('main.py.bak').exists()
