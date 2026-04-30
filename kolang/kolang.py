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
if TYPE_CHECKING:
    from typing import Sequence, Mapping, ClassVar, Self
    from ast import stmt


FALLBACK_LOCALE: str = 'en-US'


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
        #: Addon instance.
        self.addon: Addon  # set in reset()
        #: Rules for all languages.
        self._rules: Mapping[str, Sequence[stmt]] | None = None
        #: Rule for locale.
        self._rule: Sequence[stmt] | None = None
        #: Current locale.
        self._locale: str | None = None
        self.reset()

    def reset(self) -> None:
        """Recreate addon."""
        self.addon = Addon() if self.id is None else Addon(self.id)
        if self._locale is None or (kodi_locale() != self._locale):
            self._rule = None
            self._locale = None

    def load_rules(self):
        import json
        try:
            from simpleeval import SimpleEval
        except ModuleNotFoundError:
            _log('No simpleeval module', 'warning')
            return {}
        path = Path(__file__).parent.parent / 'resources' / 'language' / 'rules.json'
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except OSError:
            _log(f'Missing language rules {path}')
            return {}
        se = SimpleEval()
        return {k: tuple(se.parse(v) for v in vv) for k, vv in data.get('plural', {}).items()}

    def rules(self, *, locale: str | None = None) -> Sequence[stmt]:
        if self._rule is None:
            if self._rules is None:
                self._rules = self.load_rules()
            if not locale:
                if self._locale is None:
                    self._locale = kodi_locale()
                locale = self._locale
            rules = self._rules.get(locale)
            if rules is None:
                rules = self._rules.get(locale.partition('-')[0], ())
            self._rule = rules
        return self._rule

    @overload
    def __call__(self, id: int, string: str, /, *, n: int | None = None, **kwargs) -> str: ...

    @overload
    def __call__(self, id: int, /, *, n: int | None = None, **kwargs) -> str: ...

    @overload
    def __call__(self, string: str, /, *, n: int | None = None, **kwargs) -> str: ...

    def __call__(self, *args, n: int | None = None, **kwargs) -> str:
        """L(). Get localized string. If there is no ID there string is returned without translation."""
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
        if sid:
            if translated := self.addon.getLocalizedString(sid):
                text = translated
        return self._apply_plural(text, n, **kwargs)

    def get_text(self, string: str, /, *, n: int | None = None, **kwargs) -> str:
        """Get value of already translated label. Useful for number forms."""
        return self._apply_plural(string, n, **kwargs)

    def _apply_plural(self, text: str, n: int | None, **kwargs) -> str:
        """Apply locale's plural rule and format with `n` + kwargs."""
        if n is None:
            return text
        try:
            from simpleeval import SimpleEval
        except ModuleNotFoundError:
            return text
        se = SimpleEval(names={'n': abs(n)})
        forms = text.split('|||')
        for rule, frm in zip(self.rules(), forms):
            if se.eval('', previously_parsed=rule):
                return frm.format(n=n, **kwargs)
        return forms[-1].format(n=n, **kwargs)


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
    _addon: Literal[False] | Addon | None
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
        obj._addon = None
        obj.locale = locale
        # register as singleton for given locale
        KodiLabels._instances[locale] = obj
        return obj

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
        if self._addon is None:
            try:
                loc = self.locale.lower().replace('-', '_')
                self._addon = Addon(f'resource.language.{loc}')
            except RuntimeError:
                self._addon = False
        return self._addon or None

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
