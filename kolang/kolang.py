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


from typing import overload, Dict
from xbmcaddon import Addon


_label_getters: Dict[str, Addon] = {}


class LabelGetter:
    """
    Simple label string getter (like getLocalizedString) for given addon ID.
    """

    def __init__(self, id=None):
        self.id = id
        self.addon = Addon() if self.id is None else Addon(self.id)

    @overload
    def getter(self, id: int, string: str):
        ...

    @overload
    def getter(self, string: str):
        ...

    def getter(self, *args):
        """
        L(). Get localized string. If there is no ID there string is returned without translation.
        """
        if len(args) == 2:
            sid, text = args
        elif len(args) == 1:
            if isinstance(args[0], int):
                sid, text = args[0], None
            else:
                sid, text = None, args[0]
        else:
            raise TypeError(f'L{args} – incorrect arguments')
        if sid:
            return self.addon.getLocalizedString(sid)
        return text


def get_label_getter(id=None):
    """
    Return label string getter (like getLocalizedString) for given addon ID.
    """
    try:
        return _label_getters[id].getter
    except KeyError:
        _label_getters[id] = getter = LabelGetter(id)
    return getter.getter


#: Language label getter (translation) for current itself.
L = get_label_getter()
