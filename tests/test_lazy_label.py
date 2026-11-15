"""`LL()` — lazy label: translated when used, follows a Kodi language change (B57)."""
from __future__ import annotations

import enum
from pathlib import Path

import pytest

from kolang import kolang
from kolang.kolang import LabelGetter, LazyLabel


class Kodi:
    """Fake Kodi: UI locale, addon strings per locale, clock; counts string reads."""

    def __init__(self) -> None:
        """Start in English, Polish strings of the addon, clock at 1000 s."""
        self.locale: str = 'en-GB'
        self.strings: dict[str, dict[int, str]] = {
            'pl-PL': {30100: 'Filmy', 30101: '{n} plik|||{n} pliki|||{n} plików'},
        }
        self.now: float = 1000.0
        self.reads: int = 0

    def string(self, sid: int) -> str:
        """Addon string of the current locale ('' without translation, like Kodi)."""
        self.reads += 1
        return self.strings.get(self.locale, {}).get(sid, '')

    def tick(self, seconds: float) -> None:
        """Move the clock."""
        self.now += seconds


PL_PO: str = ('msgid ""\nmsgstr ""\n'
              '"Plural-Forms: nplurals=3; '
              'plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);\\n"\n')


@pytest.fixture
def kodi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Kodi:
    """Fake Kodi for `kolang.py` runtime: addon in `tmp_path` with `pl_pl` plural rule."""
    fake = Kodi()

    class Addon:
        def __init__(self, id=None):
            pass

        def getAddonInfo(self, key):
            return str(tmp_path)

        def getLocalizedString(self, sid):
            return fake.string(sid)

    path = tmp_path / 'resources' / 'language' / 'resource.language.pl_pl'
    path.mkdir(parents=True)
    (path / 'strings.po').write_text(PL_PO, encoding='utf-8')
    monkeypatch.setattr(kolang, 'Addon', Addon)
    monkeypatch.setattr(kolang, 'kodi_locale', lambda: fake.locale)
    monkeypatch.setattr(kolang, 'monotonic', lambda: fake.now)
    return fake


@pytest.fixture
def LL(kodi: Kodi):
    """`LL` of a fresh label getter."""
    return LabelGetter('test.lazy').lazy


def test_str_format_call(kodi: Kodi, LL) -> None:
    """`str()`, f-string (with format spec), call; plural form with `n=` given to `LL()` or to the call."""
    kodi.locale = 'pl-PL'
    title = LL(30100, 'Movies')
    files = LL(30101, '{n} file|||{n} files')
    assert isinstance(title, LazyLabel)
    assert (str(title), f'{title}', f'[{title:>7}]', title()) == ('Filmy', 'Filmy', '[  Filmy]', 'Filmy')
    assert [files(n=n) for n in (1, 2, 5)] == ['1 plik', '2 pliki', '5 plików']
    assert str(LL(30101, '{n} file|||{n} files', n=3)) == '3 pliki'
    assert LL(30101, '{n} file|||{n} files', n=3)(n=22) == '22 pliki'
    assert str(LL('No ID yet')) == 'No ID yet'
    assert repr(LL(30101, 'x', n=3)) == "LL(30101, 'x', n=3)"


def test_wrong_arguments(LL) -> None:
    """Wrong arguments fail at `LL()` (import time), not when used."""
    with pytest.raises(TypeError):
        LL()
    with pytest.raises(TypeError):
        LL(1, 'a', 'b')


def test_kept_for_epoch(kodi: Kodi, LL) -> None:
    """The text is read once per language epoch; with call arguments every time."""
    title = LL(30100, 'Movies')
    assert [str(title) for _ in range(5)] == ['Movies'] * 5
    assert kodi.reads == 1
    title(x=1)
    assert kodi.reads == 2


def test_language_change(kodi: Kodi, LL) -> None:
    """A language change is seen after `LANGUAGE_CHECK_INTERVAL`, not before; `reset()` at once."""
    title = LL(30100, 'Movies')
    assert str(title) == 'Movies'
    kodi.locale = 'pl-PL'
    kodi.tick(0.5)
    assert str(title) == 'Movies'
    kodi.tick(0.6)
    assert str(title) == 'Filmy'
    kodi.locale = 'en-GB'
    assert str(title) == 'Filmy'
    kolang.reset()
    assert str(title) == 'Movies'


def test_settle(kodi: Kodi, LL) -> None:
    """Kodi changes the language before addon strings: a text read in between is read again while settling."""
    title = LL(30100, 'Movies')
    assert str(title) == 'Movies'
    strings, kodi.strings = kodi.strings, {}       # language changed, addon strings not reloaded yet
    kodi.locale = 'pl-PL'
    kolang.reset()
    assert str(title) == 'Movies'
    kodi.strings = strings                         # strings reloaded
    assert str(title) == 'Movies'                  # kept until the next check
    kodi.tick(kolang.LANGUAGE_CHECK_INTERVAL)
    assert str(title) == 'Filmy'                   # settling: new epoch without a language change
    reads = kodi.reads
    kodi.tick(kolang.LANGUAGE_SETTLE + kolang.LANGUAGE_CHECK_INTERVAL)
    assert str(title) == 'Filmy'
    assert str(title) == 'Filmy'
    assert kodi.reads == reads                     # settled: kept, no new epoch


def test_plural_rule_follows_language(kodi: Kodi, LL) -> None:
    """Plural rule follows the Kodi language without `reset()` (it was kept forever before B57)."""
    getter = LabelGetter('test.lazy')
    kodi.strings['en-GB'] = {30101: '{n} file|||{n} files'}
    assert getter(30101, '{n} file|||{n} files', n=5) == '5 files'
    kodi.locale = 'pl-PL'
    kodi.tick(kolang.LANGUAGE_CHECK_INTERVAL)
    assert getter(30101, '{n} file|||{n} files', n=5) == '5 plików'
    assert getter(30101, '{n} file|||{n} files', n=2) == '2 pliki'


def test_descriptor(kodi: Kodi, LL) -> None:
    """Class attribute: `obj.attr` is `str`, `Class.attr` the `LazyLabel`; an instance value replaces it."""
    class Menu:
        title = LL(30100, 'Movies')

    menu = Menu()
    assert type(menu.title) is str and menu.title == 'Movies'
    assert isinstance(Menu.title, LazyLabel)
    kodi.locale = 'pl-PL'
    kolang.reset()
    assert menu.title == 'Filmy'
    menu.title = 'Own'
    assert menu.title == 'Own'


def test_enum(kodi: Kodi, LL) -> None:
    """`Enum` doesn't make a descriptor a member, `enum.member()` does (Python 3.11+)."""
    class Sort(enum.Enum):
        NAME = LL(30100, 'Movies')
        DATE = 2

    assert list(Sort) == [Sort.DATE]
    if hasattr(enum, 'member'):
        class Sort2(enum.Enum):
            NAME = enum.member(LL(30100, 'Movies'))

        assert str(Sort2.NAME.value) == 'Movies'


def test_concat_fails(LL) -> None:
    """No concatenation: a loud `TypeError` instead of a silent snapshot, use f-string."""
    with pytest.raises(TypeError):
        'x ' + LL(30100, 'Movies')


def test_module_ll() -> None:
    """Module `LL` is the lazy L() of the addon itself."""
    assert kolang.LL.__self__ is kolang.L
