#
# Some hacks.
#
# Author rysson <robert.kalinowski@sharkbits.com>
# License: MIT
#

from dataclasses import Field, MISSING
from typing import TypeVar, cast, Type, Any
from functools import wraps
from inspect import signature


T = TypeVar('T')


# See: https://stackoverflow.com/a/68699292/9935708
def name_tuple_field(wcls: Type[T], /) -> Type[T]:
    """Decorate NamedTuple classes to add suuport for dataclasses.field()."""
    @wraps(wcls.__new__)
    def __new__(cls: Type[T], *args: Any, **kwargs: Any) -> T:
        value: Field
        anames = set()
        if args:
            it = iter(sig.parameters)
            next(it, None)
            anames = {next(it, None) for _ in range(len(args))}
        for key, value in cls._field_defaults.items():
            if key in kwargs:
                pass
            elif key in anames:
                pass
            elif isinstance(value, Field):
                if value.default_factory is not MISSING:
                    kwargs[key] = value.default_factory()
                elif value.default is not MISSING:
                    kwargs[key] = value.default
        new = super(cls, cls).__new__(cls, *args, **kwargs)  # type: ignore[misc]
        # This call to cast() is necessary if you run MyPy with the --strict argument
        return cast(T, new)
    cls_name = wcls.__name__
    wcls.__name__ = wcls.__qualname__ = f'_{cls_name}'
    sig = signature(wcls.__new__)
    return type(cls_name, (wcls, ), {'__new__': __new__, '__slots__': ()})
