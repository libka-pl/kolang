"""`--reset-ids REF` (B15): IDs new on a branch are removed before merge, translations wait in PO without ID."""
from __future__ import annotations

from pathlib import Path

from conftest import PY, run_kolang
from test_merge_po import git

CONF = ('{"options": {"addon-id": "t.test", "id-from": 30100, "obsolete": "mark"}, '
        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n')


class Repo:
    """Addon in git repository with `main` branch, en + pl languages."""

    def __init__(self, addon: Path) -> None:
        self.addon: Path = addon
        self.py: Path = addon / 'resources' / 'lib' / 'main.py'
        self.other: Path = addon / 'resources' / 'lib' / 'other.py'
        self.settings: Path = addon / 'resources' / 'settings.xml'
        self.en: Path = addon / 'resources' / 'language' / 'resource.language.en_gb' / 'strings.po'
        self.pl: Path = addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'
        (addon / '.kolang.json').write_text(CONF, encoding='utf-8')
        self.py.parent.mkdir(parents=True)
        git(addon, 'init', '-q', '-b', 'main')
        git(addon, 'config', 'user.email', 't@t')
        git(addon, 'config', 'user.name', 't')
        git(addon, 'config', 'merge.kolang.driver', f'{PY} -m kolang --merge-po %O %A %B')
        (addon / '.gitattributes').write_text('strings.po merge=kolang\n', encoding='utf-8')

    def kolang(self, *args: str, rc: int = 0) -> str:
        """Run kolang, check return code, return output."""
        code, out = run_kolang(self.addon, '--no-backup-pattern', *args)
        assert code == rc, out
        return out

    def translate(self, text: str, tr: str) -> None:
        """Set pl translation of `text` (first entry)."""
        self.pl.write_text(self.pl.read_text(encoding='utf-8').replace(f'msgid "{text}"\nmsgstr ""', f'msgid "{text}"\nmsgstr "{tr}"', 1),
                           encoding='utf-8')

    def commit(self, msg: str) -> None:
        """Commit all."""
        git(self.addon, 'add', '-A')
        git(self.addon, 'commit', '-qm', msg)


def test_reset_merge_assign(addon: Path) -> None:
    """Branch IDs are reset (sources, XML, all PO), merged without collision, main run assigns IDs with translations."""
    r = Repo(addon)
    r.py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    r.settings.write_text('<settings>\n</settings>\n', encoding='utf-8')
    r.kolang()
    r.commit('base')

    git(addon, 'checkout', '-qb', 'feat')
    r.py.write_text("from kolang import L\na = L('Alpha')\nb = L('Beta', n=1)\nc = L('Open', ctx='adjective')\n", encoding='utf-8')
    r.settings.write_text('<settings>\n  <setting label="Gamma" lvalues="Alpha|Delta"/>\n</settings>\n', encoding='utf-8')
    r.kolang()
    for text, tr in (('Alpha', 'Alfa'), ('Beta', 'Beta-pl'), ('Open', 'Otwarty'), ('Gamma', 'Gamma-pl')):
        r.translate(text, tr)
    r.commit('feat')
    assert "b = L(30103, 'Beta', n=1)" in r.py.read_text(encoding='utf-8')

    out = r.kolang('--reset-ids', 'main')
    assert 'reset id: 30103' in out and 'after merge into main' in out, out
    assert r.py.read_text(encoding='utf-8') == ("from kolang import L\na = L(30100, 'Alpha')\nb = L('Beta', n=1)\n"
                                                "c = L('Open', ctx='adjective')\n")
    xml = r.settings.read_text(encoding='utf-8')
    assert '<setting label="Gamma" lvalues="30100|Delta"/>' in xml, xml
    assert 'L[label]' not in xml and 'L[lvalues#1]' not in xml and 'L[lvalues#0](30100' in xml
    pl = r.pl.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Alpha"\nmsgstr "Alfa"' in pl
    assert '\nmsgid "Beta"\nmsgstr "Beta-pl"' in pl and 'msgctxt "#30103"' not in pl
    assert '#. context: adjective\nmsgid "Open"\nmsgstr "Otwarty"' in pl
    assert 'pending: 4' in out, out
    r.kolang('--reset-ids', 'main')     # idempotent
    assert r.pl.read_text(encoding='utf-8') == pl
    r.commit('reset')

    git(addon, 'checkout', '-q', 'main')
    r.other.write_text("from kolang import L\nm = L('From main')\n", encoding='utf-8')
    r.kolang()
    r.translate('From main', 'Z maina')
    r.commit('main')

    git(addon, 'merge', '-q', '-m', 'merge', 'feat')   # check=True: no conflict
    out = r.kolang()
    assert 'pending' not in out, out
    assert "m = L(30101, 'From main')" in r.other.read_text(encoding='utf-8')
    src = r.py.read_text(encoding='utf-8')
    assert "b = L(30104, 'Beta', n=1)" in src and "c = L(30105, 'Open', ctx='adjective')" in src
    xml = r.settings.read_text(encoding='utf-8')
    assert "L[label](30102, 'Gamma')" in xml and "L[lvalues#1](30103, 'Delta')" in xml
    pl = r.pl.read_text(encoding='utf-8')
    for mid, text, tr in ((30101, 'From main', 'Z maina'), (30104, 'Beta', 'Beta-pl'), (30102, 'Gamma', 'Gamma-pl'),
                          (30103, 'Delta', '')):
        assert f'msgctxt "#{mid}"\nmsgid "{text}"\nmsgstr "{tr}"' in pl
    assert '#. context: adjective\nmsgctxt "#30105"\nmsgid "Open"\nmsgstr "Otwarty"' in pl
    assert pl.count('msgid "Beta"') == 1


def test_reset_keeps_numeric_references(addon: Path) -> None:
    """IDs used by number (getLocalizedString(N), label="N" without L() comment) are kept and reported."""
    r = Repo(addon)
    r.py.write_text("from kolang import L\n", encoding='utf-8')
    r.kolang()
    r.commit('base')
    git(addon, 'checkout', '-qb', 'feat')
    r.py.write_text("from kolang import L\na = L('Alpha')\nb = L('Beta')\n", encoding='utf-8')
    r.kolang()
    r.py.write_text("from kolang import L\na = L(30100, 'Alpha')\nb = L(30101, 'Beta')\nx = getLocalizedString(30101)\n", encoding='utf-8')
    out = r.kolang('--reset-ids', 'main')
    assert 'reset id: 30100' in out and 'keep id: 30101' in out, out
    assert "a = L('Alpha')\nb = L(30101, 'Beta')" in r.py.read_text(encoding='utf-8')


def test_reset_bad_ref(addon: Path) -> None:
    """Unknown REF is an error, nothing written."""
    r = Repo(addon)
    r.py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    r.kolang()
    r.commit('base')
    src = r.py.read_text(encoding='utf-8')
    assert 'no-such-branch' in r.kolang('--reset-ids', 'no-such-branch', rc=1)
    assert r.py.read_text(encoding='utf-8') == src


def test_pending_unused_not_assigned(addon: Path, kolang_run, po_path: Path) -> None:
    """PO entry without ID whose text is not in sources gets no ID (obsolete policy applies)."""
    (addon / 'main.py').write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    assert kolang_run()[0] == 0
    po_path.write_text(po_path.read_text(encoding='utf-8') + '\nmsgid "Unused"\nmsgstr ""\n', encoding='utf-8')
    rc, out = kolang_run()
    assert rc == 0, out
    po = po_path.read_text(encoding='utf-8')
    assert 'msgctxt "#30101"' not in po
    assert '\nmsgid "Unused"' in po


def test_reset_skin_and_context(addon: Path) -> None:
    """Skin: whole `$ADDON[addon ID]` → plain text, inside a value → `$ADDON[addon text]`; XML ctx → `:context[]=…:`."""
    r = Repo(addon)
    skin = addon / 'resources' / 'skins' / 'Default' / '720p' / 'D.xml'
    skin.parent.mkdir(parents=True)
    skin.write_text('<window>\n</window>\n', encoding='utf-8')
    r.py.write_text("from kolang import L\n", encoding='utf-8')
    r.kolang()
    r.commit('base')
    git(addon, 'checkout', '-qb', 'feat')
    skin.write_text('<window>\n  <!-- :context=verb: -->\n  <label>Open</label>\n'
                    '  <label>$ADDON[t.test World] and more</label>\n</window>\n', encoding='utf-8')
    r.kolang()
    xml = skin.read_text(encoding='utf-8')
    assert "<!-- L(30100, 'Open', ctx='verb') -->\n  <label>$ADDON[t.test 30100]</label>" in xml, xml
    assert '<label>$ADDON[t.test 30101] and more</label>' in xml, xml
    r.kolang('--reset-ids', 'main')
    assert skin.read_text(encoding='utf-8').rstrip() == ('<window>\n  <!-- :context[]=verb: -->\n  <label>Open</label>\n'
                                                         '  <label>$ADDON[t.test World] and more</label>\n</window>')
    r.kolang()
    assert skin.read_text(encoding='utf-8') == xml
