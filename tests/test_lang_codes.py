"""Language codes vs Kodi language add-ons (B39): PO folder must be `resource.language.<Kodi ID>`."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from kolang import TranslateBase, parse_lang_arg
from kolang.plural import KODI_LANGUAGES

AR = 'nplurals=6; plural=(n==0 ? 0 : n==1 ? 1 : n==2 ? 2 : n%100>=3 && n%100<=10 ? 3 : n%100>=11 ? 4 : 5);'


@pytest.mark.parametrize('lang', sorted({re.split('[_@]', k)[0] for k in KODI_LANGUAGES}))
def test_short_code_is_kodi_language(lang: str) -> None:
    """Every Kodi language by its short code gives a Kodi language add-on ID."""
    assert TranslateBase.lang_code(lang).lower() in KODI_LANGUAGES


@pytest.mark.parametrize('code, expected', [
    ('he', 'he_IL'), ('iw', 'he_IL'), ('in', 'id_ID'), ('ar', 'ar_SA'), ('nb', 'nb_NO'), ('eo', 'eo'), ('fil', 'fil'),
    ('en', 'en_GB'), ('zh', 'zh_CN'), ('sr', 'sr_RS'), ('fa', 'fa_IR'), ('pt', 'pt_PT'), ('es', 'es_ES'),
    ('pl', 'pl_PL'), ('es_mx', 'es_MX'), ('SR_rs@LATIN', 'sr_RS@latin'), ('xx', 'xx_XX'),
])
def test_lang_code(code: str, expected: str) -> None:
    """Short code → Kodi language, full code only normalized, unknown language guessed."""
    assert TranslateBase.lang_code(code) == expected


@pytest.mark.parametrize('lang, nplurals, name', [
    ('ar_SA', 6, 'Arabic'), ('he_IL', 2, 'Hebrew'), ('es_MX', 2, 'Spanish'), ('zh_TW', 2, 'Chinese'),
    ('en_US', 2, 'English'), ('pt_BR', 2, 'Brazilian Portuguese'), ('sr_RS@latin', 3, 'Serbian'),
    ('szl', 3, 'Silesian'), ('os_OS', 2, 'Ossetian'),
])
def test_plural_and_name_of_kodi_ids(lang: str, nplurals: int, name: str) -> None:
    """Kodi IDs find the rule and name by the full code, then by the language."""
    assert TranslateBase.lang_plural_forms(lang).startswith(f'nplurals={nplurals};')
    assert TranslateBase.lang_name(lang) == name


def test_parse_lang_arg() -> None:
    """CLI accepts variants and codes without region, rejects garbage."""
    assert parse_lang_arg('pl, sr_RS@latin,fil') == ['pl', 'sr_RS@latin', 'fil']
    with pytest.raises(ValueError):
        parse_lang_arg('Polish')


def setup(addon: Path, langs: str) -> Path:
    """Addon config with `langs` (JSON list items) and one label, return the language dir."""
    (addon / '.kolang.json').write_text(
        f'{{"options": {{"addon-id": "t.test"}}, "languages": [{langs}], "sources": [{{"addon": "."}}]}}\n',
        encoding='utf-8')
    (addon / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    return addon / 'resources' / 'language'


def test_new_folders(addon: Path, kolang_run) -> None:
    """Short codes create Kodi folders with the right rule; `@latin` works in the config."""
    lang_dir = setup(addon, '"en", "ar", "he", "sr_RS@latin"')
    rc, out = kolang_run()
    assert rc == 0, out
    expected = {f'resource.language.{c}' for c in ('en_gb', 'ar_sa', 'he_il', 'sr_rs@latin')}
    assert {p.name for p in lang_dir.iterdir()} == expected
    ar = (lang_dir / 'resource.language.ar_sa' / 'strings.po').read_text(encoding='utf-8')
    assert f'"Plural-Forms: {AR}\\n"' in ar and '"Language-Team: Arabic\\n"' in ar and '"Language: ar_SA\\n"' in ar
    assert 'Kodi' not in out, out
    rc, out = kolang_run('--check')                     # folders from disk are recognized again, nothing changes
    assert rc == 0 and 'would change' not in out, out


def test_old_folder_kept_until_renamed(addon: Path, kolang_run) -> None:
    """Old kolang guess `he_he` with translations: warning with `git mv`, it's still written, no `he_il` split."""
    lang_dir = setup(addon, '"en", "he"')
    old = lang_dir / 'resource.language.he_he' / 'strings.po'
    old.parent.mkdir(parents=True)
    old.write_text('msgid ""\nmsgstr ""\n"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n\n'
                   'msgctxt "#30100"\nmsgid "Alpha"\nmsgstr "Alef"\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'git mv resources/language/resource.language.he_he resources/language/resource.language.he_il' in out, out
    assert not (lang_dir / 'resource.language.he_il').exists()
    assert 'msgstr "Alef"' in old.read_text(encoding='utf-8')
    assert out.count('resource.language.he_he') == 2, out    # only the migration warning (git mv names it twice)


def test_foreign_folder_warning(addon: Path, kolang_run) -> None:
    """Folder that isn't a Kodi language and has no configured counterpart: warning, still kept."""
    lang_dir = setup(addon, '"en"')
    (lang_dir / 'resource.language.xx_xx').mkdir(parents=True)
    (lang_dir / 'resource.language.xx_xx' / 'strings.po').write_text('msgid ""\nmsgstr ""\n\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0 and 'resource.language.xx_xx: Kodi has no such language add-on' in out, out
