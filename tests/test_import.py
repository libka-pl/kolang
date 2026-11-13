"""`--import FILE|-`: translations from PO or JSON (format from the text, not the name) written in the run (B51)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from conftest import PY

PO_HEAD = 'msgid ""\nmsgstr ""\n"Language: pl\\n"\n\n'


def run(addon: Path, *args: str, stdin: str | None = None) -> tuple[int, str]:
    """Run `python -m kolang ARGS .` in `addon`, return (returncode, stdout+stderr)."""
    res = subprocess.run([str(PY), '-m', 'kolang', '--no-backup-pattern', '-L', 'pl', *args, '.'], cwd=addon,
                         capture_output=True, text=True, input=stdin, encoding='utf-8')
    return res.returncode, res.stdout + res.stderr


def source(addon: Path, code: str) -> Path:
    """Write resources/lib/main.py with `code`, return the path."""
    lib = addon / 'resources' / 'lib'
    lib.mkdir(parents=True, exist_ok=True)
    (lib / 'main.py').write_text(f'from kolang import L\n{code}\n', encoding='utf-8')
    return lib / 'main.py'


def pl(addon: Path) -> str:
    """Text of the pl PO."""
    return (addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po').read_text(encoding='utf-8')


def test_json_stdin_new_text(addon: Path) -> None:
    """A new text gets its ID and the translation from stdin JSON in one run."""
    source(addon, "a = L('Viewer')\nb = L('Owner')")
    rc, out = run(addon, '--import', '-', stdin=json.dumps({'pl': {'Viewer': 'Podgląd', 'Owner': 'Właściciel'}}))
    assert rc == 0, out
    assert 'msgid "Viewer"\nmsgstr "Podgląd"' in pl(addon)
    assert 'msgid "Owner"\nmsgstr "Właściciel"' in pl(addon)
    assert 'imported: 2' in out


def test_po_any_name_replaces_and_unfuzzes(addon: Path, tmp_path: Path) -> None:
    """PO in a file without extension: replaces a translation (`changed`), clears `fuzzy`; JSON in a `.po` is JSON."""
    source(addon, "a = L('Viewer')")
    assert run(addon)[0] == 0
    po = (addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po')
    fuzzy = pl(addon).replace('msgid "Viewer"\nmsgstr ""', '#, fuzzy\nmsgid "Viewer"\nmsgstr "Widz"')
    po.write_text(fuzzy, encoding='utf-8')
    (tmp_path / 'abc').write_text(PO_HEAD + 'msgctxt "#30100"\nmsgid "Viewer"\nmsgstr "Podgląd"\n', encoding='utf-8')
    rc, out = run(addon, '--import', str(tmp_path / 'abc'))
    assert rc == 0, out
    assert '#, fuzzy' not in pl(addon) and 'msgstr "Podgląd"' in pl(addon)
    assert 'changed: 1' in out
    (tmp_path / 'tr.po').write_text('﻿  {"pl": {"Viewer": "Oglądający"}}', encoding='utf-8')
    rc, out = run(addon, '--import', str(tmp_path / 'tr.po'))
    assert rc == 0, out
    assert 'msgstr "Oglądający"' in pl(addon)


def test_not_imported(addon: Path) -> None:
    """Unknown text, an ID with another text, a text in two contexts without ID, the base language: warnings only."""
    source(addon, "a = L('Open', ctx='verb')\nb = L('Open', ctx='adjective')\nc = L('Close')")
    po = (PO_HEAD + 'msgid "Missing"\nmsgstr "Brak"\n\nmsgid "Open"\nmsgstr "Otwórz"\n\n'
          'msgctxt "#30199"\nmsgid "Close"\nmsgstr "Zamknij"\n\n#. context: verb\nmsgid "Open"\nmsgstr "Otwórz"\n')
    rc, out = run(addon, '-L', 'en', '--import', '-', stdin=po)
    assert rc == 0, out
    assert "'Missing' not in PO" in out
    assert "'Open' in 2 entries" in out
    assert "'Close' not #30199 or other context (it is #30102)" in out
    assert 'imported: 1' in out   # `Open` with context `verb`
    assert pl(addon).count('msgstr "Otwórz"') == 1
    rc, out = run(addon, '--import', '-', stdin='{"en": {"Close": "x"}}')
    assert rc == 0 and 'en_GB is the base language, not imported' in out, out


def test_errors_write_nothing(addon: Path) -> None:
    """PO without `Language:`, bad JSON, `[…]`, two stdin: error, sources untouched."""
    main = source(addon, "a = L('Viewer')")
    for args, stdin, msg in [(('--import', '-'), 'msgid "Viewer"\nmsgstr "Podgląd"\n', 'no "Language:"'),
                             (('--import', '-'), '{"pl": {', 'invalid JSON'),
                             (('--import', '-'), '["pl"]', 'JSON must be an object'),
                             (('--import', '-', '--import', '-'), '{}', 'stdin can be read only once')]:
        rc, out = run(addon, *args, stdin=stdin)
        assert rc == 1 and msg in out, out
        assert main.read_text(encoding='utf-8') == "from kolang import L\na = L('Viewer')\n"


def test_plural_check_and_dry_run(addon: Path) -> None:
    """A wrong plural translation is imported with the usual warning; `--dry-run` writes nothing."""
    source(addon, "a = L('{n} file|||{n} files', n=2)")
    stdin = '{"pl": {"{n} file|||{n} files": "{n} plik|||{n} pliki"}}'
    rc, out = run(addon, '--dry-run', '--import', '-', stdin=stdin)
    assert rc == 0, out
    assert 'imported: 1' in out and '2 plural forms, pl_PL needs 3' in out
    assert not (addon / 'resources' / 'language' / 'resource.language.pl_pl').exists()
