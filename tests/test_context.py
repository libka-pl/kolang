"""Text context (B16): the same text with different contexts (meanings) gets different IDs and translations."""
from __future__ import annotations

from pathlib import Path

from test_merge_po import HEADER, merge

PL_CONF = ('{"options": {"addon-id": "t.test", "id-from": 30100}, '
           '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n')


def write_py(addon: Path, body: str) -> Path:
    """Write `body` as the addon python source, return its path."""
    path = addon / 'resources' / 'lib' / 'main.py'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'from kolang import L\n{body}', encoding='utf-8')
    return path


def write_settings(addon: Path, body: str) -> Path:
    """Write settings.xml with `body` inside <settings>, return its path."""
    path = addon / 'resources' / 'settings.xml'
    path.write_text(f'<settings>\n{body}</settings>\n', encoding='utf-8')
    return path


def pl_po(addon: Path) -> Path:
    """Return pl_pl strings.po path (enables pl language in config)."""
    (addon / '.kolang.json').write_text(PL_CONF, encoding='utf-8')
    return addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'


def translate(po: Path, msgid: str, msgstr: str) -> None:
    """Set translation of the first entry with `msgid`."""
    text = po.read_text(encoding='utf-8')
    po.write_text(text.replace(f'msgid "{msgid}"\nmsgstr ""', f'msgid "{msgid}"\nmsgstr "{msgstr}"', 1), encoding='utf-8')


def entry(mid: int, text: str, tr: str = '', ctx: str = '') -> str:
    """Return PO entry text with optional context comment."""
    return (f'#. context: {ctx}\n' if ctx else '') + f'msgctxt "#{mid}"\nmsgid "{text}"\nmsgstr "{tr}"\n\n'


def test_py_context_splits_ids(addon: Path, kolang_run, po_path: Path) -> None:
    """Same text: one ID per context, the same context shares the ID; context goes to `#.` comment."""
    py = write_py(addon, "a = L('Open')\nb = L('Open', ctx='adjective')\nc = L('Open')\nd = L('Open', n=1, ctx='adjective')\n")
    rc, out = kolang_run()
    assert rc == 0, out
    assert py.read_text(encoding='utf-8').splitlines()[1:] == [
        "a = L(30100, 'Open')", "b = L(30101, 'Open', ctx='adjective')",
        "c = L(30100, 'Open')", "d = L(30101, 'Open', n=1, ctx='adjective')"]
    po = po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Open"' in po
    assert '#. context: adjective\nmsgctxt "#30101"\nmsgid "Open"' in po
    assert kolang_run()[0] == 0
    assert po_path.read_text(encoding='utf-8') == po    # idempotent, context read back from PO


def test_xml_context_directive(addon: Path, kolang_run, po_path: Path) -> None:
    """`:context[label]=…:` goes to L() comment (directive removed), other directives in the comment are kept."""
    xml = write_settings(addon, '  <setting label="Open"/>\n'
                                '  <!-- :context[label]=adjective: :translate[help]=false: -->\n'
                                '  <setting label="Open" help="Open"/>\n'
                                '  <!-- :context=verb: -->\n'
                                '  <setting label="Open"/>\n')
    rc, out = kolang_run()
    assert rc == 0, out
    assert xml.read_text(encoding='utf-8').rstrip() == (
        '<settings>\n'
        "  <!-- L[label](30100, 'Open') -->\n"
        '  <setting label="30100"/>\n'
        '  <!-- :translate[help]=false: -->\n'
        "  <!-- L[label](30101, 'Open', ctx='adjective') -->\n"
        '  <setting label="30101" help="Open"/>\n'
        "  <!-- L[label](30102, 'Open', ctx='verb') -->\n"
        '  <setting label="30102"/>\n'
        '</settings>')
    assert '#. context: verb\nmsgctxt "#30102"\nmsgid "Open"' in po_path.read_text(encoding='utf-8')
    assert kolang_run()[0] == 0
    assert "L[label](30101, 'Open', ctx='adjective')" in xml.read_text(encoding='utf-8')


def test_xml_context_next_to_l_comment(addon: Path, kolang_run) -> None:
    """`:context:` next to L(): the same → removed (warning), other (also L() without ctx) → error."""
    xml = write_settings(addon, "  <!-- :context=verb: -->\n  <!-- L[label](30100, 'Open', ctx='verb') -->\n  <setting label=\"30100\"/>\n")
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'duplicates L() comment' in out
    assert ':context' not in xml.read_text(encoding='utf-8')
    write_settings(addon, "  <!-- :context=noun: -->\n  <!-- L[label](30100, 'Open', ctx='verb') -->\n  <setting label=\"30100\"/>\n")
    rc, out = kolang_run()
    assert rc == 1 and 'edit `ctx=` in the L() comment' in out, out
    write_settings(addon, "  <!-- :context=noun: -->\n  <!-- L[label](30100, 'Open') -->\n  <setting label=\"30100\"/>\n")
    rc, out = kolang_run()
    assert rc == 1, out


def test_split_copies_translation_fuzzy(addon: Path, kolang_run, po_path: Path) -> None:
    """Context added to some occurrences of an ID: they get a new ID with the translation copied as fuzzy."""
    pl = pl_po(addon)
    py = write_py(addon, "a = L('Open')\nb = L('Open')\n")
    assert kolang_run()[0] == 0
    translate(pl, 'Open', 'Otwórz')
    write_py(addon, "a = L(30100, 'Open')\nb = L(30100, 'Open', ctx='adjective')\n")
    rc, out = kolang_run()
    assert rc == 0, out
    assert "b = L(30101, 'Open', ctx='adjective')" in py.read_text(encoding='utf-8')
    text = pl.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Open"\nmsgstr "Otwórz"' in text
    assert '#. context: adjective\n#, fuzzy\n#| msgid "Open"\nmsgctxt "#30101"\nmsgid "Open"\nmsgstr "Otwórz"' in text
    assert 'msgctxt "#30101"\nmsgid "Open"\nmsgstr ""' in po_path.read_text(encoding='utf-8')


def test_context_edit_is_fuzzy(addon: Path, kolang_run) -> None:
    """Only context changed (one ID): ID is kept, translation becomes fuzzy like on text edit."""
    pl = pl_po(addon)
    py = write_py(addon, "a = L('Open')\n")
    assert kolang_run()[0] == 0
    translate(pl, 'Open', 'Otwórz')
    write_py(addon, "a = L(30100, 'Open', ctx='verb')\n")
    rc, out = kolang_run()
    assert rc == 0, out
    assert "a = L(30100, 'Open', ctx='verb')" in py.read_text(encoding='utf-8')
    assert '#. context: verb\n#, fuzzy\n#| msgid "Open"\nmsgctxt "#30100"\nmsgid "Open"\nmsgstr "Otwórz"' in pl.read_text(encoding='utf-8')


def test_realign_by_context(addon: Path, kolang_run) -> None:
    """Language PO out of sync: translations move to the ID of their (context, text)."""
    pl = pl_po(addon)
    write_py(addon, "a = L(30100, 'Open')\nb = L(30101, 'Open', ctx='adjective')\n")
    assert kolang_run()[0] == 0
    pl.write_text(HEADER + entry(30100, 'Open', 'Otwarty', ctx='adjective') + entry(30101, 'Open', 'Otwórz'), encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    assert 'realign' in out, out
    text = pl.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Open"\nmsgstr "Otwórz"' in text
    assert '#. context: adjective\nmsgctxt "#30101"\nmsgid "Open"\nmsgstr "Otwarty"' in text


def test_merge_po_context(tmp_path: Path) -> None:
    """Merge driver: same msgid with another context is a collision, the same (context, msgid) merges translation."""
    base = HEADER + entry(30100, 'Open')
    ours = base + entry(30101, 'Open', ctx='adjective')
    n, out = merge(tmp_path, base, ours, base + entry(30101, 'Open', 'Otwarte', ctx='adjective'))
    assert n == 0
    assert entry(30101, 'Open', 'Otwarte', ctx='adjective').rstrip() in out
    n, out = merge(tmp_path, base, ours, base + entry(30101, 'Open', 'Otwarty', ctx='verb'))
    assert n == 0
    assert entry(30101, 'Open', ctx='adjective').rstrip() in out
    assert entry(30102, 'Open', 'Otwarty', ctx='verb').rstrip() in out
