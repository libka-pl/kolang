"""L() formats the text with keyword arguments (also without the plural `n`)."""

from kolang.kolang import L


def test_format_without_n() -> None:
    """Keyword arguments are applied even if `n` is not given."""
    assert L('Login failed: {error}', error='bad') == 'Login failed: bad'


def test_no_kwargs_no_format() -> None:
    """Text without arguments is returned as is (braces are not interpreted)."""
    assert L('Set {login} in settings') == 'Set {login} in settings'
