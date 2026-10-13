"""PO merge driver (`--merge-po BASE OURS THEIRS`) and the kolang run after the merge."""
from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import PY, run_kolang
from kolang import merge_po

HEADER = 'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=utf-8\\n"\n\n'


def po(**entries: tuple[str, str]) -> str:
    """Return PO text, entries as `_<id>=(msgid, msgstr)`."""
    return HEADER + ''.join(f'msgctxt "#{k[1:]}"\nmsgid "{t}"\nmsgstr "{s}"\n\n' for k, (t, s) in entries.items())


def merge(tmp_path: Path, base: str, ours: str, theirs: str) -> tuple[int, str]:
    """Run merge_po() on texts, return (conflicts, merged ours)."""
    paths = []
    for name, text in (('base', base), ('ours', ours), ('theirs', theirs)):
        paths.append(tmp_path / f'{name}.po')
        paths[-1].write_text(text, encoding='utf-8')
    conflicts = merge_po(*paths)
    return conflicts, paths[1].read_text(encoding='utf-8')


def test_collision_gets_new_id(tmp_path: Path) -> None:
    """Both sides took the next ID for different texts, theirs moves to a new ID with its translation."""
    base = po(_30100=('Alpha', ''))
    n, out = merge(tmp_path, base, po(_30100=('Alpha', ''), _30101=('Main', 'Główna')),
                   po(_30100=('Alpha', ''), _30101=('Branch', 'Gałąź')))
    assert n == 0
    assert 'msgctxt "#30101"\nmsgid "Main"\nmsgstr "Główna"' in out
    assert 'msgctxt "#30102"\nmsgid "Branch"\nmsgstr "Gałąź"' in out


def test_collision_text_known_in_ours(tmp_path: Path) -> None:
    """Colliding theirs text already present in ours (other ID) is not duplicated, translation is merged."""
    n, out = merge(tmp_path, po(), po(_30100=('Main', ''), _30101=('Both', '')),
                   po(_30100=('Both', 'Oba')))
    assert n == 0
    assert out.count('msgid "Both"') == 1
    assert 'msgctxt "#30101"\nmsgid "Both"\nmsgstr "Oba"' in out


def test_translation_3way(tmp_path: Path) -> None:
    """Translation changed on one side wins, changed differently on both sides is a conflict (ours fuzzy, theirs in comment)."""
    base = po(_30100=('A', 'a'), _30101=('B', 'b'))
    n, out = merge(tmp_path, base, po(_30100=('A', 'a'), _30101=('B', 'b1')), po(_30100=('A', 'a2'), _30101=('B', 'b2')))
    assert n == 1
    assert 'msgid "A"\nmsgstr "a2"' in out
    assert '# theirs: b2\n#, fuzzy\nmsgctxt "#30101"\nmsgid "B"\nmsgstr "b1"' in out


def test_text_edited_on_one_side(tmp_path: Path) -> None:
    """Text edited in theirs only is taken, edited in ours only is kept."""
    base = po(_30100=('A', ''), _30101=('B', ''))
    n, out = merge(tmp_path, base, po(_30100=('A', ''), _30101=('B ours', '')), po(_30100=('A theirs', ''), _30101=('B', '')))
    assert n == 0
    assert 'msgctxt "#30100"\nmsgid "A theirs"' in out
    assert 'msgctxt "#30101"\nmsgid "B ours"' in out


def git(addon: Path, *args: str) -> str:
    """Run git in addon dir."""
    return subprocess.run(['git', *args], cwd=addon, check=True, capture_output=True, text=True).stdout


def test_git_merge_branches(addon: Path) -> None:
    """Branches assigned the same next ID, after merge with the driver and kolang run both texts and translations live."""
    (addon / '.kolang.json').write_text('{"options": {"addon-id": "t.test", "id-from": 30100}, '
                                        '"languages": ["en", "pl"], "sources": [{"addon": "."}]}\n', encoding='utf-8')
    py = addon / 'resources' / 'lib' / 'main.py'
    py.parent.mkdir(parents=True)
    settings = addon / 'resources' / 'settings.xml'
    pl = addon / 'resources' / 'language' / 'resource.language.pl_pl' / 'strings.po'

    def kolang() -> None:
        rc, out = run_kolang(addon, '--no-backup-pattern')
        assert rc == 0, out

    def translate(text: str, tr: str) -> None:
        pl.write_text(pl.read_text(encoding='utf-8').replace(f'msgid "{text}"\nmsgstr ""', f'msgid "{text}"\nmsgstr "{tr}"'),
                      encoding='utf-8')

    git(addon, 'init', '-q', '-b', 'main')
    git(addon, 'config', 'user.email', 't@t')
    git(addon, 'config', 'user.name', 't')
    git(addon, 'config', 'merge.kolang.driver', f'{PY} -m kolang --merge-po %O %A %B')
    (addon / '.gitattributes').write_text('strings.po merge=kolang\n', encoding='utf-8')
    py.write_text("from kolang import L\na = L('Alpha')\n", encoding='utf-8')
    settings.write_text('<settings>\n</settings>\n', encoding='utf-8')
    kolang()
    git(addon, 'add', '-A')
    git(addon, 'commit', '-qm', 'base')

    git(addon, 'checkout', '-qb', 'feat')
    settings.write_text('<settings>\n  <setting label="Setting A"/>\n</settings>\n', encoding='utf-8')
    kolang()
    translate('Setting A', 'Ustawienie A')
    translate('Alpha', 'Alfa')
    git(addon, 'commit', '-qam', 'feat')

    git(addon, 'checkout', '-q', 'main')
    py.write_text("from kolang import L\na = L(30100, 'Alpha')\nm = L('From main')\n", encoding='utf-8')
    kolang()
    translate('From main', 'Z maina')
    git(addon, 'commit', '-qam', 'main')
    assert "L(30101, 'From main')" in py.read_text(encoding='utf-8')
    assert "L[label](30101, 'Setting A')" in git(addon, 'show', 'feat:resources/settings.xml')

    git(addon, 'merge', '-q', '-m', 'merge', 'feat')   # check=True: no conflict
    kolang()
    assert "L(30101, 'From main')" in py.read_text(encoding='utf-8')
    xml = settings.read_text(encoding='utf-8')
    assert "L[label](30102, 'Setting A')" in xml
    assert '<setting label="30102"/>' in xml
    text = pl.read_text(encoding='utf-8')
    assert 'msgctxt "#30100"\nmsgid "Alpha"\nmsgstr "Alfa"' in text
    assert 'msgctxt "#30101"\nmsgid "From main"\nmsgstr "Z maina"' in text
    assert 'msgctxt "#30102"\nmsgid "Setting A"\nmsgstr "Ustawienie A"' in text
