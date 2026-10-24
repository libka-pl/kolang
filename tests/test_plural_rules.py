"""Runtime plural forms (B37): rule from `Plural-Forms` of the addon PO (gettext.c2py), English for untranslated."""
from __future__ import annotations

import gettext
from pathlib import Path

import pytest

from kolang import kolang
from kolang.kolang import LabelGetter

PL = 'nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);'
RU = 'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);'
CS = 'nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;'
AR = 'nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);'
EN = 'nplurals=2; plural=(n != 1);'


def write_po(root: Path, folder: str, forms: str | None, *, header: str | None = None, entries: str = '') -> None:
    """Write `resources/language/resource.language.<folder>/strings.po` with the given Plural-Forms."""
    path = root / 'resources' / 'language' / f'resource.language.{folder}' / 'strings.po'
    path.parent.mkdir(parents=True, exist_ok=True)
    if header is None:
        header = '"Language: x\\n"\n' + (f'"Plural-Forms: {forms}\\n"\n' if forms else '')
    path.write_text(f'# comment\nmsgid ""\nmsgstr ""\n{header}\n{entries}', encoding='utf-8')


@pytest.fixture
def getter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LabelGetter:
    """Label getter of an addon in `tmp_path`, UI locale pl-PL, translations from `getter.translations`."""
    translations: dict[int, str] = {}

    class Addon:
        def __init__(self, id=None):
            pass

        def getAddonInfo(self, key):
            return str(tmp_path)

        def getLocalizedString(self, sid):
            return translations.get(sid, '')

    monkeypatch.setattr(kolang, 'Addon', Addon)
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'pl-PL')
    write_po(tmp_path, 'en_gb', EN)
    obj = LabelGetter('test.plural')
    obj.translations = translations
    return obj


def forms(getter: LabelGetter, numbers=(0, 1, 2, 5, 12, 21, 22, 25, 101, 111)) -> list[int]:
    """Form indexes of the UI locale for numbers."""
    return [getter.plural()(n) for n in numbers]


def test_pl_translated(getter: LabelGetter, tmp_path: Path) -> None:
    """Translated text uses the UI language rule (3 forms)."""
    write_po(tmp_path, 'pl_pl', PL)
    getter.translations[30100] = '{n} plik|||{n} pliki|||{n} plików'
    assert [getter(30100, '{n} file|||{n} files', n=n) for n in (1, 2, 5, 12, 22, 25)] == [
        '1 plik', '2 pliki', '5 plików', '12 plików', '22 pliki', '25 plików']


def test_untranslated_uses_source_rule(getter: LabelGetter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kodi returns the English source if there is no translation: English rule, not the UI one (ru 21 → "files")."""
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'ru-RU')
    write_po(tmp_path, 'ru_ru', RU)
    getter.translations[30100] = '{n} file|||{n} files'            # Kodi fallback to en_gb msgid
    assert getter(30100, '{n} file|||{n} files', n=21) == '21 files'
    assert getter(30101, '{n} file|||{n} files', n=1) == '1 file'   # missing ID
    assert getter('{n} file|||{n} files', n=21) == '21 files'       # no ID yet


def test_id_only_and_get_text_use_ui_rule(getter: LabelGetter, tmp_path: Path) -> None:
    """`L(id)` and `get_text()` don't know the source text: UI language rule."""
    write_po(tmp_path, 'pl_pl', PL)
    getter.translations[30100] = 'a|||b|||c'
    assert getter(30100, n=5) == 'c'
    assert getter.get_text('a|||b|||c', n=22) == 'b'


@pytest.mark.parametrize('forms_rule, expected', [
    (PL, [2, 0, 1, 2, 2, 2, 1, 2, 2, 2]),
    (CS, [2, 0, 1, 2, 2, 2, 2, 2, 2, 2]),
    (AR, [0, 1, 2, 3, 4, 4, 4, 4, 5, 4]),
])
def test_rules(getter: LabelGetter, tmp_path: Path, forms_rule: str, expected: list[int]) -> None:
    """Rules from the PO header, the same as gettext."""
    write_po(tmp_path, 'pl_pl', forms_rule)
    assert forms(getter) == expected


def test_too_few_forms(getter: LabelGetter, tmp_path: Path) -> None:
    """Form index past the text forms → the last form."""
    write_po(tmp_path, 'pl_pl', PL)
    assert getter.get_text('one|||many', n=5) == 'many'


def test_other_folder_of_language_ignored(getter: LabelGetter, tmp_path: Path) -> None:
    """No `pl_pl`: Kodi doesn't load other folders of the language (`pl`), so the `en_gb` rule (B39)."""
    write_po(tmp_path, 'pl', PL)
    assert forms(getter, (1, 2, 5)) == [0, 1, 1]


def test_folder_without_region(getter: LabelGetter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kodi language without region (`eo`): its exact folder."""
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'eo')
    write_po(tmp_path, 'eo', 'nplurals=3; plural=(n==1 ? 0 : n==2 ? 1 : 2);')
    assert forms(getter, (1, 2, 5)) == [0, 1, 2]


def test_no_language_folder(getter: LabelGetter, capsys: pytest.CaptureFixture) -> None:
    """No PO for the UI language: `en_gb` rule."""
    assert forms(getter, (0, 1, 2, 5)) == [1, 0, 1, 1]
    assert 'No language PO' not in capsys.readouterr().err


def test_wrapped_header(getter: LabelGetter, tmp_path: Path) -> None:
    """Plural-Forms split by polib into more `"…"` lines."""
    header = ('"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : n%10>=2 && "\n'
              '"n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);\\n"\n')
    write_po(tmp_path, 'pl_pl', None, header=header)
    assert forms(getter, (1, 2, 5, 22)) == [0, 1, 2, 1]


@pytest.mark.parametrize('header', [
    '"Language: pl\\n"\n',                                                                      # no Plural-Forms
    '"Plural-Forms: nplurals=2; plural= n==1 || n%10==1 ? 0 : 1; Can’t be correct\\n"\n',  # `mk` junk, cut at `;`
    '"Plural-Forms: nplurals=2; plural=().__class__;\\n"\n',
])
def test_missing_or_broken_header(getter: LabelGetter, tmp_path: Path, header: str,
                                  capsys: pytest.CaptureFixture) -> None:
    """Missing or rejected rule: gettext default `n != 1` (the `mk` junk after `;` is ignored, its rule works)."""
    write_po(tmp_path, 'pl_pl', None, header=header)
    result = forms(getter, (1, 2, 11))
    if 'n%10==1' in header:
        assert result == [0, 1, 0]
    else:
        assert result == [0, 1, 1]
        assert 'default plural rule' in capsys.readouterr().err


def test_no_po_at_all(tmp_path: Path, getter: LabelGetter, capsys: pytest.CaptureFixture) -> None:
    """No PO files: default rule and a warning."""
    (tmp_path / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po').unlink()
    assert forms(getter, (1, 2)) == [0, 1]
    assert 'No language PO file' in capsys.readouterr().err


def test_cache_and_reset(getter: LabelGetter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule cached per locale, `reset()` follows the Kodi language change."""
    write_po(tmp_path, 'pl_pl', PL)
    assert getter.plural()(5) == 2
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'en-GB')
    assert getter.plural()(5) == 2          # still pl until reset
    getter.reset()
    assert getter.plural()(5) == 1


@pytest.mark.parametrize('rule', [
    '().__class__', "__import__('os')", 'n ** 10 ** 10', 'x == 1', 'n ' + '+ 1 ' * 600, '(' * 200 + 'n' + ')' * 200,
])
def test_c2py_rejects(rule: str) -> None:
    """Guard of the trust assumption: gettext.c2py accepts only `n`, numbers and C operators, limited size."""
    with pytest.raises(ValueError):
        gettext.c2py(rule)


def test_cli_test_plural() -> None:
    """`--test-plural CODE` prints the `plural.py` rule and form indexes (no PATH needed), unknown code fails."""
    import subprocess
    import sys
    res = subprocess.run([sys.executable, '-m', 'kolang', '--test-plural', 'pl'], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert all(f'{n:3} → {i}\n' in res.stdout for n, i in ((1, 0), (2, 1), (5, 2), (22, 1))), res.stdout
    res = subprocess.run([sys.executable, '-m', 'kolang', '--test-plural', 'xx'], capture_output=True, text=True)
    assert res.returncode == 1 and 'Unknown language' in res.stderr
