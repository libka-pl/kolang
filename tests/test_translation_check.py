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
