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
"""

from __future__ import annotations
from typing import overload, TYPE_CHECKING
from typing import Literal
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
    from collections.abc import Sequence, Mapping
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
            with open(path) as f:
                data = json.load(f)
        except OSError:
            _log(f'Missing laguage rules {path}')
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
                sid, text = args[0], ''
            else:
                sid, text = None, args[0]
        else:
            raise TypeError(f'L{args} – incorrect arguments')
        if sid:
            translated = self.addon.getLocalizedString(sid)
            if translated:
                text = translated
        if n is None:
            return text
        try:
            from simpleeval import SimpleEval
        except ModuleNotFoundError:
            return text
        else:
            se = SimpleEval(names={'n': abs(n)})
            forms = text.split('|||')
            for rule, frm in zip(self.rules(), forms):
                if se.eval('', previously_parsed=rule):
                    return frm.format(n=n, **kwargs)
            else:
                return forms[-1].format(n=n, **kwargs)

    def get_text(self, string: str, /, *, n: int | None = None, **kwargs) -> str:
        """Get value of already translated label. Useful for number forms."""
        text = string
        if n is None:
            return text
        try:
            from simpleeval import SimpleEval
        except ModuleNotFoundError:
            return text
        else:
            se = SimpleEval(names={'n': abs(n)})
            forms = text.split('|||')
            for rule, frm in zip(self.rules(), forms):
                if se.eval('', previously_parsed=rule):
                    return frm.format(n=n, **kwargs)
            else:
                return forms[-1].format(n=n, **kwargs)


class KodiLabels:
    """Main Kodi labels translations."""

    # kodi strings.po translation parse regex; supports PO line continuation
    # (msgid/msgstr split across multiple "..." lines).
    _rx = re.compile(
        r'\nmsgctxt\s+"#(?P<id>\d+)"\s*'
        r'\nmsgid\s+(?P<en>"(?:\\.|[^"])*"(?:\s*"(?:\\.|[^"])*")*)\s*'
        r'\nmsgstr\s+(?P<loc>"(?:\\.|[^"])*"(?:\s*"(?:\\.|[^"])*")*)'
    )
    _rx_po_str = re.compile(r'"((?:\\.|[^"])*)"')

    @classmethod
    def _join_po_strings(cls, s: str) -> str:
        """Concatenate consecutive "..." parts of a PO value."""
        return ''.join(cls._rx_po_str.findall(s))

    def __init__(self, locale: str | None = None) -> None:
        if locale is None:
            locale = self.ui_locale()
        self._translations: dict[int, str] | None = None
        self._addon: Literal[False] | Addon | None = None
        self.locale: str = locale

    @classmethod
    def ui_locale(cls) -> str:
        """Get current Kodi UI locale."""
        return kodi_locale()

    def set_locale(self, locale: str | None = None) -> None:
        """Set locale (UI language change)."""
        if locale is None:
            locale = self.ui_locale()
        if locale != self.locale:
            self._translations = None
            self._addon = None
            self.locale = locale

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
    def translations(self) -> dict[int, str]:
        """Get translations, lazy loading."""
        if self._translations is None:
            if addon := self.addon:
                path = Path(addon.getAddonInfo('path')) / 'resources' / 'strings.po'
                try:
                    with open(path, encoding='utf-8') as f:
                        self._translations = {
                            int(mch['id']): self._join_po_strings(mch['loc']) or self._join_po_strings(mch['en'])
                            for mch in self._rx.finditer(f.read())
                        }
                except IOError:
                    self._translations = {}
            else:
                self._translations = {}
        return self._translations

    def label(self, id: int) -> str:
        """Get localized label."""
        return self.translations.get(id, f'#{id}')

    def get(self, id: int, default: str | None = None) -> str | None:
        """Get localized label with default."""
        return self.translations.get(id, default)

    def __getitem__(self, key: int) -> str:
        """Get localized label, dict-like access: KodiLabels('pl-PL')[123]."""
        return self.translations[key]

    __call__ = label


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
