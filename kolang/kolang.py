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

Author: rysson <robert.kalinowski@sharkbits.com>
License: MIT
Home: https://github.com/kodi-pl/
Python version: 3.8+
"""

from __future__ import annotations
from typing import Literal, overload, TYPE_CHECKING
from pathlib import Path
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
    from typing import Callable, ClassVar


FALLBACK_LOCALE: str = 'en-US'
#: Locale of source texts in `L(id, 'text')`, Kodi returns them if there is no translation.
SOURCE_LOCALE: str = 'en-GB'


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
        #: Current Kodi UI locale (None: not checked yet).
        self._locale: str | None = None

    @property
    def addon(self) -> Addon:
        """Get language addon."""
        if self.id is None:
            return Addon()
        return Addon(self.id)

    def reset(self) -> None:
        """Forget the UI locale if Kodi language has changed."""
        if self._locale is not None and kodi_locale() != self._locale:
            self._locale = None

    def destroy(self) -> None:
        """Destroy addon."""
        self._plurals.clear()
        self._locale = None

    @property
    def locale(self) -> str:
        """Current Kodi UI locale, cached."""
        if self._locale is None:
            self._locale = kodi_locale()
        return self._locale

    def plural(self, locale: str | None = None) -> Callable[[int], int]:
        """Return plural rule (n → form index) for the locale (Kodi UI locale by default), cached."""
        locale = locale or self.locale
        rule = self._plurals.get(locale)
        if rule is None:
            rule = self._plurals[locale] = self._load_plural(locale)
        return rule

    def _po_path(self, locale: str) -> Path | None:
        """Find the addon PO file for the locale: exact `ll_cc`, other folder of the language, `en_gb`."""
        base = Path(self.addon.getAddonInfo('path')) / 'resources' / 'language'
        lang, _, region = locale.lower().partition('-')
        prefix = f'resource.language.{lang}'
        try:
            others = sorted(p.name for p in base.iterdir()
                            if p.name.startswith(prefix) and p.name[len(prefix):][:1] in ('', '_', '@'))
        except OSError:
            others = []
        for name in (f'{prefix}_{region}', *others, 'resource.language.en_gb'):
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

    def get_text(self, string: str, /, *, n: int | None = None, **kwargs) -> str:
        """Get value of already translated label. Useful for number forms."""
        return self._apply_plural(string, n, None, **kwargs)

    def _apply_plural(self, text: str, n: int | None, locale: str | None, /, **kwargs) -> str:
        """Apply plural rule of the locale (UI locale if None) and format with `n` + kwargs."""
        if n is None:
            return text.format(**kwargs) if kwargs else text
        forms = text.split('|||')
        return forms[min(self.plural(locale)(abs(n)), len(forms) - 1)].format(n=n, **kwargs)


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

    @property
    def raw_translations(self) -> dict[int, tuple[str, str]]:
        """Get raw translations [id] = (en, loc), lazy loading."""
        if self._translations is None:
            if addon := self.addon:
                path = Path(addon.getAddonInfo('path')) / 'resources' / 'strings.po'
                try:
                    with open(path, encoding='utf-8') as f:
                        self._translations = {
                            int(mch['id']): (self._join_po_strings(mch['en']),
                                             self._join_po_strings(mch['loc']))
                            for mch in self._rx.finditer(f.read())
                        }
                except IOError:
                    self._translations = {}
            else:
                self._translations = {}
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
        """Get localized label."""
        default = f'#{id}'
        if isinstance(id, str):
            return self.en_to_locale_translations.get(id, default)
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
    """Reset all getters."""
    for getter in _label_getters.values():
        getter.reset()


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


def destroy() -> None:
    """Destroy state of all label getters, they stay registered (module `L` is still the getter of the addon)."""
    for getter in _label_getters.values():
        getter.destroy()
    KodiLabels.destroy_all()
