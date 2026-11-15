"""`KodiLabels`: Kodi language addon found by folders, untranslated text returned as is (B56)."""
from __future__ import annotations

from pathlib import Path

import pytest

from kolang import kolang
from kolang.kolang import KodiLabels


PO: str = '''msgid ""
msgstr ""

msgctxt "#20373"
msgid "Season"
msgstr "{season}"

msgctxt "#20359"
msgid "Episode"
msgstr ""
'''


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Create two Kodi addon folders: home and system; UI locale `pl-PL`, fresh `KodiLabels` instances."""
    dirs = [tmp_path / 'home', tmp_path / 'xbmc']
    for path in dirs:
        path.mkdir()
    monkeypatch.setattr(kolang, '_addon_folders', lambda: dirs)
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'pl-PL')
    KodiLabels.destroy_all()
    yield dirs
    KodiLabels.destroy_all()


def add_language(folder: Path, name: str, season: str) -> None:
    """Create language addon `resource.language.<name>` with the translation of "Season"."""
    path = folder / f'resource.language.{name}' / 'resources'
    path.mkdir(parents=True)
    (path / 'strings.po').write_text(PO.format(season=season), encoding='utf-8')


def test_no_language_addon(folders: list[Path]) -> None:
    """No language addon: English text as is, a number as `#number`."""
    labels = KodiLabels('de-DE')
    assert labels('Season') == 'Season'
    assert labels(20373) == '#20373'
    assert labels.get('Season') is None


def test_no_kodi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without Kodi (no `xbmcvfs`) there are no addon folders, English text as is."""
    KodiLabels.destroy_all()
    assert kolang._addon_folders() == []
    assert KodiLabels('de-DE')('Season') == 'Season'
    KodiLabels.destroy_all()


def test_addon_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kodi addon folders from `xbmcvfs.translatePath`, in Kodi order, missing ones skipped."""
    import sys
    import types
    paths = {'special://home/addons': tmp_path / 'home', 'special://xbmc/addons': tmp_path / 'xbmc',
             'special://xbmcbin/addons': tmp_path / 'xbmcbin'}
    paths['special://home/addons'].mkdir()
    paths['special://xbmcbin/addons'].mkdir()
    monkeypatch.setitem(sys.modules, 'xbmcvfs', types.SimpleNamespace(translatePath=lambda p: str(paths[p])))
    assert kolang._addon_folders() == [tmp_path / 'home', tmp_path / 'xbmcbin']


def test_exact_wins(folders: list[Path]) -> None:
    """Exact `ll_cc` addon wins over the UI and alphabetical one, also when it is in the system folder."""
    add_language(folders[0], 'pt_br', 'Temporada BR')
    add_language(folders[1], 'pt_pt', 'Temporada PT')
    assert KodiLabels('pt-PT')('Season') == 'Temporada PT'


def test_ui_language_before_alphabetical(folders: list[Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `ll_cc` the UI language addon of the same language goes before the first one alphabetically."""
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: 'pt-BR')
    add_language(folders[0], 'pt_ao', 'Temporada AO')
    add_language(folders[0], 'pt_br', 'Temporada BR')
    assert KodiLabels('pt-PT')('Season') == 'Temporada BR'


def test_alphabetical(folders: list[Path]) -> None:
    """Without `ll_cc` and UI language of another language: the first `ll_*` alphabetically, from any folder."""
    add_language(folders[0], 'pt_br', 'Temporada BR')
    add_language(folders[1], 'pt_ao', 'Temporada AO')
    assert KodiLabels('pt-PT')('Season') == 'Temporada AO'


def test_english_us(folders: list[Path]) -> None:
    """`en-US` without `en_us` reads built-in `en_gb` (empty `msgstr` → English text)."""
    add_language(folders[1], 'en_gb', '')
    labels = KodiLabels('en-US')
    assert labels('Season') == 'Season'
    assert labels(20373) == 'Season'
    assert labels('Episode') == 'Episode'


def test_norwegian_alias(folders: list[Path]) -> None:
    """`no-NO` is Kodi `nb_no`."""
    add_language(folders[0], 'nb_no', 'Sesong')
    assert KodiLabels('no-NO')('Season') == 'Sesong'


def test_locale_without_region(folders: list[Path]) -> None:
    """K21 locale without region (`en-`) is the language `en`."""
    add_language(folders[1], 'en_gb', '')
    add_language(folders[0], 'de_de', 'Staffel')
    assert KodiLabels('en-')._po_path() == folders[1] / 'resource.language.en_gb' / 'resources' / 'strings.po'


def test_home_before_system(folders: list[Path]) -> None:
    """The same language addon in two folders: home folder first."""
    add_language(folders[0], 'pl_pl', 'Sezon (home)')
    add_language(folders[1], 'pl_pl', 'Sezon')
    assert KodiLabels('pl-PL')('Season') == 'Sezon (home)'
