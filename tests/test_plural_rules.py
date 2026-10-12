"""Plural rules without simpleeval: compile_rule() with AST check and L() using them."""

import sys
import pytest
from kolang import kolang
from kolang.kolang import compile_rule, LabelGetter

PL_RULES = ('n == 1', '2 <= n % 10 <= 4 and not 10 < n % 100 < 20')


def test_compiled_rule_matches_python() -> None:
    """Compiled rules give the same result as plain Python."""
    for rule in PL_RULES:
        code = compile_rule(rule)
        for n in range(200):
            assert eval(code, {'__builtins__': {}}, {'n': n}) == eval(rule, {}, {'n': n}), (rule, n)


@pytest.mark.parametrize('rule', [
    "().__class__.__base__.__subclasses__()",   # sandbox escape via attributes
    "n.__class__",
    "__import__('os').system('true')",          # call
    "open('/etc/passwd')",
    "(lambda: 1)()",
    "[c for c in ()]",
    "n ** 10 ** 10",                            # DoS
    "'a' == 'a'",                               # strings
    "x == 1",                                   # other names
    "n == 1.5",                                 # float
    "n == 1 if n else 0",
])
def test_forbidden_rule(rule: str) -> None:
    """Rules with anything else than simple arithmetic on `n` are rejected."""
    with pytest.raises(ValueError):
        compile_rule(rule)


def test_plural_without_simpleeval(monkeypatch: pytest.MonkeyPatch) -> None:
    """L(n=) chooses the plural form by compiled rules if there is no simpleeval."""
    monkeypatch.setitem(sys.modules, 'simpleeval', None)  # import raises ModuleNotFoundError
    getter = LabelGetter('test.plural')
    getter.rules(locale='pl')
    assert all(type(rule) is type(compile_rule('n')) for rule in getter.rules())
    text = '{n} plik|||{n} pliki|||{n} plików'
    assert [getter(text, n=n) for n in (1, 2, 5, 12, 22, 25)] == ['1 plik', '2 pliki', '5 plików', '12 plików', '22 pliki', '25 plików']


def test_incorrect_rule_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Language with a forbidden rule is skipped (the last form is used), other languages work."""
    monkeypatch.setitem(sys.modules, 'simpleeval', None)
    (tmp_path / 'resources' / 'language').mkdir(parents=True)
    (tmp_path / 'resources' / 'language' / 'rules.json').write_text(
        '{"plural": {"en": ["n == 1"], "xx": ["().__class__"]}}', encoding='utf-8')
    monkeypatch.setattr(kolang, '__file__', str(tmp_path / 'kolang' / 'kolang.py'))
    rules = LabelGetter('test.bad').load_rules()
    assert list(rules) == ['en']
