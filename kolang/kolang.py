"""
Simple Kodi localized string getter L().
It's extracrted from libka module.

Example
-------

    from kolang import L

    L('localized string')
    L(31000, 'Already localized string')

    # then run kolang.pyz -L en,pl .
    # the first form will change to the second form

    TITLE = LL(31001, 'Movies')     # lazy: translated when used, follows a Kodi language change
    f'{TITLE}: ...'

Author: rysson <robert.kalinowski@sharkbits.com>
License: MIT
Home: https://github.com/kodi-pl/
Python version: 3.8+
"""

from __future__ import annotations
from typing import Literal, overload, TYPE_CHECKING
from pathlib import Path
from time import monotonic
import re
try:
    from xbmcaddon import Addon
except ModuleNotFoundError:
    # DEBUG & TESTS  (run w/o Kodi)
    if TYPE_CHECKING:
        from xbmcaddon import Addon
    else:
        class Addon:                           # noqa: D101
            def __init__(self, id=None):       # noqa: D107
                pass
            def getLocalizedString(self, v):   # noqa: D102, E301
                return str(v)
            def getAddonInfo(self, key):       # noqa: D102, E301
                return ''                      # addon path: current directory
if TYPE_CHECKING:
    from typing import Any, Callable, ClassVar


FALLBACK_LOCALE: str = 'en-US'
#: Locale of source texts in `L(id, 'text')`, Kodi returns them if there is no translation.
SOURCE_LOCALE: str = 'en-GB'


#: Kodi language is checked at most every N seconds (`LL()` texts, plural rules follow it), `reset()` checks at once.
LANGUAGE_CHECK_INTERVAL: float = 1.0
#: Seconds after a language change when every check starts a new epoch (Kodi reloads addon strings a bit later).
LANGUAGE_SETTLE: float = 2.0

#: Language epoch, the next one on every Kodi language change.
_epoch: int = 0
#: Kodi UI locale of the epoch (None: not checked yet).
_ui_locale: str | None = None
#: Time (`monotonic`) of the next language check.
_next_check: float = 0.0
#: Time (`monotonic`) until the language settles after a change.
_settle_until: float = 0.0

#: Kodi addon folders in the order Kodi scans them (`AddonManager.cpp`).
ADDON_FOLDERS: tuple[str, ...] = ('special://home/addons', 'special://xbmc/addons', 'special://xbmcbin/addons')
#: Language of a locale → language of its Kodi language addon, if it differs (`no-NO` → `resource.language.nb_no`).
LANGUAGE_ALIASES: dict[str, str] = {'no': 'nb'}


def _addon_folders() -> list[Path]:
    """Return existing Kodi addon folders (`ADDON_FOLDERS`), none without Kodi."""
    try:
        from xbmcvfs import translatePath
    except ModuleNotFoundError:
        # DEBUG & TESTS  (run w/o Kodi)
        return []
    return [path for folder in ADDON_FOLDERS if (path := Path(translatePath(folder))).is_dir()]


def _language_folder(locale: str) -> str:
    """Return Kodi language folder (addon) name suffix for the locale: `pl-PL` → `pl_pl`, `en-` → `en`."""
    return locale.lower().replace('-', '_').rstrip('_')


def _check_language(force: bool = False) -> int:
    """Return the language epoch; Kodi language is checked at most every `LANGUAGE_CHECK_INTERVAL` s (`force`: now).

    Kodi changes the language code before it reloads addon strings (a few ms, intermediate codes like `pl-`), so for
    `LANGUAGE_SETTLE` s after a change every check starts a new epoch: a text read too early is read again.
    """
    global _epoch, _ui_locale, _next_check, _settle_until
    now = monotonic()
    if force or now >= _next_check:
        _next_check = now + LANGUAGE_CHECK_INTERVAL
        locale = kodi_locale()
        if locale != _ui_locale:
            if _ui_locale is not None:
                _settle_until = now + LANGUAGE_SETTLE
            _ui_locale = locale
            _epoch += 1
        elif now < _settle_until:
            _epoch += 1
    return _epoch


def _forget_language() -> None:
    """Forget the checked Kodi language, the next check reads it at once and starts a new epoch."""
    global _epoch, _ui_locale, _next_check, _settle_until
    _ui_locale = None
    _next_check = _settle_until = 0.0
    _epoch += 1


def _default_plural(n: int) -> int:
    """Gettext default plural rule: two forms, the first one for 1."""
    return int(n != 1)


def kodi_locale() -> str:
    """Return kodi locale (pl-PL)."""
    try:
        import xbmc
    except ModuleNotFoundError:
        # DEBUG & TESTS  (run w/o Kodi)
        return FALLBACK_LOCALE
    # For locale codes see: https://datahub.io/core/language-codes
    locale: str = xbmc.getLanguage(xbmc.ISO_639_1, True)  # locale: language with region
    if not locale or locale == '-':  # Kodi fack-up, eg. for en-NZ kodi returns "-"
        # incorrect ISO 639/1, contains ISO 3136/1 (country) but lower
        locale = xbmc.getLanguage(xbmc.ISO_639_1)
    elif locale[0] == '-':
        # fix Kodi fackup, xbmc.ISO_639_1 + region without language
        try:
            from const import const
        except ModuleNotFoundError:
            locale = ''
        else:
            if lang := const.global_defs.country_language.get(region := locale[1:].upper()):
                locale = f'{lang}-{region}'
            else:
                locale = ''
    if not locale:
        return FALLBACK_LOCALE
    locale, sep, region = locale.partition('-')
    if sep:
        locale = f'{locale}-{region.upper()}'
    return locale


_label_getters: dict[str | None, LabelGetter] = {}


class LabelGetter:
    """Simple label string getter (like getLocalizedString) for given addon ID."""

    def __init__(self, id: str | None = None) -> None:
        #: Addon ID.
        self.id: str | None = id or None
        #: Plural rule (n → form index) per locale, from `Plural-Forms` of the addon PO.
        self._plurals: dict[str, Callable[[int], int]] = {}

    @property
    def addon(self) -> Addon:
        """Get language addon."""
        if self.id is None:
            return Addon()
        return Addon(self.id)

    def reset(self) -> None:
        """Check the Kodi language now (the module function)."""
        reset()

    def destroy(self) -> None:
        """Destroy addon."""
        self._plurals.clear()

    @property
    def locale(self) -> str:
        """Current Kodi UI locale, checked like `LL()` texts (see `LANGUAGE_CHECK_INTERVAL`)."""
        _check_language()
        return _ui_locale or FALLBACK_LOCALE

    def plural(self, locale: str | None = None) -> Callable[[int], int]:
        """Return plural rule (n → form index) for the locale (Kodi UI locale by default), cached."""
        locale = locale or self.locale
        rule = self._plurals.get(locale)
        if rule is None:
            rule = self._plurals[locale] = self._load_plural(locale)
        return rule

    def _po_path(self, locale: str) -> Path | None:
        """Find the addon PO file for the locale like Kodi loads it: exact `ll_cc` folder, then `en_gb`."""
        base = Path(self.addon.getAddonInfo('path')) / 'resources' / 'language'
        for name in (f'resource.language.{_language_folder(locale)}', 'resource.language.en_gb'):
            if (path := base / name / 'strings.po').is_file():
                return path
        return None

    def _load_plural(self, locale: str) -> Callable[[int], int]:
        """Read `Plural-Forms` from the PO header for the locale, gettext default rule if missing or broken."""
        import gettext
        path = self._po_path(locale)
        if path is None:
            _log(f'No language PO file for {locale!r}, default plural rule', 'warning')
            return _default_plural
        header: list[str] = []
        try:
            with open(path, encoding='utf-8') as f:
                for line in f:
                    if not line.strip() and any(h.startswith('msgstr') for h in header):
                        break
                    header.append(line)
        except OSError as exc:
            _log(f'Can not read {path}: {exc}, default plural rule', 'warning')
            return _default_plural
        values = KodiLabels._join_po_strings(''.join(h for h in header if h.startswith('"') or h.startswith('msgstr')))
        if (mch := re.search(r'Plural-Forms:[^\\]*?plural\s*=\s*([^;\\"]+)', values)) is None:
            _log(f'No Plural-Forms in {path}, default plural rule', 'warning')
            return _default_plural
        try:
            return gettext.c2py(mch[1].strip())
        except (ValueError, SyntaxError, RecursionError) as exc:
            _log(f'Incorrect Plural-Forms in {path}: {exc}, default plural rule', 'error')
            return _default_plural

    @overload
    def __call__(self, id: int, string: str, /, *, n: int | None = None, ctx: str = '', **kwargs) -> str: ...

    @overload
    def __call__(self, id: int, /, *, n: int | None = None, ctx: str = '', **kwargs) -> str: ...

    @overload
    def __call__(self, string: str, /, *, n: int | None = None, ctx: str = '', **kwargs) -> str: ...

    def __call__(self, /, *args, n: int | None = None, ctx: str = '', **kwargs) -> str:
        """L(). Get localized string. If there is no ID there string is returned without translation.

        `ctx` is the text context for kolang only (same text, other meaning → other ID), not a format field.
        """
        sid: int | None
        text: str
        if len(args) == 2:
            sid, text = args
        elif len(args) == 1:
            if isinstance(args[0], int):
                sid, text = args[0], f'#{args[0]}'
            else:
                sid, text = None, args[0]
        else:
            raise TypeError(f'L{args} – incorrect arguments')
        # Kodi returns the English source if there is no translation, then the source plural rule fits
        locale: str | None = SOURCE_LOCALE
        if sid and (translated := self.addon.getLocalizedString(sid)) and translated != text:
            text, locale = translated, None
        return self._apply_plural(text, n, locale, **kwargs)

    @overload
    def lazy(self, id: int, string: str, /, *, n: int | None = None, ctx: str = '', **kwargs) -> LazyLabel: ...

    @overload
    def lazy(self, id: int, /, *, n: int | None = None, ctx: str = '', **kwargs) -> LazyLabel: ...

    @overload
    def lazy(self, string: str, /, *, n: int | None = None, ctx: str = '', **kwargs) -> LazyLabel: ...

    def lazy(self, /, *args, n: int | None = None, ctx: str = '', **kwargs) -> LazyLabel:
        """Return a lazy label, `LL()`: translated when used (`str()`, f-string, call, class attribute)."""
        if not 1 <= len(args) <= 2:
            raise TypeError(f'LL{args} – incorrect arguments')
        if n is not None:
            kwargs['n'] = n
        return LazyLabel(self, args, kwargs)

    def get_text(self, string: str, /, *, n: int | None = None, **kwargs) -> str:
        """Get value of already translated label. Useful for number forms."""
        return self._apply_plural(string, n, None, **kwargs)

    def _apply_plural(self, text: str, n: int | None, locale: str | None, /, **kwargs) -> str:
        """Apply plural rule of the locale (UI locale if None) and format with `n` + kwargs."""
        if n is None:
            return text.format(**kwargs) if kwargs else text
        forms = text.split('|||')
        return forms[min(self.plural(locale)(abs(n)), len(forms) - 1)].format(n=n, **kwargs)


class LazyLabel:
    """Label translated when used, made by `LL()`: `str()`, f-string, call (with format arguments), class attribute.

    The text is kept for the language epoch: a Kodi language change is seen in `LANGUAGE_CHECK_INTERVAL` s, at once
    after `reset()`. As a class attribute it's a descriptor: `obj.title` is `str`, `Class.title` the `LazyLabel`
    (so `Enum` doesn't make it a member, use `enum.member(LL(…))`). Kodi API needs `str`: `ListItem(str(TITLE))`.
    """

    __slots__ = ('getter', 'args', 'kwargs', '_cache')

    getter: LabelGetter
    args: tuple[int | str, ...]
    kwargs: dict[str, Any]
    _cache: tuple[int, str]

    def __init__(self, getter: LabelGetter, args: tuple[int | str, ...], kwargs: dict[str, Any]) -> None:
        """Keep L() arguments: the getter, (id, text) and format arguments (`n=` too)."""
        self.getter = getter
        self.args = args
        self.kwargs = kwargs
        self._cache = (-1, '')

    def __call__(self, **kwargs: Any) -> str:
        """Return the label in the current Kodi language; `kwargs` (format, `n=`) extend those given to `LL()`."""
        if kwargs:
            return self.getter(*self.args, **{**self.kwargs, **kwargs})
        epoch, text = self._cache
        if epoch != (current := _check_language()):
            text = self.getter(*self.args, **self.kwargs)
            self._cache = (current, text)
        return text

    def __str__(self) -> str:
        """Return the label in the current Kodi language."""
        return self()

    def __format__(self, spec: str) -> str:
        """Format the label in the current Kodi language (f-string)."""
        return format(self(), spec)

    def __repr__(self) -> str:
        """Return `LL(…)` with the arguments."""
        args = [repr(a) for a in self.args] + [f'{k}={v!r}' for k, v in self.kwargs.items()]
        return f'LL({", ".join(args)})'

    @overload
    def __get__(self, obj: None, owner: type | None = None) -> LazyLabel: ...  # noqa: D105

    @overload
    def __get__(self, obj: object, owner: type | None = None) -> str: ...  # noqa: D105

    def __get__(self, obj: object | None, owner: type | None = None) -> LazyLabel | str:
        """Descriptor: the label text for an instance, the `LazyLabel` itself for the class."""
        return self if obj is None else self()


class KodiLabels:
    """Main Kodi labels translations."""

    #: kodi strings.po translation parse regex; supports PO line continuation
    #: (msgid/msgstr split across multiple "..." lines).
    _rx: ClassVar[re.Pattern[str]] = re.compile(
        r'\nmsgctxt\s+"#(?P<id>\d+)"\s*'
        r'\nmsgid\s+(?P<en>"(?:\\.|[^"])*"(?:\s*"(?:\\.|[^"])*")*)\s*'
        r'\nmsgstr\s+(?P<loc>"(?:\\.|[^"])*"(?:\s*"(?:\\.|[^"])*")*)'
    )
    #: regex to extract and concatenate "..." parts of a PO value.
    _rx_po_str: ClassVar[re.Pattern[str]] = re.compile(r'"((?:\\.|[^"])*)"')
    #: instances, only one per locale
    _instances: ClassVar[dict[str, KodiLabels]] = {}

    # -- object attributes --
    # all translations [id] = (en, loc)
    _translations: dict[int, tuple[str, str]] | None
    _en_to_locale: dict[str, str] | None
    locale: str

    def __new__(cls, locale: str | None = None) -> KodiLabels:
        """Only one instance per locale, if exists just return, if not - create."""
        if locale is None:
            locale = cls.ui_locale()
        if obj := cls._instances.get(locale):
            return obj
        obj = super().__new__(cls)
        # initialize object
        obj._translations = None
        obj._en_to_locale = None
        obj.locale = locale
        # register as singleton for given locale
        KodiLabels._instances[locale] = obj
        return obj

    @classmethod
    def destroy_all(cls) -> None:
        """Destroy all instances."""
        cls._instances.clear()

    @classmethod
    def _join_po_strings(cls, s: str) -> str:
        """Concatenate consecutive "..." parts of a PO value."""
        return ''.join(cls._rx_po_str.findall(s))

    @classmethod
    def ui_locale(cls) -> str:
        """Get current Kodi UI locale."""
        return kodi_locale()

    @property
    def addon(self) -> Addon | None:
        """Get language addon."""
        try:
            loc = self.locale.lower().replace('-', '_')
            return Addon(f'resource.language.{loc}')
        except RuntimeError:
            return None

    def _po_path(self) -> Path | None:
        """Find `strings.po` of the Kodi language addon for the locale, without `Addon()` (no exception logged).

        Addon folders like Kodi (home first). Language addon: exact `ll_cc`, then the UI language addon if it has
        the same language (`pt-PT` → `pt_br`), then the first `ll_*` alphabetically (`en-US` → `en_gb`).
        Known limits: a disabled addon is read too, an addon in two folders is taken from the first one
        (Kodi takes the higher version).
        """
        folders = _addon_folders()

        def lang_of(locale: str) -> tuple[str, str]:
            """Return (language, `ll_cc` folder suffix) of the locale, with the language alias applied."""
            lang, _, region = _language_folder(locale).partition('_')
            lang = LANGUAGE_ALIASES.get(lang, lang)
            return lang, f'{lang}_{region}' if region else lang

        def find(name: str) -> Path | None:
            """Return `strings.po` of the language addon `name` from the first folder having it."""
            for folder in folders:
                if (path := folder / name / 'resources' / 'strings.po').is_file():
                    return path
            return None

        lang, exact = lang_of(self.locale)
        names = [f'resource.language.{exact}']
        ui_lang, ui_exact = lang_of(kodi_locale())
        if ui_lang == lang:
            names.append(f'resource.language.{ui_exact}')
        names.extend(sorted({path.name for folder in folders for path in folder.glob(f'resource.language.{lang}_*')}))
        for name in names:
            if path := find(name):
                return path
        return None

    @property
    def raw_translations(self) -> dict[int, tuple[str, str]]:
        """Get raw translations [id] = (en, loc), lazy loading."""
        if self._translations is None:
            self._translations = {}
            if path := self._po_path():
                try:
                    with open(path, encoding='utf-8') as f:
                        self._translations = {
                            int(mch['id']): (self._join_po_strings(mch['en']),
                                             self._join_po_strings(mch['loc']))
                            for mch in self._rx.finditer(f.read())
                        }
                except OSError as exc:
                    _log(f'Can not read {path}: {exc}', 'warning')
        return self._translations

    @property
    def en_to_locale_translations(self) -> dict[str, str]:
        """English to localized dict."""
        if self._en_to_locale is None:
            self._en_to_locale = {en: loc or en for en, loc in self.raw_translations.values()}
        return self._en_to_locale

    @property
    def translations(self) -> dict[int, str]:
        """Get translations [id] = loc or en, lazy loading."""
        return {num: loc or en for num, (en, loc) in self.raw_translations.items()}

    def __call__(self, id: int | str) -> str:
        """Get localized label. English text without translation is returned as is, number as `#number`."""
        if isinstance(id, str):
            return self.en_to_locale_translations.get(id, id)
        default = f'#{id}'
        en, loc = self.raw_translations.get(id, (default, default))
        return loc or en

    def label(self, id: int) -> str:
        """Get localized label."""
        en, loc = self.raw_translations.get(id, ('', f'#{id}'))
        return loc or en

    def get(self, id: int | str, default: str | None = None) -> str | None:
        """Get localized label with default."""
        if isinstance(id, str):
            return self.en_to_locale_translations.get(id, default)
        en, loc = self.raw_translations.get(id, (default, default))
        return loc or en

    def __getitem__(self, key: int | str) -> str:
        """Get localized label, dict-like access: KodiLabels('pl-PL')[123] or KodiLabels('pl-PL')['Movies']."""
        if isinstance(key, str):
            return self.en_to_locale_translations[key]
        en, loc = self.raw_translations[key]
        return loc or en


def get_label_getter(id: str | None = None) -> LabelGetter:
    """Return label string getter (like getLocalizedString) for given addon ID."""
    try:
        return _label_getters[id or None]
    except KeyError:
        _label_getters[id or None] = getter = LabelGetter(id)
    return getter


def reset() -> None:
    """Check the Kodi language now, don't wait `LANGUAGE_CHECK_INTERVAL` s.

    E.g. on K22 notification `GUI.OnSkinLoaded` (Kodi reloads the skin after a language change), on a plugin call
    in a reused interpreter (`reuselanguageinvoker`) or in `onInit` of a window.
    """
    _check_language(force=True)


def _log(msg: str, level: Literal['info', 'warning', 'error'] = 'info') -> None:
    """Log message to Kodi log."""
    try:
        import xbmc
        if level == 'error':
            xbmc.log(msg, xbmc.LOGERROR)
        elif level == 'warning':
            xbmc.log(msg, xbmc.LOGWARNING)
        else:  # default is info
            xbmc.log(msg, xbmc.LOGINFO)
    except ModuleNotFoundError:
        # debug and tests
        import sys
        print(msg, file=sys.stderr)


#: Language label getter (translation) for current itself.
L = get_label_getter()
#: Lazy label (translated when used) for current addon itself.
LL = L.lazy


def destroy() -> None:
    """Destroy state of all label getters, they stay registered (module `L` is still the getter of the addon)."""
    for getter in _label_getters.values():
        getter.destroy()
    KodiLabels.destroy_all()
    _forget_language()
