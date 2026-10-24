"""PO header `Plural-Forms` check (B38): unusable, inconsistent or different from the expected rule → warning."""
from __future__ import annotations

from pathlib import Path

import pytest

from kolang.plural import plural_forms

PL = 'nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);'


def setup_lang(addon: Path, lang: str, folder: str, forms: str | None, *, po_header: str = '') -> Path:
    """Addon with en + `lang`, one label; `lang` PO with the given Plural-Forms (None: no PO). Return the PO path."""
    options = f'"addon-id": "t.test"{po_header}'
    conf = f'{{"options": {{{options}}}, "languages": ["en", "{lang}"], "sources": [{{"addon": "."}}]}}\n'
    (addon / '.kolang.json').write_text(conf, encoding='utf-8')
    (addon / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    po = addon / 'resources' / 'language' / f'resource.language.{folder}' / 'strings.po'
    if forms is not None:
        po.parent.mkdir(parents=True, exist_ok=True)
        po.write_text(f'msgid ""\nmsgstr ""\n"Plural-Forms: {forms}\\n"\n\n', encoding='utf-8')
    return po


def test_correct_header_is_silent(addon: Path, kolang_run) -> None:
    """Header equal to the kolang table: no warning."""
    setup_lang(addon, 'pl', 'pl_pl', PL)
    rc, out = kolang_run()
    assert rc == 0 and 'Plural-Forms' not in out, out


def test_different_rule(addon: Path, kolang_run) -> None:
    """Weblate default for Polish: warning with the first different n."""
    setup_lang(addon, 'pl', 'pl_pl', 'nplurals=2; plural=(n != 1);')
    rc, out = kolang_run()
    assert rc == 0, out
    assert "differs from" in out and 'n=0 → form 1, expected 2' in out and 'fix the PO header' in out, out


@pytest.mark.parametrize('forms, message', [
    ('nplurals=2; plural= n==1 || n%10==1 ? 0 : 1; Can’t be correct needs a 2 somewhere', 'is incorrect'),
    ('nplurals=2; plural=().__class__;', 'is incorrect'),
    ('nplurals=3; plural=(n != 1);', 'is inconsistent'),
    ('nplurals=2; plural=(n==1 ? 0 : n==2 ? 1 : 2);', 'is inconsistent'),
])
def test_broken_header(addon: Path, kolang_run, forms: str, message: str) -> None:
    """Unusable or inconsistent header: warning."""
    setup_lang(addon, 'pl', 'pl_pl', forms)
    rc, out = kolang_run()
    assert rc == 0 and message in out, out


def test_config_po_header_is_expected(addon: Path, kolang_run) -> None:
    """`po-header` Plural-Forms from the config is what kolang writes, so it's the expected rule."""
    setup_lang(addon, 'pl', 'pl_pl', 'nplurals=2; plural=(n != 1);',
               po_header=', "po-header": {"Plural-Forms": "nplurals=2; plural=(n != 1);"}')
    rc, out = kolang_run()
    assert rc == 0 and 'Plural-Forms' not in out, out


def test_unknown_language_not_compared(addon: Path, kolang_run) -> None:
    """Language without a kolang table entry: its own consistent rule isn't compared to a guess."""
    setup_lang(addon, 'xx', 'xx_xx', 'nplurals=1; plural=0;')
    rc, out = kolang_run()
    assert rc == 0 and 'Plural-Forms' not in out, out


def test_new_mk_po(addon: Path, kolang_run) -> None:
    """New Macedonian PO gets the fixed rule, no warning."""
    po = setup_lang(addon, 'mk', 'mk_mk', None)
    rc, out = kolang_run()
    assert rc == 0 and 'Plural-Forms' not in out, out
    assert '"Plural-Forms: nplurals=2; plural=(n%10==1 && n%100!=11) ? 0 : 1;\\n"' in po.read_text(encoding='utf-8')


def test_kolang_table_is_consistent() -> None:
    """Every rule of `plural.py` parses and uses exactly `nplurals` forms."""
    from kolang import _parse_plural_forms
    for p in plural_forms:
        nplurals, rule = _parse_plural_forms(p.forms)
        assert {rule(n) for n in range(1000)} == set(range(nplurals)), p
