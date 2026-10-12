"""L() formats the text with keyword arguments (also without the plural `n`)."""

from kolang.kolang import L


def test_format_without_n() -> None:
    """Keyword arguments are applied even if `n` is not given."""
    assert L('Login failed: {error}', error='bad') == 'Login failed: bad'


def test_no_kwargs_no_format() -> None:
    """Text without arguments is returned as is (braces are not interpreted)."""
    assert L('Set {login} in settings') == 'Set {login} in settings'


def test_destroy_keeps_l_registered() -> None:
    """After destroy() module `L` is still the registered getter (reset() reaches it)."""
    from kolang import kolang
    kolang.destroy()
    assert kolang.get_label_getter() is kolang.L
    assert L('Error: {e}', e='x') == 'Error: x'


def test_kwargs_named_like_parameters() -> None:
    """Format arguments may have any name, also `self` or `text` (positional-only parameters)."""
    assert L('{self} {text}', self='a', text='b') == 'a b'
    assert L.get_text('{text}', text='c') == 'c'
