"""Warnings on translations that break at runtime: wrong number of `|||` forms, placeholders differ from msgid."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pl(addon: Path, kolang_run) -> Path:
    """Addon with en+pl, sources with plural and placeholder labels, return pl PO path."""
    (addon / '.kolang.json').write_text('{"options": {"addon-id": "t.test", "id-from": 30100}, '
                                        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n', encoding='utf-8')
    py = addon / 'resources' / 'lib' / 'main.py'
    py.parent.mkdir(parents=True)
    py.write_text("from kolang import L\na = L('file|||files', n=1)\nb = L('Error: {e}', e=1)\nc = L('one|||{n} items', n=2)\n",
                  encoding='utf-8')
    assert kolang_run()[0] == 0
    return addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def translate(pl: Path, **tr: str) -> None:
    """Fill pl translations, `tr` maps msgid (as kwargs name via dict) to msgstr."""
    text = pl.read_text(encoding='utf-8')
    for msgid, msgstr in tr.items():
        text = text.replace(f'msgid "{msgid}"\nmsgstr ""', f'msgid "{msgid}"\nmsgstr "{msgstr}"')
    pl.write_text(text, encoding='utf-8')


def test_correct_translations_no_warning(pl: Path, kolang_run) -> None:
    """Right form count and placeholders (also {n} only in some forms) give no warning."""
    translate(pl, **{'file|||files': 'plik|||pliki|||plików', 'Error: {e}': 'Błąd: {e}', 'one|||{n} items': 'jeden|||{n} elementy|||{n} elementów'})
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'WARNING' not in out, out


def test_wrong_form_count(pl: Path, kolang_run) -> None:
    """Two forms where pl needs three: warning (not error)."""
    translate(pl, **{'file|||files': 'plik|||pliki'})
    rc, out = kolang_run()
    assert rc == 0, out
    assert "'file|||files': 2 plural forms, pl_PL needs 3" in out, out


def test_placeholder_mismatch(pl: Path, kolang_run) -> None:
    """Unknown placeholder in msgstr (KeyError at runtime) and missing one are reported."""
    translate(pl, **{'Error: {e}': 'Błąd: {err}', 'one|||{n} items': 'jeden|||kilka|||wiele'})
    rc, out = kolang_run()
    assert rc == 0, out
    assert "'Error: {e}': placeholders {err} not in msgid, {e} missing" in out, out
    assert "'one|||{n} items': placeholders {n} missing" in out, out


def test_broken_format(pl: Path, kolang_run) -> None:
    """Unbalanced brace in msgstr is reported."""
    translate(pl, **{'Error: {e}': 'Błąd: {e'})
    rc, out = kolang_run()
    assert rc == 0, out
    assert "'Error: {e}': invalid format" in out, out


def test_python_brace_format_flag(pl: Path, kolang_run) -> None:
    """Entries with placeholders get `python-brace-format` (msgfmt -c and PO editors check them), others don't."""
    translate(pl, **{'file|||files': 'plik|||pliki|||plików'})
    assert kolang_run()[0] == 0
    text = pl.read_text(encoding='utf-8')
    assert '#, python-brace-format\nmsgctxt "#30101"\nmsgid "Error: {e}"' in text
    assert '#, python-brace-format\nmsgctxt "#30102"\nmsgid "one|||{n} items"' in text
    assert 'python-brace-format\nmsgctxt "#30100"' not in text
    en = pl.parent.parent / 'resource.language.en_gb' / 'strings.po'
    assert '#, python-brace-format\nmsgctxt "#30101"' in en.read_text(encoding='utf-8')


def test_python_brace_format_follows_text(addon: Path, pl: Path, kolang_run) -> None:
    """Flag is removed when edited text has no placeholders anymore, fuzzy stays."""
    translate(pl, **{'Error: {e}': 'Błąd: {e}'})
    py = addon / 'resources' / 'lib' / 'main.py'
    py.write_text(py.read_text(encoding='utf-8').replace("'Error: {e}', e=1", "'Error'"), encoding='utf-8')
    assert kolang_run()[0] == 0
    text = pl.read_text(encoding='utf-8')
    assert '#, fuzzy\n#| msgid "Error: {e}"\nmsgctxt "#30101"\nmsgid "Error"' in text, text


def test_list_fuzzy_and_untranslated(addon: Path, pl: Path, kolang_run) -> None:
    """`--list fuzzy --list untranslated` prints entries per language (base language has no untranslated list)."""
    translate(pl, **{'file|||files': 'plik|||pliki|||plików', 'Error: {e}': 'Błąd: {e}'})
    py = addon / 'resources' / 'lib' / 'main.py'
    py.write_text(py.read_text(encoding='utf-8').replace("'Error: {e}'", "'Failure: {e}'"), encoding='utf-8')
    rc, out = kolang_run('--dry-run', '--list', 'fuzzy', '--list', 'untranslated')
    assert rc == 0, out
    assert "pl_PL fuzzy #30101 'Failure: {e}' (was 'Error: {e}'): 'Błąd: {e}'" in out, out
    assert "pl_PL untranslated #30102 'one|||{n} items'" in out, out
    assert 'en_GB untranslated' not in out
    assert "'file|||files'" not in out
    assert 'Error: {e}' in pl.read_text(encoding='utf-8')   # dry run: nothing written


def test_plural_form_count_comment(pl: Path, kolang_run) -> None:
    """Plural entries get `#.` comment with the language's form count, others don't; idempotent."""
    assert kolang_run()[0] == 0
    text = pl.read_text(encoding='utf-8')
    assert '#. 3 plural forms separated by |||\nmsgctxt "#30100"\nmsgid "file|||files"' in text
    assert '#. 3 plural forms separated by |||\n#, python-brace-format\nmsgctxt "#30102"' in text
    assert text.count('plural forms') == 2
    en = pl.parent.parent / 'resource.language.en_gb' / 'strings.po'
    assert '#. 2 plural forms separated by |||\nmsgctxt "#30100"' in en.read_text(encoding='utf-8')
    assert kolang_run()[0] == 0
    assert pl.read_text(encoding='utf-8') == text
