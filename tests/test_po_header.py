"""PO header: missing fields are added (also to existing files), values from .kolang.json, addon.xml, defaults."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def pl(addon: Path) -> Path:
    """Addon with en+pl and one label, return pl PO path."""
    (addon / '.kolang.json').write_text('{"options": {"addon-id": "t.test"}, "languages": ["en", "pl"], "sources": [{"addon": "."}]}\n',
                                        encoding='utf-8')
    py = addon / 'resources' / 'lib' / 'main.py'
    py.parent.mkdir(parents=True)
    py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    return addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def header(po: Path) -> dict[str, str]:
    """Return header fields of PO file."""
    from kolang import polib
    return polib.pofile(str(po)).metadata


def test_new_file_header(addon: Path, pl: Path, kolang_run) -> None:
    """New file: Language-Team is the language name, translator from addon.xml provider."""
    assert kolang_run()[0] == 0
    h = header(pl)
    assert h['Language-Team'] == 'Polish'
    assert h['Language'] == 'pl_PL'
    assert h['Last-Translator'] == 't'
    assert h['Content-Type'] == 'text/plain; charset=utf-8'
    assert h['Plural-Forms'].startswith('nplurals=3;')


def test_existing_empty_header_filled(addon: Path, pl: Path, kolang_run) -> None:
    """Existing file with empty header gets missing fields, kept values stay."""
    pl.parent.mkdir(parents=True)
    pl.write_text('#\nmsgid ""\nmsgstr ""\n"Plural-Forms: nplurals=3; plural=(n==1 ? 0 : 2);\\n"\n'
                  '"Last-Translator: Jan <jan@x>\\n"\n\nmsgctxt "#30100"\nmsgid "Alpha"\nmsgstr "Alfa"\n', encoding='utf-8')
    assert kolang_run()[0] == 0
    h = header(pl)
    assert h['Content-Type'] == 'text/plain; charset=utf-8'
    assert h['Language-Team'] == 'Polish'
    assert h['Plural-Forms'] == 'nplurals=3; plural=(n==1 ? 0 : 2);'
    assert h['Last-Translator'] == 'Jan <jan@x>'
    text = pl.read_text(encoding='utf-8')
    assert kolang_run()[0] == 0
    assert pl.read_text(encoding='utf-8') == text   # idempotent


def test_header_from_addon_xml_and_config(addon: Path, pl: Path, kolang_run) -> None:
    """addon.xml email goes to translator and bugs address, .kolang.json `po-header` wins."""
    xml = (addon / 'addon.xml').read_text(encoding='utf-8')
    (addon / 'addon.xml').write_text(xml.replace('<summary', '<email>dev@t.org</email>\n        <summary'), encoding='utf-8')
    conf = addon / '.kolang.json'
    conf.write_text(conf.read_text(encoding='utf-8').replace('"options": {', '"options": {"po-header": {"Language-Team": "Team {language}"}, '),
                    encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    h = header(pl)
    assert h['Last-Translator'] == 't <dev@t.org>'
    assert h['Report-Msgid-Bugs-To'] == 'dev@t.org'
    assert h['Language-Team'] == 'Team Polish'
