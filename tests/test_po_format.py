"""PO format of other tools is kept (B24) and broken quotes are read like Kodi (B29)."""
from __future__ import annotations

from pathlib import Path

#: Weblate / Kodi style: header split per field in own order, `#:` file references (Kodi `/` prefix), all kolang fields.
WEBLATE = '''# Kodi Media Center language file
# Addon Name: t
# Addon id: t.test
# Addon Provider: t
msgid ""
msgstr ""
"Project-Id-Version: t.test\\n"
"Report-Msgid-Bugs-To: translations@kodi.tv\\n"
"POT-Creation-Date: YEAR-MO-DA HO:MI+ZONE\\n"
"PO-Revision-Date: 2024-01-01 10:00+0000\\n"
"Last-Translator: Someone <a@b.c>\\n"
"Language-Team: English\\n"
"Language: en_GB\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=n != 1;\\n"
"X-Generator: Weblate 5.0\\n"

#: /main.py
msgctxt "#30100"
msgid "Alpha"
msgstr ""

#: /main.py
msgctxt "#30101"
msgid "Beta"
msgstr ""
'''


def test_other_tools_format_kept(addon: Path, kolang_run, po_path: Path) -> None:
    """Complete PO from Weblate / Kodi is not rewritten (header lines, field order, `#:` lines)."""
    (addon / 'main.py').write_text("from kolang import L\na = L(30100, 'Alpha')\nb = L(30101, 'Beta')\n", encoding='utf-8')
    text = WEBLATE.replace('"Last-Translator', '"X-Custom: before\\n"\n"Last-Translator')    # own field order
    po_path.write_text(text, encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert po_path.read_text(encoding='utf-8') == text


def test_one_line_header_split(addon: Path, kolang_run, po_path: Path) -> None:
    """kolang header (one line, old format) is written one field per line, missing fields appended."""
    (addon / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    po_path.write_text('msgid ""\nmsgstr "Language: en_GB\\nContent-Type: text/plain; charset=utf-8\\n"\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    text = po_path.read_text(encoding='utf-8')
    assert 'msgid ""\nmsgstr ""\n"Language: en_GB\\n"\n"Content-Type: text/plain; charset=utf-8\\n"\n"Project-Id-Version: ' in text, text


def test_unescaped_quotes_read_like_kodi(addon: Path, kolang_run, po_path: Path) -> None:
    """`msgid "… "Name""` (Kodi shows the inner quotes): read with warning, written escaped, valid PO."""
    (addon / 'main.py').write_text('from kolang import L\na = L(30100, \'Use "Database settings"\')\n', encoding='utf-8')
    po_path.write_text('msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'
                       'msgctxt "#30100"\nmsgid "Use "Database settings""\nmsgstr ""\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'unescaped "' in out, out
    assert 'msgctxt "#30100"\nmsgid "Use \\"Database settings\\""\nmsgstr ""' in po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30101"' not in po_path.read_text(encoding='utf-8')
