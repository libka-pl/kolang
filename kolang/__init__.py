from __future__ import annotations

# See: https://kodi.wiki/view/Add-on_settings_conversion
#
# These IDs are reserved by Kodi:
# - strings 30000 thru 30999 reserved for plugins and plugin settings
# - strings 31000 thru 31999 reserved for skins
# - strings 32000 thru 32999 reserved for scripts
# - strings 33000 thru 33999 reserved for common strings used in add-ons

import sys
import re
import string
from bisect import bisect
from dataclasses import dataclass, field, replace as dc_replace
from itertools import chain, count
from typing import Any, Literal, overload, TYPE_CHECKING
from pathlib import Path
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from fnmatch import fnmatch
from io import BytesIO
from ast import literal_eval
import json
import argparse
import subprocess
import shutil
import shlex
import os
try:
    from lxml import etree
except ImportError:
    sys.stderr.write('Missing lxml module, try `pip install lxml`\n')
    sys.exit(1)
if TYPE_CHECKING:
    from typing import Callable, ClassVar, Iterable, Iterator, Sequence
    from lxml.etree import _ElementTree as ElementTree
    from lxml.etree import _Element as Element
from . import polib
from .plural import plural_forms, Plural, KODI_LANGUAGES

import logging
import logging.config
logger = logging.getLogger('kolang')


__author__ = 'rysson'
__version__ = '0.3.0'


@dataclass(frozen=True)
class GenerateStats:
    new: int
    moved: int = 0
    obsolete: int = 0


class NoFreeIdError(ValueError):
    """No free label ID in the ID range."""


class FuncType(Enum):
    L = auto()                     # L(num, text)
    GetLocalizedString = auto()    # getLocalizedString(num)
    Localize = auto()              # $LOCALIZE[num]
    Addon = auto()                 # $ADDON[id num]


class XmlType(Enum):
    Auto = auto()                  # auto-detect or unsupported like includes, variables
    Settings = auto()              # settings.xml
    Window = auto()                # skin/*.xml


# @name_tuple_field
@dataclass(frozen=True)
class L8Func:
    #: Function regex pattern.
    pattern: str
    #: Function type (LL / getLocalizedString)
    type: FuncType = FuncType.GetLocalizedString
    #: Where this function is allowed.
    paths: set[Path] | None = None

    def __str__(self) -> str:
        return self.pattern

    def is_allowed(self, path: Path | None) -> bool:
        if self.paths is None:
            return True
        if path is None:
            return False
        path = path.resolve()
        return any(path.is_relative_to(p) for p in self.paths)


# @name_tuple_field
@dataclass(frozen=True)
class AddonConf:
    #: Addon ID (from addon.xml).
    id: str
    #: Paths to scan.
    paths: list[Path]
    #: Extra languages.
    langs: set[str] = field(default_factory=set)
    #: Paths to skip.
    skip: set[Path] = field(default_factory=set)
    #: Extra python localzed function/method to detect.
    l8funcs: list[L8Func] = field(default_factory=list)


@dataclass(frozen=True)
class XmlInput:
    path: Path
    tree: ElementTree
    base: Path
    declaration: str = None
    encoding: str = 'utf-8'
    #: Original file content, unchanged file is not written.
    original: bytes = field(default=b'', repr=False)
    #: Original start tag source of each element (keeps line breaks and spacing inside tags).
    start_tags: dict[Element, str] = field(default_factory=dict, repr=False)
    #: Symlink leaving the addon: scanned, never written (B30).
    readonly: bool = False


@dataclass
class PyInput:
    path: Path
    data: str = field(repr=False)
    base: Path
    #: Original file content, unchanged file is not written.
    original: str = field(default='', repr=False)
    #: Symlink leaving the addon: scanned, never written (B30).
    readonly: bool = False

    def __post_init__(self) -> None:
        """Remember original content."""
        self.original = self.original or self.data

    def replace(self, fmt: str, label: Label, start: int, end: int) -> None:
        self.data = fmt.format(before=self.data[:start], after=self.data[end:], label=label)


@dataclass
class XmlValueInput:
    """Value in XML file, used only in PY in XML."""
    node: NodeValue

    def replace(self, fmt: str, label: Label, start: int, end: int) -> None:
        node = self.node.node
        if self.node.tail:
            text = node.tail or ''
            node.tail = fmt.format(before=text[:start], after=text[end:], label=label)
        elif self.node.attr is None:
            text = node.text or ''
            node.text = fmt.format(before=text[:start], after=text[end:], label=label)
        else:
            text = node.get(self.node.attr, '')
            node.set(self.node.attr, fmt.format(before=text[:start], after=text[end:], label=label))


def local_now():
    tz = timezone(timedelta(seconds=round((datetime.now() - datetime.utcnow()).total_seconds())))
    return datetime.now(tz)


def _git_root(path: Path) -> Path | None:
    """Return git repo root for path, None if path is not in a repo. Hard-exit if git is missing."""
    cwd = path if path.is_dir() else path.parent
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=str(cwd), capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        logger.error('git binary not found in PATH; install git or disable --git-only')
        sys.exit(1)
    except subprocess.CalledProcessError:
        return None
    return Path(out.stdout.strip()).resolve()


#: Base language of sources (no translation needed).
BASE_LANG: str = 'en_GB'

_RE_OPT_SPLIT = re.compile(r'\s*:\s*')
# Matches `translate` (general) or `translate[<target>]` (per-attr/text); target
# may be empty (text content), an attr name, or `attr#index` for lvalues.
_RE_TRANSLATE_KEY = re.compile(r'^translate(?:\[([^\]]*)\])?$')
# Matches `python` (general) or `python[<target>]` (per-attr/text). Values:
# 'true' (raw scan), 'false' (no scan), 'fstring' (only {…} blocks).
_RE_PYTHON_KEY = re.compile(r'^python(?:\[([^\]]*)\])?$')
# Matches `context` (general) or `context[<target>]`. Value is the text context (no `:` inside).
_RE_CONTEXT_KEY = re.compile(r'^context(?:\[([^\]]*)\])?$')
#: Note for translators (gettext `xgettext --add-comments=Translators:` convention), in Python and XML comments.
_RE_TRANSLATORS = re.compile(r'\s*translators(?:\[(?P<target>[^\]]*)\])?\s*:\s*(?P<text>.*?)\s*$', re.IGNORECASE | re.DOTALL)
_RE_CONTEXT_DIRECTIVE = re.compile(r'\s*:\s*context(?:\[[^\]]*\])?\s*=[^:]*:')

#: Allowed `:python=…:` values.
_PYTHON_VALUES = frozenset({'true', 'false', 'fstring'})

# L() comment marker — `L(N, 'text')`, `L[attr](N, 'text')`, `L[attr#N](N, 'text')`, optional `ctx='…'`.
# Empty `L[]` is rejected (ambiguous with `L(...)`).
_RE_L_COMMENT = re.compile(
    r'\s*L'
    r'(?:\[(?P<attr>[A-Za-z_][\w.\-:]*(?:#\d+)?)\])?'
    r'\s*\(\s*(?P<id>\d+)\s*,\s*'
    r"(?P<text>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"(?:\s*,\s*ctx\s*=\s*(?P<ctx>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"))?"
    r'\s*\)\s*'
)


def _parse_L_comment(comment_text: str) -> tuple[str | None, int, str, str] | None:
    """Parse an XML comment text as `L(...)` marker. Return (attr, id, text, ctx) or None.

    `attr` is None for text content, attribute name otherwise (may be 'name#N'
    for indexed lvalues). Text is decoded from Python literal (handles `\\u002d`,
    `\\\\`, `\\'`, etc. natively via ast.literal_eval).
    """
    m = _RE_L_COMMENT.fullmatch(comment_text or '')
    if not m:
        return None
    try:
        text = literal_eval(m.group('text'))
        ctx = literal_eval(m.group('ctx')) if m.group('ctx') else ''
    except (ValueError, SyntaxError):
        return None
    return m.group('attr'), int(m.group('id')), text, ctx


def _node_value_target(nv) -> str | None:
    """Map a NodeValue to its translation `target` (None / 'attr' / 'attr#N')."""
    if nv.attr is None:
        return None
    if nv.attr == 'lvalues' and nv.index is not None:
        return f'lvalues#{nv.index}'
    return nv.attr


def _find_L_marker(node, target: str | None) -> tuple[int, str, str] | None:
    """Walk back through XML comments before `node`, find L(...) for `target`.

    Returns (id, text, ctx) of the matching marker; None if no marker found.
    Non-L comments and unrelated L markers are skipped (allowing free-form
    developer notes interleaved). Raise ValueError on the second marker for
    the same target (e.g. git merged two identical elements into one).
    """
    found: tuple[int, str, str] | None = None
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        parsed = _parse_L_comment(prev.text or '')
        if parsed is not None:
            attr, lid, text, ctx = parsed
            if attr == target:
                if found is not None:
                    raise ValueError(f'two L() comments for {target!r}: {found[:2]} and {(lid, text)}, element lost in merge?')
                found = lid, text, ctx
        prev = prev.getprevious()
    return found


def _format_L_comment(attr: str | None, label_id: int, text: str, ctx: str = '') -> str:
    """Format an L(...) marker as XML comment body (without `<!-- ... -->`).

    Each `--` sequence is escaped to `\\u002d` (per char) so the comment stays
    XML-valid. ast.literal_eval round-trips the value back when parsing.
    """
    body_text = repr(text)
    if ctx:
        body_text = f'{body_text}, ctx={ctx!r}'
    body_text = re.sub(r'-{2,}', lambda m: '\\u002d' * len(m[0]), body_text)
    if attr:
        return f' L[{attr}]({label_id}, {body_text}) '
    return f' L({label_id}, {body_text}) '


def _parse_translate_comment(text: str) -> tuple[bool | None, dict[str, bool]]:
    """Parse a single XML comment text. Return (general, per_target).

    `general` is bool (from `:translate=true/false:`) or None if absent.
    `per_target` maps target → bool, where target is:
        ''            — text content (`:translate[]=…:`)
        'attr'        — attribute (`:translate[attr]=…:`)
        'attr#N'      — lvalues index (`:translate[lvalues#0]=…:`)
    Unknown directives or invalid values are silently skipped.
    """
    general: bool | None = None
    per_target: dict[str, bool] = {}
    for op in _RE_OPT_SPLIT.split(text or ''):
        if not op:
            continue
        key, sep, value = op.partition('=')
        if not sep:
            continue
        m = _RE_TRANSLATE_KEY.match(key.strip())
        if not m:
            continue
        value = value.strip()
        if value not in ('true', 'false'):
            continue
        bval = value == 'true'
        target = m.group(1)
        if target is None:
            general = bval
        else:
            per_target[target] = bval
    return general, per_target


def _get_translate_overrides(node) -> tuple[bool | None, dict[str, bool]]:
    """Walk back through preceding XML comments, collecting :translate=…: overrides.

    Closer-to-element comments take precedence (set first, never overwritten).
    Non-`:translate=…:` comments are skipped (allowing free-form developer notes
    interleaved with directives). Walk stops at first non-comment sibling.
    """
    general: bool | None = None
    per_target: dict[str, bool] = {}
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        g, p = _parse_translate_comment(prev.text or '')
        for k, v in p.items():
            per_target.setdefault(k, v)
        if general is None:
            general = g
        prev = prev.getprevious()
    return general, per_target


def _translation_enabled(node, target: str | None) -> bool | None:
    """Return True/False/None override for a given target on node.

    Hierarchy (most specific wins):
        target='lvalues#0' → check 'lvalues#0' → 'lvalues' → general
        target='label'     → check 'label'     → general
        target=''          → check ''          → general
        target=None        → element-level default only (general)
    """
    general, per_target = _get_translate_overrides(node)
    if target is None:
        return general
    if target in per_target:
        return per_target[target]
    if '#' in target:
        attr_only = target.split('#', 1)[0]
        if attr_only in per_target:
            return per_target[attr_only]
    return general


def _parse_python_comment(text: str) -> tuple[str | None, dict[str, str]]:
    """Parse one comment text for `:python=…:` directives.

    Returns (general, per_target) where values are 'true' | 'false' | 'fstring'
    (validated; invalid values silently skipped).
    """
    general: str | None = None
    per_target: dict[str, str] = {}
    for op in _RE_OPT_SPLIT.split(text or ''):
        if not op:
            continue
        key, sep, value = op.partition('=')
        if not sep:
            continue
        m = _RE_PYTHON_KEY.match(key.strip())
        if not m:
            continue
        value = value.strip()
        if value not in _PYTHON_VALUES:
            continue
        target = m.group(1)
        if target is None:
            general = value
        else:
            per_target[target] = value
    return general, per_target


def _get_python_overrides(node) -> tuple[str | None, dict[str, str]]:
    """Walk back through preceding comments collecting :python=…: overrides.
    Closer-to-element comments take precedence (set first, never overwritten).
    """
    general: str | None = None
    per_target: dict[str, str] = {}
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        g, p = _parse_python_comment(prev.text or '')
        for k, v in p.items():
            per_target.setdefault(k, v)
        if general is None:
            general = g
        prev = prev.getprevious()
    return general, per_target


def _parse_plural_forms(forms: str) -> tuple[int, Callable[[int], int]]:
    """Parse `Plural-Forms` value (`nplurals=N; plural=EXPR;`) into (N, n → form index) like runtime `L()` (gettext).

    Raise ValueError if the value is malformed or the expression is rejected by `gettext.c2py`.
    """
    import gettext
    mch = re.fullmatch(r'\s*nplurals\s*=\s*(\d+)\s*;\s*plural\s*=\s*([^;]+);?\s*', forms)
    if mch is None:
        raise ValueError(f'malformed {forms!r}')
    try:
        return int(mch[1]), gettext.c2py(mch[2].strip())
    except (SyntaxError, RecursionError) as exc:
        raise ValueError(str(exc)) from None


def _extract_fstring_blocks(text: str) -> list[tuple[int, int, str]]:
    """Return [(start, end, code), …] for `{…}` expressions in `text` (f-string body without quotes).

    `{{` / `}}` are literal `{` / `}`. Expressions may contain strings, nested f-strings and format specs
    (`{x:>{w}}` gives `x` and `w`). Indices are positions in `text` of the code, without the braces.
    On unbalanced input blocks found so far are returned.
    """
    _end, blocks = _scan_fstring_body(text, 0, len(text), '', raw=True)
    return [(start, end, text[start:end]) for start, end in blocks]


#: Python string literal prefix characters (`t` is PEP 750 template string, same syntax as f-string).
_STR_PREFIX: frozenset[str] = frozenset('rRbBuUfFtT')


def _scan_str(text: str, i: int, end: int) -> tuple[int | None, list[tuple[int, int]]]:
    """Scan Python string literal starting at `text[i]` (prefix or quote), stop before `end`.

    Returns (index after the closing quote or None if it's not a complete literal, [(start, end), …] of `{…}` code
    in f/t-strings). Plain text scan, independent of the running Python: supports PEP 701 (same quotes, comments
    and backslashes inside nested f-string expressions).
    """
    j = i
    while j < end and text[j] in _STR_PREFIX:
        j += 1
    prefix = text[i:j].lower()
    if j >= end or text[j] not in '\'"' or len(prefix) > 2:
        return None, []
    quote = text[j] * 3 if text.startswith(text[j] * 3, j) else text[j]
    j += len(quote)
    if 'f' in prefix or 't' in prefix:
        return _scan_fstring_body(text, j, end, quote, raw='r' in prefix)
    while j < end:
        c = text[j]
        if c == '\\':
            j += 2
        elif text.startswith(quote, j):
            return j + len(quote), []
        elif c == '\n' and len(quote) == 1:
            return None, []
        else:
            j += 1
    return None, []


def _scan_fstring_body(text: str, i: int, end: int, quote: str, *, raw: bool,
                       spec: bool = False) -> tuple[int | None, list[tuple[int, int]]]:
    """Scan f-string text part from `i`: up to the closing `quote`, or `end` if `quote` is empty (XML value).

    In a format `spec` the scan stops at `}` and returns its index. Returns (index after the quote / of `}` or None
    if unterminated, [(start, end), …] of expression code).
    """
    blocks: list[tuple[int, int]] = []
    j = i
    while j < end:
        c = text[j]
        if quote and text.startswith(quote, j):
            return j + len(quote), blocks
        if c == '\\':
            if not raw and text.startswith('N{', j + 1):  # `\N{NAME}` is a character name, not an expression
                close = text.find('}', j, end)
                if close < 0:
                    return None, blocks
                j = close + 1
            else:  # escaped quote or backslash doesn't end the literal, `\{` still starts an expression
                j += 2 if j + 1 < end and text[j + 1] in '\'"\\' else 1
        elif c == '{':
            if not spec and text.startswith('{{', j):
                j += 2
                continue
            j, inner = _scan_fstring_expr(text, j + 1, end, raw=raw)
            if j is None:
                return None, blocks
            blocks.extend(inner)
        elif c == '}':
            if spec:
                return j, blocks
            j += 2 if text.startswith('}}', j) else 1
        elif c == '\n' and len(quote) == 1:
            return None, blocks
        else:
            j += 1
    return (end, blocks) if not quote else (None, blocks)


def _scan_fstring_expr(text: str, i: int, end: int, *, raw: bool) -> tuple[int | None, list[tuple[int, int]]]:
    """Scan f-string replacement field after `{` at `i`: expression, `!conversion`, `:spec`, closing `}`.

    Returns (index after `}` or None, [(start, end) of the expression, then of `{…}` inside the spec]).
    """
    depth = 0
    j = i
    while j < end:
        c = text[j]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if not depth:
                return (j + 1, [(i, j)]) if c == '}' else (None, [])
            depth -= 1
        elif c in '\'"' or (c in _STR_PREFIX and (j == i or not (text[j - 1].isalnum() or text[j - 1] == '_'))):
            stop, _blocks = _scan_str(text, j, end)  # nested literal, its own `{…}` are found by the caller's rescan
            if stop is not None:
                j = stop
                continue
            if c in '\'"':
                return None, []
        elif c == '#':
            j = text.find('\n', j, end)
            if j < 0:
                return None, []
            continue
        elif not depth and ((c == '!' and not text.startswith('!=', j)) or c == ':'):
            expr = (i, j)
            if c == '!':
                j += 1
                while j < end and (text[j].isalnum() or text[j] == '_'):
                    j += 1
                if j < end and text[j] == '}':
                    return j + 1, [expr]
                if j >= end or text[j] != ':':
                    return None, []
            stop, inner = _scan_fstring_body(text, j + 1, end, '', raw=raw, spec=True)
            if stop is None or stop >= end or text[stop] != '}':
                return None, []
            return stop + 1, [expr, *inner]
        j += 1
    return None, []


def _python_override(node, target: str | None) -> str | None:
    """Resolve effective :python override for given target. Same hierarchy
    as `_translation_enabled`. Returns 'true' | 'false' | 'fstring' | None.
    """
    general, per_target = _get_python_overrides(node)
    if target is None:
        return general
    if target in per_target:
        return per_target[target]
    if '#' in target:
        attr_only = target.split('#', 1)[0]
        if attr_only in per_target:
            return per_target[attr_only]
    return general


def _parse_context_comment(text: str) -> tuple[str | None, dict[str, str]]:
    """Parse one comment text for `:context=…:` directives. Return (general, per_target)."""
    general: str | None = None
    per_target: dict[str, str] = {}
    for op in _RE_OPT_SPLIT.split(text or ''):
        key, sep, value = op.partition('=')
        if not sep or not (m := _RE_CONTEXT_KEY.match(key.strip())):
            continue
        if m.group(1) is None:
            general = value.strip()
        else:
            per_target[m.group(1)] = value.strip()
    return general, per_target


def _context_override(node, target: str | None) -> str | None:
    """Return `:context=…:` value for `target` on `node` (None if not set). Same hierarchy as `_translation_enabled`,
    text content is `:context[]=…:`. Closer-to-element comments take precedence.
    """
    target = target or ''
    general: str | None = None
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        g, per_target = _parse_context_comment(prev.text or '')
        for key in (target, target.split('#', 1)[0]):
            if key in per_target:
                return per_target[key]
        if general is None:
            general = g
        prev = prev.getprevious()
    return general


def _translators_notes(node, target: str | None) -> list[str]:
    """Return notes of `<!-- Translators: … -->` / `<!-- Translators[target]: … -->` comments before `node` for `target`
    (general ones too, `[]` is text content, `lvalues#N` matches `[lvalues]`), whitespace collapsed, in document order.
    """
    target = target or ''
    notes: list[str] = []
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        if (m := _RE_TRANSLATORS.match(prev.text or '')) and m['target'] in (None, target, target.split('#', 1)[0]):
            notes.insert(0, ' '.join(m['text'].split()))
        prev = prev.getprevious()
    return notes


def _remove_context_comments(node) -> None:
    """Remove `:context=…:` directives before `node` (context lives in `L()` marker), drop comments left empty."""
    prev = node.getprevious()
    while isinstance(prev, etree._Comment):
        comment, prev = prev, prev.getprevious()
        text = _RE_CONTEXT_DIRECTIVE.sub('', comment.text or '')
        if text != comment.text:
            if text.strip():
                comment.text = text if text.endswith(' ') else f'{text} '
            elif (parent := comment.getparent()) is not None:
                parent.remove(comment)


def _leaves_root(path: Path, root: Path) -> bool:
    """True if `path` is inside `root` by name, but a symlink takes it outside (read-only source, B30)."""
    return (Path(os.path.normpath(path.absolute())).is_relative_to(Path(os.path.normpath(root.absolute())))
            and not path.resolve().is_relative_to(root.resolve()))


def _link_path(path: Path) -> Path:
    """Absolute path with resolved directories, the last component kept: a tracked symlink is the link, not its target."""
    return path.absolute().parent.resolve() / path.name


def _git_tracked_files(repo_root: Path) -> set[Path]:
    """Return absolute paths of files tracked by git (in the index) for given repo."""
    out = subprocess.run(
        ['git', 'ls-files', '-z'],
        cwd=str(repo_root), capture_output=True, check=True,
    )
    return {repo_root / name.decode() for name in out.stdout.split(b'\x00') if name}


def _git_clean_files(repo_root: Path) -> set[Path]:
    """Return absolute paths of tracked files without changes against HEAD (git can restore them)."""
    try:
        out = subprocess.run(['git', 'diff', '--name-only', '-z', 'HEAD'], cwd=str(repo_root), capture_output=True, check=True)
    except subprocess.CalledProcessError:  # no commit yet
        return set()
    changed = {repo_root / name.decode() for name in out.stdout.split(b'\x00') if name}
    return _git_tracked_files(repo_root) - changed


class ranges(tuple[range]):

    def __contains__(self, o: Any) -> bool:
        if isinstance(o, int):
            return any(o in rng for rng in self)
        return False

    def ids(self) -> set[int]:
        return {x for rng in self for x in rng}


class ObsoleteAction(Enum):
    KEEP = 'keep'
    MARK = 'mark'
    REMOVE = 'remove'


class SafeFormatter(string.Formatter):
    r"""
    Simple safe string formatter.
    """

    def get_field(self, field_name, args, kwargs):
        try:
            return super().get_field(field_name, args, kwargs)
        except (KeyError, AttributeError, IndexError):
            return '{%s}' % field_name, ()


def debug_print(text: str, *, indent: int = 4) -> None:
    ind = '\n' + ' ' * indent
    logger.debug(ind + text.replace('\n', ind))


def node_error(node: Element, msg: str | None = None) -> None:
    """Log XML node error."""
    lno = getattr(node, 'sourceline', None)
    suffix = f': {msg}' if msg else ''
    if lno is None:
        logger.warning(f'Node {node.tag} error{suffix}')
    else:
        logger.warning(f'Node {node.tag} (line {lno}) error{suffix}')


#: Source file (.py) translate info / translate in NodeValue
@dataclass(frozen=True)
class Trans:
    file: PyInput | XmlValueInput | None
    start: int
    end: int
    fmt: str = '{label.id}'
    #: End of `ID, ` in `L(ID, 'text')` (start of the text), to remove the ID (`--reset-ids`).
    id_end: int | None = None

    def replace(self, label: Label, *, fmt: str | None = None) -> None:
        if fmt is None:
            fmt = f'{{before}}{self.fmt}{{after}}'
        if self.file is not None:
            self.file.replace(fmt, label, start=self.start, end=self.end)


@dataclass
class Label:
    """Single label occurace in xml or py."""

    id: int | None
    text: str | None = None
    nodes: set[NodeValue] = field(default_factory=set)
    trans: list[Trans] = field(default_factory=list)
    ref: Label | None = None
    #: Text context (Qt-like disambiguation): same text with different contexts gets different IDs.
    ctx: str = ''

    @property
    def key(self) -> tuple[str, str | None]:
        """Identity of the text: (context, text)."""
        return self.ctx, self.text

    @property
    def referenced(self) -> bool:
        """True if any source uses the label (XML node or python L() occurrence)."""
        return bool(self.nodes or self.trans)


class LabelList(list[Label]):
    """Just list with smart label add."""

    def add(self, label):
        """Add label in new ID, otherwise merge."""
        for lb in self:
            if lb.id is None and label.id is not None:
                lb.id = label.id  # still label ID if was None
            if lb.id == label.id or label.id is None:
                if not lb.text and label.text:
                    lb.text = label.text
                elif label.text is not None:
                    assert label.text == lb.text
                lb.nodes |= label.nodes
                lb.trans.extend(label.trans)
                return lb
        self.append(label)
        # return len(self) - 1
        return label


@dataclass(frozen=True)
class NodeValue:
    """Pseudo xml-node, points to node and one of old select "lvalues"."""

    #: XML node.
    node: Element
    #: Attribute name.
    attr: str | None = None
    #: Index in "lvalues" settings attribute.
    index: int | None = None
    #: Regex match for take substring of the value.
    trans: Sequence[Trans] | None = None
    #: Python source node text ar attribute.
    python: bool = False
    #: True when this NodeValue refers to `node.tail` (text after the closing tag).
    tail: bool = False

    def __getattr__(self, key):
        return getattr(self.node, key)

    def replace(self, text: str, value: str, *, addon: str | None = None) -> str:
        for tr in self.trans or ():
            if tr.fmt is not None:
                value = tr.fmt.format(value=value, id=value, addon=addon)
            text = f'{text[:tr.start]}{value}{text[tr.end:]}'
        return text

    def set_label(self, value: str, addon: str | None = None) -> None:
        if self.attr is None:
            if self.trans and self.node.text is not None:
                self.node.text = self.replace(self.node.text, value, addon=addon)
            else:
                self.node.text = value
        elif self.attr == 'lvalues':
            lst = self.node.get(self.attr, '').split('|')
            if self.index is None or len(lst) < self.index:
                lst.append(value)
            else:
                lst[self.index] = value
            self.node.set(self.attr, '|'.join(lst))
        else:
            if self.trans:
                self.node.set(self.attr,
                              self.replace(self.node.get(self.attr, ''), value, addon=addon))
            else:
                self.node.set(self.attr, value)


class TranslateBase:
    """Whole translate process handler."""

    #: Language code: `ll[l]`, optional `_CC` region, optional `@variant` (like Kodi `sr_rs@latin`).
    _RE_LANG: ClassVar[re.Pattern[str]] = re.compile(
        r'(?P<lang>[a-zA-Z]{2,3})(?:_(?P<region>[a-zA-Z]{2}))?(?:@(?P<variant>\w+))?')
    #: Kodi language of a short code with more Kodi variants and no `xx_xx` one.
    _LANG_DEFAULT: ClassVar[dict[str, str]] = {'en': 'en_gb', 'zh': 'zh_cn', 'sr': 'sr_rs', 'fa': 'fa_ir'}
    #: Obsolete (Java) language codes → current ones.
    _LANG_ALIAS: ClassVar[dict[str, str]] = {'iw': 'he', 'in': 'id'}
    #: `plural.py` entries by code in lower case (the later entry of a code wins).
    _PLURALS: ClassVar[dict[str, Plural]] = {p.code.lower(): p for p in plural_forms}

    @classmethod
    def lang_case(cls, code: str) -> str:
        """Return the code in `ll_CC@variant` case (`sr_rs@latin` → `sr_RS@latin`), raise ValueError if malformed."""
        mch = cls._RE_LANG.fullmatch(code.strip())
        if mch is None:
            raise ValueError(f'Unknown language format {code!r}')
        region, variant = mch['region'], mch['variant']
        region = f'_{region.upper()}' if region else ''
        variant = f'@{variant.lower()}' if variant else ''
        return f"{mch['lang'].lower()}{region}{variant}"

    @classmethod
    def lang_code(cls, code: str) -> str:
        """Return language code like "pl_PL", a short code is the Kodi language add-on of it ("he" → "he_IL").

        Language without Kodi add-on: guess "xx_XX" (the caller warns, Kodi doesn't load it).
        """
        code = cls.lang_case(code)
        if '_' in code or '@' in code:
            return code
        lang = cls._LANG_ALIAS.get(code, code)
        ids = [k for k in KODI_LANGUAGES if re.split('[_@]', k)[0] == lang]
        kid = (cls._LANG_DEFAULT.get(lang)
               or (ids[0] if len(ids) == 1 else f'{lang}_{lang}' if f'{lang}_{lang}' in ids else None))
        return cls.lang_case(kid) if kid else f'{lang}_{lang.upper()}'

    @classmethod
    def plural_info(cls, lang: str) -> Plural | None:
        """Return `plural.py` entry of the language: by the full code ("pt_BR"), then by the language ("es_MX")."""
        code = lang.lower().partition('@')[0]
        short = code.partition('_')[0]
        return cls._PLURALS.get(code) or cls._PLURALS.get(cls._LANG_ALIAS.get(short, short))

    @classmethod
    def lang_plural_forms(cls, lang: str) -> str | None:
        """Return `Plural-Forms` of the language from the kolang table, None if unknown."""
        return info.forms if (info := cls.plural_info(lang)) else None

    @classmethod
    def lang_name(cls, lang: str) -> str:
        """Return English name of the language (for `Language-Team`) without notes like "[1]", the code if unknown."""
        return re.sub(r'\s*\[.*?\]', '', info.name) if (info := cls.plural_info(lang)) else lang


class Translate(TranslateBase):
    """Whole translate process handler."""

    #: Default lowest ID for newly assigned strings. Override via --id-from / "id-from".
    ID_FROM_DEFAULT: int = 30100
    #: Default upper bound for newly assigned IDs. Kodi reserves 30000-32999 for plugins/skins/scripts,
    #: 33000-33999 are Kodi core common strings. Override via --id-max / "id-max".
    ID_MAX_DEFAULT: int = 32999
    #: Skin string IDs: `$LOCALIZE[N]` and numeric labels find skin strings only in this range (Kodi `IsSkinStringId`).
    SKIN_ID_RANGE: tuple[int, int] = (31000, 31999)
    #: Default lowest ID for newly assigned skin strings.
    SKIN_ID_FROM_DEFAULT: int = 31100

    #: Default raw-Python tags (cała text+tail to Python source).
    DEFAULT_PYTHON_TAGS: tuple[str, ...] = ('ff:vars',)
    #: Default raw-Python attributes (per-tag); each entry is (tag_or_None, attr).
    DEFAULT_PYTHON_ATTRS: tuple[tuple[str | None, str], ...] = (
        ('ff:define', 'args'),
        ('ff:include', 'ff:args'),
        ('ff:set', 'value'),
    )

    DEF_PLURAL_FORMS = 'nplurals=2; plural=(n != 1);'

    _RE_LABEL_NUM = re.compile(r'#(?P<id>\d+)')
    _RE_PLURAL_NOTE = re.compile(r'\d+ plural forms? separated by \|\|\|')
    #: `#. context: …` line, text context for translators and for kolang (merge driver, realign).
    _RE_CONTEXT_NOTE = re.compile(r'context: (?P<ctx>.*)')
    _RE_READ_PO = re.compile(r'(?:^|\n)(?P<var>(?:msgctxt|msgid|msgstr))[ \t]*'
                             r'(?:[ \t]*[\n]"(?P<val>(?:\\.|[^"])*))+"')
    _RE_PO_VAL = re.compile(r'\s*"((?:\\.|[^"])*)"')
    _RE_LOCALIZE = re.compile(r'\$LOCALIZE\[(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|[^]])*))\]')
    _RE_ADDON = re.compile(r'\$ADDON\[(?:(?P<addon>[A-Za-z]\w*(?:\.\w+)+)\s+)?'
                           r'(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|[^]])*))\]')
    #                        r'(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|(?<!\$ADDON)[^]])*))\]')
    _RE_XML_DECL: re.Pattern = re.compile(r'''\s*<\?(?:"(?:\.|[^"])*"|'(?:\.|[^'])*'|[^>])*>\s*''')
    # bytes-version of _RE_XML_DECL — used before we know the file's encoding
    _RE_XML_DECL_BYTES: re.Pattern = re.compile(rb'''\s*<\?(?:"(?:\.|[^"])*"|'(?:\.|[^'])*'|[^>])*>\s*''')
    _RE_XML_DECL_ENCODING: re.Pattern = re.compile(rb'''encoding\s*=\s*['"]([^'"]+)['"]''')
    # XML markup tokens, only start tags are captured (`tag`), the rest is skipped.
    _RE_XML_START_TAG: re.Pattern = re.compile(r'''<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE(?:[^>\[]|\[.*?\])*>|</[^>]*>'''
                                               r'''|(?P<tag><[^\s/>!?](?:[^>"']|"[^"]*"|'[^']*')*>)''', re.DOTALL)
    _RE_XML_ATTR: re.Pattern = re.compile(r'''([^\s=<>/]+)\s*=\s*("[^"]*"|'[^']*')''')

    # `$LOCALIZE[...]` inside Python string literal — used by _replace_py.
    _RE_PY_LOCALIZE = re.compile(r'\$LOCALIZE\[(?:(?P<id>\d+)|(?P<text>(?:[\\%].|\[(?:[\\%].|[^]])*\]|[^]])+))\]')
    _RE_PY_LOCALIZE_ESC = re.compile(r'[\\%](.)')

    # Kodi label format tags (CGUITextLayout::ParseText). Stripped before the
    # `_is_translatable` letter-test, so pure-formatting strings don't qualify.
    _RE_KODI_FORMAT = re.compile(
        r'\[/?(?:B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE|TABS|COLOR|CHARSET)'
        r'(?:[ =][^\]]*)?\]'
        r'|\[CR\]'
    )
    # Generic Kodi runtime placeholder ($INFO[…], $VAR[…], …).
    _RE_KODI_PLACEHOLDER_OPEN = re.compile(r'\$\w+\[')

    def __init__(self, *,
                 dry_run: bool = False,
                 dump_output: bool = False,
                 dump_translations: str | None = None,
                 stats: bool = True,
                 list_entries: Sequence[str] = (),
                 id_from: int | None = None,
                 id_min: int | None = None,
                 id_max: int | None = None,
                 id_policy: Literal['min', 'max'] = 'max',
                 handle_getLocalizedString: bool = True,
                 addon_id: str | None = None,
                 mark_translated: bool = False,
                 obsolete: ObsoleteAction = ObsoleteAction.KEEP,
                 backup_pattern: str | None = '{}~',
                 po_wrap_width: int = 999999,
                 encoding: str = 'utf8',
                 reserved_ids: ranges | None = None,
                 multi_line_msg: bool = False,
                 git_only: bool = False,
                 extra_translate_attrs: list[str] | None = None,
                 extra_translate_tags: list[str] | None = None,
                 python_tags: list[str] | None = None,
                 python_attrs: list | None = None,
                 cleanup_translate_comments: bool = False,
                 rename: bool = True,
                 compact_ids: bool = False,
                 ) -> None:
        self.xml_inputs: list[XmlInput] = []
        self.py_inputs: list[PyInput] = []
        #: Root elements of read-only XML inputs (B30) → file path.
        self._readonly_roots: dict[Element, Path] = {}
        self._ids: set[int] = set()
        self._by_id: dict[int, Label] = {}
        self._by_text: dict[tuple[str, str], LabelList] = {}
        self.dry_run = dry_run
        self.dump_output = dump_output
        self.dump_translations = dump_translations
        #: Entries to list per language: 'fuzzy', 'untranslated'.
        self.list_entries: set[str] = set(list_entries)
        #: PO header fields from config (`po-header`), `{language}` is replaced by the language name.
        self.po_header: dict[str, str] = {}
        #: PO header fields from addon.xml (provider, email).
        self._addon_header: dict[str, str] = {}
        #: PO header comment (like Kodi addons have), addon info from addon.xml.
        self._header_comment: str = 'Kodi Media Center language file'
        #: addon.xml read for the PO header (once, the first addon).
        self._addon_header_loaded: bool = False
        self.stats = stats
        self.handle_getLocalizedString = handle_getLocalizedString
        #: Skin addon (`xbmc.gui.skin` in addon.xml or `--type skin`), ID range defaults follow Kodi skin range.
        self.skin: bool = False
        #: ID range options set explicitly (CLI, then config); None → default derived from addon type.
        self._id_from: int | None = id_from
        self._id_min: int | None = id_min
        self._id_max: int | None = id_max
        #: ID range options given on the command line, config doesn't override them.
        self._cli_options: set[str] = {k for k, v in (('id-from', id_from), ('id-min', id_min), ('id-max', id_max)) if v is not None}
        #: New ID policy:  min – lower avaliavle, max – above last used.
        self.id_policy: Literal['min', 'max'] = id_policy
        #: Addon ID for $ADDON[] XML label.
        self.addon_id: str | None = addon_id
        # Copy all EN entries as translated texts (fake translation).
        self.mark_translated: bool = mark_translated
        #: Mark translation in PO as oboslete if not used in py & xml. If false remove or don't touch.
        self.obsolete: ObsoleteAction = obsolete
        #: Backap pattern {} for source files. If false (None, False, "") backup is skipped.
        self.backup_pattern = backup_pattern
        #: Max PO line length, 999999 means no wrap.
        self.po_wrap_width = po_wrap_width
        #: Source file enocding. Should be utf-8.
        self.encoding: str = encoding
        #: Set of ranges of reserved IDs (IDs can be used).
        self.reserved_ids: ranges = reserved_ids or ranges()
        #: Moved IDs (existing IDs in reserved_ids): old → new, None if the unreferenced label is removed.
        self._moved_ids: dict[int, int | None] = {}
        #: Cache of compiled `_replace_py` regexes keyed by the tuple of
        #: GLS function patterns active for the scan (recompiling per file
        #: dominated profile traces).
        self._replace_py_re_cache: dict[tuple[str, ...], re.Pattern[str]] = {}
        #: Map id → new (ctx, text) for labels renamed in `generate()`. Used by
        #: `translate()` to update the matching `msgid` in each PO.
        self._renamed_ids: dict[int, tuple[str, str]] = {}
        #: Files that are (or with `--dry-run` / `--check` would be) written because their content changes.
        self.changed: list[Path] = []
        #: `#:` references in PO: 'none', 'file', 'line'; None → derived from the base language PO (`#:` there).
        self.locations: str | None = None
        #: Prefix of `#:` paths (`/` in Kodi skins: `#: /xml/Home.xml`), derived from the base language PO.
        self._location_prefix: str = ''
        #: Where texts are used: text key → {(path, line)}, for `#:` references.
        self._locations: dict[tuple[str, str], set[tuple[Path, int]]] = {}
        #: Where IDs are used by number: ID → {(path, line)}, for `#:` references.
        self._ref_locations: dict[int, set[tuple[Path, int]]] = {}
        #: Addon root, `#:` paths are relative to it.
        self.root: Path | None = None
        #: Notes for translators (`Translators:` comments in sources) by text key, written as `#. Translators: …`.
        self._notes: dict[tuple[str, str], list[str]] = {}
        #: IDs used by numeric references (`getLocalizedString(N)`, `$LOCALIZE[N]`, `label="N"` without `L()` comment).
        self._refs: set[int] = set()
        #: IDs removed by `reset_ids()`, their PO entries lose `msgctxt` (translation waits for a new ID).
        self._reset_ids: set[int] = set()
        #: True if po msg are splited into mulitple lines.
        self.multi_line_msg: bool = multi_line_msg
        #: Cache of loaded addon configs keyed by resolved config-file path.
        self._config_cache: dict[Path, AddonConf | None] = {}
        #: Scan only files tracked by git (in the index).
        self.git_only: bool = git_only
        #: Cache of git-tracked file sets, keyed by repo root.
        self._git_tracked_by_repo: dict[Path, set[Path]] = {}
        #: Per-repo tracked files without local changes (no backup needed, git restores them).
        self._git_clean_by_repo: dict[Path, set[Path]] = {}
        #: Backup files were checked against .gitignore (warn once).
        self._backup_ignore_checked: bool = False
        #: Extra XML attributes to scan for translation (added to defaults).
        self.extra_translate_attrs: list[str] = list(extra_translate_attrs or ())
        #: Extra XML element tags to scan as text-content translations.
        self.extra_translate_tags: list[str] = list(extra_translate_tags or ())
        #: Tags whose text/tail is raw Python (default + config).
        self.python_tags: set[str] = set(self.DEFAULT_PYTHON_TAGS) | set(python_tags or ())
        #: Per-tag raw-Python attrs as set of (tag_or_None, attr_name).
        self.python_attrs: set[tuple[str | None, str]] = set(self.DEFAULT_PYTHON_ATTRS)
        for entry in python_attrs or ():
            if isinstance(entry, str):
                self.python_attrs.add((None, entry))
            elif isinstance(entry, dict):
                name = entry.get('name')
                tags = entry.get('tags')
                if not name:
                    continue
                if not tags:
                    self.python_attrs.add((None, name))
                else:
                    for tag in tags:
                        self.python_attrs.add((tag, name))
        #: One-time cleanup: drop `:translate=false:` comments the automat would
        #: skip on its own.
        self.cleanup_translate_comments: bool = cleanup_translate_comments
        #: Rename existing IDs in place when a text edit would otherwise
        #: produce an obsolete entry that has no translation anywhere
        #: (or `--obsolete=remove` is set, so the old entry would be dropped).
        self.rename: bool = rename
        #: Renumber own IDs one after another from `id-from` (`--compact-ids`).
        self.compact_ids: bool = compact_ids

    def _add_location(self, key: tuple[str, str], path: Path | None, line: int | None) -> None:
        """Remember where text `key` is used (`#:` reference)."""
        if path is not None:
            self._locations.setdefault(key, set()).add((Path(path), line or 0))

    @property
    def id_from(self) -> int:
        """Lowest ID for new labels."""
        if self._id_from is not None:
            return self._id_from
        return self.SKIN_ID_FROM_DEFAULT if self.skin else self.ID_FROM_DEFAULT

    @id_from.setter
    def id_from(self, value: int | None) -> None:
        self._id_from = value

    @property
    def id_min(self) -> int:
        """Lower bound for "ID below threshold" warning."""
        if self._id_min is not None:
            return self._id_min
        return self.SKIN_ID_RANGE[0] if self.skin else self.id_from

    @id_min.setter
    def id_min(self, value: int | None) -> None:
        self._id_min = value

    @property
    def id_max(self) -> int:
        """Upper bound for newly assigned IDs (used by nextid())."""
        if self._id_max is not None:
            return self._id_max
        return self.SKIN_ID_RANGE[1] if self.skin else self.ID_MAX_DEFAULT

    @id_max.setter
    def id_max(self, value: int | None) -> None:
        self._id_max = value

    def _add_note(self, key: tuple[str, str], note: str) -> None:
        """Add note for translators (`Translators:` comment) to text `key`, without duplicates."""
        notes = self._notes.setdefault(key, [])
        if note and note not in notes:
            notes.append(note)

    def _add_ref(self, label_id: int, path: Path | None = None, line: int | None = None) -> None:
        """Mark `label_id` as used by a numeric reference (no text, the ID can't be found again by text) at `path:line`."""
        self._ids.add(label_id)
        self._refs.add(label_id)
        if path is not None:
            self._ref_locations.setdefault(label_id, set()).add((Path(path), line or 0))

    def _add_label(self, label: Label, *, used=True):
        """Add label to existing data (by ID and by TEXT)."""
        L1 = L2 = None
        lst = []
        if label is None:
            return
        if label.id is not None:
            if label.id < self.id_min:
                logger.warning(f'Label #{label.id} < #{self.id_min}')
            L1 = self._by_id.setdefault(label.id, label)
            # NOTE: don't merge label into L1 here — wait until conflict
            # resolution, otherwise a mismatched text would still pollute
            # L1's node set with nodes that belong to a different label.
        if label.text is not None:
            # explicit empty (`L('')`) is a declaration too, distinct from
            # a numeric reference where text is unknown — keep it.
            lst = self._by_text.setdefault(label.key, LabelList())
            L2 = lst.add(label)
        if L1 is not None and L2 is not None and L1 is not L2:
            if L2.id is None:
                label = Label(L1.id or L2.id, L1.text or L2.text,
                              L1.nodes | L2.nodes | label.nodes,
                              L1.trans + L2.trans, ctx=L2.ctx)
                assert label.id is not None
                self._by_id[label.id] = label
                lst[lst.index(L2)] = label
            else:
                assert L1.id is None or L1.id == L2.id
                if L1.text and L1.key != L2.key:
                    L0 = label
                    if (L2 is L0 or not used or (L2.id == L0.id and L2.key == L0.key)) and L1.id is not None:
                        # text mismatch in the same ID, force to generate new ID (or find another existing)
                        for lb in lst:
                            if lb.id is not None and lb.id != L2.id:
                                # text has its own ID already, move occurrences there (not the colliding text ones)
                                lb.nodes |= L2.nodes
                                lb.trans.extend(L2.trans)
                                lst.remove(L2)
                                if used:
                                    self._ids.add(lb.id)
                                return lb
                        else:
                            L2.id = None  # need to generate new ID
                            L2.ref = L1
                            return L2
                    else:
                        raise ValueError(f'Label #{L2.id}: text mismatch: {L1.key!r} != {L2.key!r}')
                L2.nodes |= L1.nodes
                L2.trans.extend(L1.trans)
                assert label.id is not None
                self._by_id[label.id] = label = L2
        elif L1 is not None:
            if L1 is not label:
                L1.nodes |= label.nodes
                L1.trans.extend(label.trans)
            label = L1
        elif L2 is not None:
            label = L2
        if used and label.id is not None:
            self._ids.add(label.id)
        return label

    #: Python string literal (no prefix), for `L()` regex.
    _R_PY_LIT: str = (r'(?:"""(?:\\.|[^"]|"(?!""))*"""' + r"|'''(?:\\.|[^']|'(?!''))*'''"
                      + r'|"(?:\\.|[^"])*"' + r"|'(?:\\.|[^'])*')")
    #: Parts of adjacent literals in `L()` text: comments (skipped) and literal contents.
    _RE_PY_LIT_PART = re.compile(r'#[^\n]*|"""((?:\\.|[^"]|"(?!""))*)"""' + r"|'''((?:\\.|[^']|'(?!''))*)'''"
                                 + r'|"((?:\\.|[^"])*)"' + r"|'((?:\\.|[^'])*)'")
    #: Python call tokens for `_call_ctx()`: string literals (skipped, `ctx=` keyword before), brackets.
    _RE_CALL_TOKEN = re.compile(r'''(?P<ctx>\bctx\s*=\s*)?(?P<str>"""(?:\\.|[^"]|"(?!""))*"""|'''
                                r"""'''(?:\\.|[^']|'(?!''))*'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|[([{]|[)\]}]""")

    @classmethod
    def _call_ctx(cls, data: str, pos: int) -> str:
        """Return `ctx='…'` value of L() call arguments starting at `pos` (after the text), empty if none.

        Scan to the closing bracket of the call, strings and nested brackets are skipped.
        """
        depth = 1
        for m in cls._RE_CALL_TOKEN.finditer(data, pos):
            if m['str'] is not None:
                if m['ctx'] is not None and depth == 1:
                    return literal_eval(m['str'])
            elif m[0] in '([{':
                depth += 1
            else:
                depth -= 1
                if not depth:
                    break
        return ''

    @staticmethod
    def _find_matching_bracket(text: str, open_pos: int) -> int | None:
        """Return index of `]` matching the `[` at `open_pos`, or None if unmatched."""
        depth = 1
        i = open_pos + 1
        while i < len(text):
            c = text[i]
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return None

    #: Kodi placeholders whose args may carry translatable text (prefix/suffix).
    _KODI_PLACEHOLDER_TEXT_ARGS: frozenset[str] = frozenset({'INFO', 'ESCINFO'})

    @staticmethod
    def _split_placeholder_args(args: str) -> list[str]:
        """Split `args` on top-level commas (respecting `[…]` nesting)."""
        parts = []
        depth = 0
        start = 0
        for i, c in enumerate(args):
            if c == '[':
                depth += 1
            elif c == ']':
                depth -= 1
            elif c == ',' and depth == 0:
                parts.append(args[start:i])
                start = i + 1
        parts.append(args[start:])
        return parts

    @classmethod
    def _strip_placeholders(cls, text: str) -> str:
        """Strip Kodi runtime placeholders, keeping translatable args (per-command).

        - `$INFO[main, prefix, suffix]`, `$ESCINFO[…]` → drop `main` (dynamic
          source), keep prefix/suffix as candidates for the letter-test.
        - `$LOCALIZE[…]`, `$ADDON[…]`, `$NUMBER[…]`, `$LABEL[…]`, `$VAR[…]`,
          `$EXP[…]`, `$PARAM[…]`, unknown `$XXX[…]` → drop entirely.
        """
        while m := cls._RE_KODI_PLACEHOLDER_OPEN.search(text):
            end = cls._find_matching_bracket(text, m.end() - 1)
            if end is None:
                # malformed — give up to avoid infinite loop
                break
            cmd = text[m.start() + 1:m.end() - 1]
            args = text[m.end():end]
            if cmd in cls._KODI_PLACEHOLDER_TEXT_ARGS:
                kept = ' '.join(cls._split_placeholder_args(args)[1:])
            else:
                kept = ''
            text = text[:m.start()] + kept + text[end + 1:]
        return text

    def _is_redundant_skip_comment(self, elem) -> bool:
        """True if a `:translate=false:` on `elem` is redundant (automat would
        skip text and all attrs anyway). Used by `--cleanup-translate-comments`."""
        text_val = elem.text or ''
        if text_val and not text_val.isdigit() and self._is_translatable(text_val):
            return False
        for attr_val in elem.attrib.values():
            if attr_val and not attr_val.isdigit() and self._is_translatable(attr_val):
                return False
        return True

    def _cleanup_translate_comments_in(self, tree) -> int:
        """Remove `:translate=false:` comments that the automat would deliver
        anyway. Only acts on solo `:translate=false:` (no other directive in
        same comment). Returns count of removed comments."""
        to_remove = []
        for elem in tree.iter():
            if isinstance(elem, etree._Comment):
                continue
            prev = elem.getprevious()
            while isinstance(prev, etree._Comment):
                general, per_target = _parse_translate_comment(prev.text or '')
                if general is False and not per_target and self._is_redundant_skip_comment(elem):
                    to_remove.append(prev)
                prev = prev.getprevious()
        for c in to_remove:
            parent = c.getparent()
            if parent is not None:
                parent.remove(c)
        return len(to_remove)

    @staticmethod
    def _ensure_L_comment(node_value, label) -> None:
        """Ensure an `L(...)` XML comment for `label` precedes the element.

        Three cases for the existing comment matching this target:
          - identical (id, text and context) → skip (idempotent),
          - stale (id, text or context differs) → update in place (preserves position
            and tail), so the next run sees the up-to-date marker,
          - missing → insert a new comment, on its own line, using the
            indent that precedes the element.

        `:context=…:` directives before the element are removed (context is kept in `L()`).
        Skips labels with no text (numeric refs to unknown ids — nothing to
        document).
        """
        if not label.text:
            return
        target = _node_value_target(node_value)
        elem = node_value.node
        _remove_context_comments(elem)  # context is in L() now
        body = _format_L_comment(target, label.id, label.text, label.ctx)
        # Walk back through preceding comments looking for one targeting us.
        prev = elem.getprevious()
        while isinstance(prev, etree._Comment):
            parsed = _parse_L_comment(prev.text or '')
            if parsed is not None and parsed[0] == target:
                if parsed[1:] == (label.id, label.text, label.ctx):
                    return  # identical
                prev.text = body  # stale → update in place
                return
            prev = prev.getprevious()
        # Missing — insert new on its own line.
        prev = elem.getprevious()
        parent = elem.getparent()
        src = prev.tail if prev is not None else (parent.text if parent is not None else '')
        m = re.search(r'(\n[ \t]*)$', src or '')
        sep = m.group(1) if m else ''
        comment = etree.Comment(body)
        comment.tail = sep
        elem.addprevious(comment)

    @staticmethod
    def _tag_local(elem) -> str:
        """Return tag in `prefix:local` form (Clark `{ns}local` → `prefix:local`).

        Assumes `xmlns:prefix="ns"` on the element/ancestor — uses `nsmap` to
        find the prefix bound to the namespace URI.
        """
        tag = elem.tag
        if not isinstance(tag, str) or not tag.startswith('{'):
            return tag if isinstance(tag, str) else ''
        ns_end = tag.index('}')
        uri = tag[1:ns_end]
        local = tag[ns_end + 1:]
        for prefix, p_uri in (elem.nsmap or {}).items():
            if p_uri == uri and prefix:
                return f'{prefix}:{local}'
        return local

    @staticmethod
    def _attr_local(elem, attr: str) -> str:
        """Map a Clark-notation attribute name to `prefix:local`."""
        if not attr.startswith('{'):
            return attr
        ns_end = attr.index('}')
        uri = attr[1:ns_end]
        local = attr[ns_end + 1:]
        for prefix, p_uri in (elem.nsmap or {}).items():
            if p_uri == uri and prefix:
                return f'{prefix}:{local}'
        return local

    def _python_apply_value(self, elem, attr_or_tail, value: str, mode: str, path) -> None:
        """Run python scan on `value` in `mode`. attr_or_tail: None=text, str=attr, 'TAIL'=tail."""
        if mode == 'false' or not value:
            return
        is_tail = attr_or_tail == 'TAIL'
        attr = None if is_tail or attr_or_tail is None else attr_or_tail
        nv = NodeValue(elem, attr=attr, tail=is_tail, python=True)
        file = XmlValueInput(nv)
        if mode == 'true':
            self._replace_py(value, file=file, node=nv, path=path)
        elif mode == 'fstring':
            for start, _end, code in _extract_fstring_blocks(value):
                self._replace_py(code, file=file, node=nv, path=path, data_offset=start)

    def _python_scan_pass(self, root, *, is_skin: bool, path) -> None:
        """Step 1 of XML scan: per `:python` mode, run `_replace_py` on values.

        Iterates all elements; each text/attr/tail gets a mode resolution
        (granular override → general override → whitelist → context default)
        and is scanned accordingly. Modifies XML in place via Trans/replace.
        """
        def visit(elem):
            if isinstance(elem.tag, str):
                # text
                if elem.text:
                    mode = self._python_mode(elem, '', is_skin=is_skin)
                    self._python_apply_value(elem, None, elem.text, mode, path)
                # attrs
                for attr_name, attr_val in elem.attrib.items():
                    if not attr_val:
                        continue
                    local = self._attr_local(elem, attr_name)
                    mode = self._python_mode(elem, local, is_skin=is_skin)
                    self._python_apply_value(elem, local, attr_val, mode, path)
                for child in elem:
                    visit(child)
                    if child.tail:
                        if isinstance(child.tag, str):
                            mode = self._python_mode(child, '', is_skin=is_skin)
                            self._python_apply_value(child, 'TAIL', child.tail, mode, path)
        visit(root)

    def _python_mode(self, elem, target: str | None, *, is_skin: bool) -> str:
        """Resolve effective `:python` mode for given (elem, target).

        Returns one of: 'true' (raw), 'false' (skip), 'fstring'.
        Hierarchy: granular override → general override → whitelist → context default.
        """
        ov = _python_override(elem, target)
        if ov is not None:
            return ov
        tag = self._tag_local(elem)
        if target is None or target == '':
            # text content / tail
            if tag in self.python_tags:
                return 'true'
        else:
            # attribute (target may be 'attr' or 'attr#N')
            attr_only = target.split('#', 1)[0] if '#' in target else target
            if (tag, attr_only) in self.python_attrs or (None, attr_only) in self.python_attrs:
                return 'true'
        return 'fstring' if is_skin else 'false'

    @classmethod
    def _is_translatable(cls, text: str) -> bool:
        """Return True if `text` contains a phrase worth translating.

        Heuristic: strip Kodi format tags ([B], [COLOR …], [CR], …) and runtime
        placeholders ($INFO[…], $VAR[…], …), then look for at least one Unicode
        letter. Pure punctuation, digits and whitespace don't qualify.
        Adjust this heuristic in one place if it proves too permissive/strict.
        """
        text = cls._RE_KODI_FORMAT.sub('', text)
        text = cls._strip_placeholders(text)
        return any(c.isalpha() for c in text)

    def _scan_xml(self, tree: ElementTree, xtype: XmlType = XmlType.Auto, *,
                  path: Path | None = None):
        """Scan single XML."""
        def add(text: str, node: NodeValue) -> None:
            if not text:
                # Missing or empty XML attr/text — there's no XML idiom for
                # an "explicit empty" declaration (unlike Python's L('')),
                # so skip rather than invent a label.
                if text is None:
                    node_error(node, 'Empty node/attr (string expected)')
                return
            target = _node_value_target(node)
            try:
                marker = _find_L_marker(node.node, target)
            except ValueError as exc:
                logger.error(f'{path}:{node.node.sourceline}: {exc}')
                sys.exit(1)
            is_numeric = text.isdigit()
            ctx = _context_override(node.node, target)
            if marker is None:
                # No L() comment — current default behavior.
                if is_numeric:
                    nid = int(text)
                    logger.debug(f'  numeric XML ref #{nid}')
                    self._add_ref(nid, path, node.node.sourceline)
                    # Migration: if this ID is known from PO with a text,
                    # attach the node so write-side can inject L() comment.
                    existing = self._by_id.get(nid)
                    if existing is not None and existing.text:
                        if ctx is not None and ctx != existing.ctx:
                            logger.error(f'{path}:{node.node.sourceline}: :context={ctx}: on #{nid} with context '
                                         f'{existing.ctx!r} in PO — use the text instead of the number to change context.')
                            sys.exit(1)
                        existing.nodes.add(node)
                    return
                label = Label(None, text, ctx=ctx or '')
                label.nodes.add(node)
                self._add_location(label.key, path, node.node.sourceline)
                for note in _translators_notes(node.node, target):
                    self._add_note(label.key, note)
                self._add_label(label)
                return
            # L() comment present — comment is authoritative (matrix G).
            cm_id, cm_text, cm_ctx = marker
            # `:context:` next to L() is like XML text next to L(): the same → redundant, other → two sources of truth
            if ctx is not None:
                if ctx != cm_ctx:
                    logger.error(f'{path}:{node.node.sourceline}: :context={ctx}: on {target!r} differs from L() comment '
                                 f'context {cm_ctx!r} — refusing to discard either; edit `ctx=` in the L() comment.')
                    sys.exit(1)
                logger.warning(f'{path}:{node.node.sourceline}: :context={ctx}: duplicates L() comment on {target!r}, removed.')
            if is_numeric:
                xml_id = int(text)
                if xml_id != cm_id:
                    logger.warning(
                        f'L() comment ID mismatch on {target!r}: '
                        f'XML=#{xml_id}, comment=#{cm_id} — using comment.'
                    )
                label = Label(cm_id, cm_text, ctx=cm_ctx)
            else:
                if text == cm_text:
                    logger.warning(
                        f'L() comment duplicates XML text on {target!r} — '
                        f'replacing XML with #{cm_id}.'
                    )
                    label = Label(cm_id, cm_text, ctx=cm_ctx)
                else:
                    logger.error(
                        f'L() comment text mismatch on {target!r}: '
                        f'XML={text!r}, comment={cm_text!r} — '
                        f'refusing to discard either; pick one source of truth.'
                    )
                    sys.exit(1)
            label.nodes.add(node)
            self._add_location(label.key, path, node.node.sourceline)
            for note in _translators_notes(node.node, target):
                self._add_note(label.key, note)
            self._add_label(label)

        def is_enabled(node: Element) -> bool:
            """Element-level enable check: True unless `:translate=false:` was set."""
            general, _ = _get_translate_overrides(node)
            return general is not False

        def should_translate(node: Element, target: str | None, text: str | None) -> bool:
            """Decide whether to translate `text` for given target on `node`.

            Order of precedence:
              1. comment override (granular wins over general).
              2. if `:python=fstring:` is active for this target AND `text`
                 contains any `{…}` block — return False (template runtime
                 will compose; cała wartość nie idzie do PO).
              3. automat (`_is_translatable`) — letter-test after stripping
                 format tags & runtime placeholders.
            Numeric refs are handled by `add()` separately and don't reach here.
            """
            override = _translation_enabled(node, target)
            if override is False:
                return False
            if override is True:
                return True
            value = text or ''
            py_mode = self._python_mode(node, target, is_skin=(xtype == XmlType.Window))
            if py_mode == 'fstring' and _extract_fstring_blocks(value):
                return False
            return self._is_translatable(value)

        node: Element
        root = tree.getroot()
        if xtype == XmlType.Auto:
            if root.tag == 'settings':
                xtype = XmlType.Settings
            elif root.tag in ('window', 'includes'):  # skin window or includes (most of skin labels)
                xtype = XmlType.Window

        def gate(node: Element, target: str | None, text: str | None) -> bool:
            """Pre-`add()` filter: numeric refs always pass (so `_ids` learns
            them); empty texts always pass (handled by `add()`); text values
            go through override + automat."""
            if not text or text.isdigit():
                return True
            return should_translate(node, target, text)

        # -- step 1: python scan (raw / fstring) — modifies values in place.
        is_skin = (xtype == XmlType.Window)
        self._python_scan_pass(root, is_skin=is_skin, path=path)

        # $LOCALIZE[N] in any XML (skin window/includes, skinshortcuts, …) — runtime substitution to Kodi string by ID.
        # Mark the ID as used so the generator doesn't reassign it to a new label.
        for node in root.xpath('.//*[text()[contains(.,"$LOCALIZE[")]]'):
            for m in self._RE_LOCALIZE.finditer(node.text or ''):
                if m['id']:
                    nid = int(m['id'])
                    logger.debug(f'  XML $LOCALIZE[#{nid}] reference')
                    self._add_ref(nid, path, node.sourceline)
        for node in root.xpath('.//@*[contains(.,"$LOCALIZE[")]/..'):
            for attr_name, attr_val in node.attrib.items():
                for m in self._RE_LOCALIZE.finditer(attr_val):
                    if m['id']:
                        nid = int(m['id'])
                        logger.debug(f'  XML attr {attr_name} $LOCALIZE[#{nid}] reference')
                        self._add_ref(nid, path, node.sourceline)

        # skin attributes with a string ID: `<viewtype label="N">`, `<fontset idloc="N">` (Font.xml)
        for value in root.xpath('.//viewtype/@label|.//fontset/@idloc'):
            if value.isdigit():
                self._add_ref(int(value), path, value.getparent().sourceline)

        # -- step 2: translate scan (settings / window).
        text_tags = ('heading', *self.extra_translate_tags)
        attr_names = ('label', 'help', *self.extra_translate_attrs)
        if xtype == XmlType.Settings:
            for tag in text_tags:
                for node in root.iterfind(f'.//{tag}'):
                    logger.debug(f'  found set.XML <{tag}>, value {node.text!r}')
                    if gate(node, '', node.text):
                        add(node.text, NodeValue(node, None))
            for attr in attr_names:
                for node in root.iterfind(f'.//*[@{attr}]'):
                    text = node.get(attr)
                    if text:
                        logger.debug(f'  found set.XML node {node.tag} attr {attr}, value {text!r}')
                    if gate(node, attr, text):
                        add(text, NodeValue(node, attr))
            for node in root.iterfind('.//*[@lvalues]'):
                for i, text in enumerate(node.get('lvalues').split('|')):
                    logger.debug(f'  found set.XML lvalue {text!r}')
                    if gate(node, f'lvalues#{i}', text):
                        add(text, NodeValue(node, 'lvalues', index=i))
        # -- skin/window.xml
        elif xtype == XmlType.Window:
            # <label>TEXT</label>, w/o `$LOCALIZE[`
            if self.addon_id:
                skin_tags = ('label', 'hinttext', *self.extra_translate_tags)
                xpath_skin = '|'.join(f'.//{t}' for t in skin_tags)
                for node in root.xpath(xpath_skin):
                    text = node.text
                    if not text or '$ADDON[' in text:  # `$ADDON[…]` texts are handled below, the rest stays literal
                        continue
                    if not gate(node, '', text):
                        continue
                    logger.debug(f'  found win.XML <{node.tag}>, value {text!r}')
                    add(text, NodeValue(node, None, trans=(Trans(None, start=0, end=len(text),
                                                                 fmt='$ADDON[{addon} {id}]'),)))
                # extra attributes (e.g. tooltip)
                for attr in self.extra_translate_attrs:
                    for node in root.iterfind(f'.//*[@{attr}]'):
                        text = node.get(attr)
                        if not text:
                            continue
                        if not gate(node, attr, text):
                            continue
                        logger.debug(f'  found win.XML node {node.tag} attr {attr}, value {text!r}')
                        add(text, NodeValue(node, attr, trans=(Trans(None, start=0, end=len(text),
                                                                     fmt='$ADDON[{addon} {id}]'),)))
            # $ADDON[ID TEXT]
            for node in root.xpath('.//*[text()[contains(.,"$ADDON[")]]'):
                text = node.text
                mm = list(self._RE_ADDON.finditer(text))
                for m in reversed(mm):  # from the end to avoid span move on text replace
                    if self.addon_id and m['addon'] and self.addon_id != m['addon']:
                        continue
                    if not is_enabled(node):
                        continue
                    logger.debug(f'  found win.XML $ADDON[], value {m["text"] or "#"+m["id"]!r}, addon {m["addon"]!r}')
                    start, end = m.span('id') if m['id'] else m.span('text')
                    trans = [Trans(None, start, end, fmt=None)]
                    if self.addon_id and not m['addon']:
                        trans.append(Trans(None, start, start, fmt=f'{self.addon_id} '))
                    add(text[start:end], NodeValue(node, None, trans=tuple(trans)))

    def load_xml(self, path: str | Path, base: str | Path | None = None, *, readonly: bool = False):
        """Load XML and keep data."""
        path = Path(path)
        if base is not None:
            base = Path(base)
        content_bytes = path.read_bytes()
        # Detect encoding from XML declaration; fall back to self.encoding
        # (matters on Windows where the system default isn't UTF-8 and the
        # file lacks a declaration).
        decl_bytes_match = self._RE_XML_DECL_BYTES.match(content_bytes)
        encoding = self.encoding
        if decl_bytes_match:
            enc_match = self._RE_XML_DECL_ENCODING.search(decl_bytes_match[0])
            if enc_match:
                encoding = enc_match[1].decode('ascii')
        content = content_bytes.decode(encoding)
        tree = etree.parse(BytesIO(content_bytes))
        m: re.Match = self._RE_XML_DECL.match(content)
        decl: str = m and m[0]
        tags = [m['tag'] for m in self._RE_XML_START_TAG.finditer(content) if m['tag']]
        elems = list(tree.iter(etree.Element))
        start_tags = dict(zip(elems, tags)) if len(tags) == len(elems) else {}
        self.xml_inputs.append(XmlInput(path, tree, base, declaration=decl, encoding=encoding, original=content_bytes, start_tags=start_tags,
                                        readonly=readonly))
        if readonly:
            self._readonly_roots[tree.getroot()] = path
        self._scan_xml(tree, path=path)
        return tree

    def load_py(self, path: str | Path, base: str | Path | None = None, *,
                l8funcs: list[L8Func] | None = None, readonly: bool = False) -> None:
        """Load strings from Python source and keep data."""
        path = Path(path)
        if base is not None:
            base = Path(base)
        with open(path, encoding=self.encoding, newline='') as f:
            data = f.read()
        file = PyInput(path, data, base, readonly=readonly)
        self.py_inputs.append(file)
        self._replace_py(data, file=file, l8funcs=l8funcs, path=path)

    def _replace_py(self,
                    data: str,
                    *,
                    file: PyInput | XmlValueInput | None,
                    l8funcs: list[L8Func] | None = None,
                    node: NodeValue | None = None,
                    path: Path | None = None,
                    data_offset: int = 0,
                    ) -> None:
        """Scan single Python source data.

        `data_offset` shifts every produced `Trans.start/end` by this amount —
        used when `data` is a fragment of a larger value (e.g. a `{…}` block
        inside an XML attribute under f-string mode), so replacements land on
        the correct positions in the surrounding value.
        """

        def rstr(name='str'):
            pat = '|'.join((
                fr'"""(?P<{name}1>(?:\\.|[^"]|"(?!""))*)"""',   # """..."""
                fr"'''(?P<{name}2>(?:\\.|[^']|'(?!''))*)'''",   # '''...'''
                fr'"(?P<{name}3>(?:\\.|[^"])*)"',     # "..."
                fr"'(?P<{name}4>(?:\\.|[^'])*)'",     # '...'
            ))
            return f'(?:{pat})'

        # Pre-computed group name tuples — avoids 4× f-string formatting
        # per call in the hot finditer loop.
        _str_grp = ('str1', 'str2', 'str3', 'str4')
        _gls_grp = ('gls_text1', 'gls_text2', 'gls_text3', 'gls_text4')

        def rval(r, groups=_str_grp):
            for g in groups:
                s = r[g]
                if s is not None:
                    return s

        def rstart(r, groups=_str_grp):
            for g in groups:
                s = r.start(g)
                if s != -1:
                    return s

        _R_CM = r'#[^\S\r\n]*(?P<comment>[^\r\n]+)'
        # L(ID, 'text' 'more', …): the first argument is exactly a string literal (adjacent literals are one text,
        # also across lines, comments between them); the end of the call isn't needed (line breaks, nested calls)
        lit = self._R_PY_LIT
        _R_LL = (fr'\b(?P<label>LL?)\s*\(\s*(?:(?P<mid>\d+)\s*,\s*)?(?P<msgs>{lit}(?:(?:\s|#[^\n]*)*{lit})*)\s*(?=[,)])'
                 # L(ID) / L(ID, n=…) without text: numeric reference
                 fr'|\bLL?\s*\(\s*(?P<ref>\d+)\s*(?=[,)])'
                 # literal starts the argument, but it isn't a plain literal (f-string, prefix, expression)
                 fr'|\bLL?\s*\(\s*(?:\d+\s*,\s*)?(?P<bad>(?:[fFrRbBuU]{{1,2}})?{lit})')
        # string literal with its prefix (`pfx`): f/t-strings are scanned for `{…}` code
        pat = fr'{_R_CM}|(?P<pfx>(?<!\w)[rRbBuUfFtT]{{1,2}})?{rstr()}|{_R_LL}'
        l8funcs = list(l8funcs or ())
        if self.handle_getLocalizedString:
            l8funcs.append(L8Func('getLocalizedString'))
        gls_funcs = [f for f in l8funcs
                     if f.type == FuncType.GetLocalizedString and (path is None or f.is_allowed(path))]
        if gls_funcs:
            ff = '|'.join(fr'(?:{f})' for f in gls_funcs)
            pat += fr'|\b(?P<gls_func>{ff})\s*\(\s*(?P<gls>(?:(?P<gls_id>\d+)|{rstr("gls_text")}))\s*[),]'
        cache_key = tuple(f.pattern for f in gls_funcs)
        R = self._replace_py_re_cache.get(cache_key)
        if R is None:
            R = re.compile(pat)
            self._replace_py_re_cache[cache_key] = R
        # `# Translators: …` comment block: notes for L() on the next line (block above) or on the same line (trailing)
        newlines = [m.start() for m in re.finditer('\n', data)]
        block: list[str] = []
        block_line = -2
        line_keys: tuple[int, list[tuple[str, str]]] = (-1, [])
        xml_notes = _translators_notes(node.node, _node_value_target(node)) if node is not None else []

        def matches(pos: int, endpos: int) -> Iterator[re.Match[str]]:
            """Matches in `data[pos:endpos]`, code in `{…}` of f/t-strings included (positions stay absolute)."""
            while (r := R.search(data, pos, endpos)) is not None:
                yield r
                pos = r.end()
                if (pfx := r['pfx']) and ('f' in pfx.lower() or 't' in pfx.lower()):
                    stop, blocks = _scan_str(data, r.start(), endpos)
                    if stop is None:
                        logger.debug(f'{path}:{bisect(newlines, r.start()) + 1}: unterminated f-string, its code skipped')
                        continue
                    pos = stop
                    for start, end in blocks:
                        yield from matches(start, end)

        for r in matches(0, len(data)):
            if r['comment'] is not None:
                line = bisect(newlines, r.start())
                own_line = not data[(newlines[line - 1] + 1 if line else 0):r.start()].strip()
                if m := _RE_TRANSLATORS.match(r['comment']):
                    if not own_line:
                        for key in line_keys[1] if line_keys[0] == line else ():
                            self._add_note(key, m['text'])
                        continue
                    block, block_line = [m['text']], line
                elif own_line and block and block_line == line - 1:
                    block.append(r['comment'].strip())   # continuation of the block
                    block_line = line
                continue
            label: Label | None = None
            tr = None
            s = rval(r)
            sstart = rstart(r)
            if r['ref'] is not None:
                self._add_ref(int(r['ref']), path, node.node.sourceline if node is not None else bisect(newlines, r.start()) + 1)
                continue
            if r['bad'] is not None:
                where = f'{path}:{node.node.sourceline}' if node is not None else f'{path}:{bisect(newlines, r.start()) + 1}'
                logger.warning(f'{where}: L() text is not a plain string literal, not translated: {r[0]!r}')
                continue
            # L()
            if (msgs := r['msgs']) is not None:
                msg = ''.join(unescape(next(v for v in m.groups() if v is not None))
                              for m in self._RE_PY_LIT_PART.finditer(msgs) if m[0][0] != '#')
                start = data_offset + r.start('msgs')
                if (mid := r['mid']) is None:
                    tr = Trans(file, start=start, end=start, fmt='{label.id}, ')
                else:
                    mid = int(mid)
                    tr = Trans(file, start=data_offset + r.start('mid'), end=data_offset + r.end('mid'), id_end=start)
                label = Label(mid, msg, ctx=self._call_ctx(data, r.end('msgs')))
            # " $LOCALIZE[] "
            elif s is not None:
                for r in self._RE_PY_LOCALIZE.finditer(s):
                    mid = r['id']
                    if mid is not None:
                        mid = int(mid)
                    if r['text'] is not None:
                        tr = Trans(file, start=data_offset + sstart + r.start('text'), end=data_offset + sstart + r.end('text'))
                        text = self._RE_PY_LOCALIZE_ESC.sub(r'\1', r['text'])
                        label = Label(mid, unescape(text))
                    elif mid is not None:
                        self._add_ref(mid, path, node.node.sourceline if node is not None else bisect(newlines, sstart) + 1)
            # getLocalizedString()
            elif r['gls'] is not None:
                mid = r['gls_id']
                func = r['gls_func']
                text = rval(r, _gls_grp)
                logger.debug(f'  found func {func!r}, id {mid}, text {text!r}')
                if mid is not None:
                    # Numeric reference (e.g. getLocalizedString(123)) — only
                    # mark the ID as used; declaration lives elsewhere.
                    logger.debug(f'  numeric PY ref #{mid}')
                    self._add_ref(int(mid), path, node.node.sourceline if node is not None else bisect(newlines, r.start()) + 1)
                    continue
                tr = Trans(file, start=data_offset + r.start('gls'), end=data_offset + r.end('gls'))
                label = Label(None, unescape(text))
            if label is not None:
                if tr is not None:
                    label.trans.append(tr)
                if node is not None:
                    label.nodes.add(node)
                if label.text is not None:
                    line = bisect(newlines, r.start())
                    self._add_location(label.key, path, node.node.sourceline if node is not None else line + 1)
                    notes = [' '.join(' '.join(block).split())] if block and block_line == line - 1 else []
                    for note in notes + xml_notes:
                        self._add_note(label.key, note)
                    if line_keys[0] != line:
                        line_keys = line, []
                    line_keys[1].append(label.key)
                self._add_label(label)

    def _is_git_tracked(self, path: Path) -> bool:
        """When --git-only is enabled, return True iff `path` is in the git index.
        Hard-exits if the path is not in any git repository (--git-only contract)."""
        if not self.git_only:
            return True
        abspath = _link_path(path)
        root = _git_root(abspath)
        if root is None:
            logger.error(f'{abspath} is not in a git repository (--git-only requires git tracking)')
            sys.exit(1)
        if root not in self._git_tracked_by_repo:
            self._git_tracked_by_repo[root] = _git_tracked_files(root)
        return abspath in self._git_tracked_by_repo[root]

    def uncommitted(self, paths: Iterable[Path]) -> list[Path]:
        """Return `paths` git can't restore: outside a repository, untracked or with local changes."""
        result = []
        for path in paths:
            path = _link_path(path)
            root = _git_root(path) if shutil.which('git') else None
            if root is not None and root not in self._git_clean_by_repo:
                self._git_clean_by_repo[root] = _git_clean_files(root)
            if root is None or path not in self._git_clean_by_repo[root]:
                result.append(path)
        return result

    def _load_input(self, path: Path, *, l8funcs: list[L8Func] | None = None, readonly: bool = False) -> None:
        """Load single file (XML / py) and keep data."""
        logger.info(f'Loading source {path}')
        if readonly:
            logger.warning(f'Read-only source {path} -> {path.resolve()} (symlink outside the addon), not written')
        if path.suffix == '.py':
            return self.load_py(path, l8funcs=l8funcs, readonly=readonly)
        return self.load_xml(path, readonly=readonly)

    def load_input(self,
                   path: str | Path,
                   *,
                   skip: set[Path] = set(),
                   l8funcs: list[L8Func] | None = None,
                   root: Path | None = None) -> None:
        """Load input file / py-dir (XML / py) and keep data.

        Source leaving `root` (addon dir, default: the dir itself or the file's dir) through a symlink is read-only.
        """
        res = None
        path = Path(path)
        if root is None:
            root = path if path.is_dir() else path.parent
        if not path.exists():
            logger.warning('Path does not exist: {!r}, skipping.'.format(str(path)))
        elif path.is_dir():
            # `path.glob` returns absolute paths starting with `path`, and
            # `skip` was resolved to absolute paths in `load_addon` — so a
            # lexical `is_relative_to` is enough; avoid `resolve()` per file
            # (each `resolve()` does lstat per path component, and this loop
            # easily sees thousands of files).
            # `**` doesn't descend into symlinked dirs (Python 3.9–3.15), only a symlinked file or the dir itself
            # can leave the root — `resolve()` only for links.
            dir_leaves = _leaves_root(path, root)
            for p in chain(path.glob('**/*.xml'), path.glob('**/*.py')):
                if skip and any(p.is_relative_to(s) for s in skip):
                    pass
                elif not self._is_git_tracked(p):
                    logger.debug(f'Skipping non-tracked: {p}')
                else:
                    res = self._load_input(p, l8funcs=l8funcs, readonly=dir_leaves or (p.is_symlink() and _leaves_root(p, root)))
        elif not self._is_git_tracked(path):
            logger.debug(f'Skipping non-tracked: {path}')
        else:
            res = self._load_input(path, l8funcs=l8funcs, readonly=_leaves_root(path, root))
        return res

    # def load_settings(self, path: str | Path | None = None):
    #     path = Path(path or '')
    #     return self.load_input(path / 'resources' / 'settings.xml')

    def load_translate(self, path: str | Path, *, base: bool = False) -> GenerateStats:
        """Load PO file `path` (`base`: base language, `#:` style is derived from it) and keep data."""
        pofile = polib.pofile(path)
        if base and self.locations is None:
            occurrences = [o for e in pofile for o in e.occurrences if ' ' not in o[0]]
            self.locations = 'line' if any(line for _, line in occurrences) else 'file' if occurrences else 'none'
            self._location_prefix = '/' if sum(f.startswith('/') for f, _ in occurrences) * 2 > len(occurrences) else ''
        was_obsolete = 0
        # active entries first: an obsolete entry (old text of the ID, e.g. kept by Weblate) doesn't define the ID
        # when the ID is known, otherwise it would look like an edit of the text (B27)
        for entry in sorted(pofile, key=lambda e: e.obsolete):
            text = entry.msgid
            if self._RE_LABEL_NUM.fullmatch(text) and '[empty]' in entry.comment:
                text = None
            if (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is None:
                label = Label(None, text, ctx=self._entry_ctx(entry))
            else:
                lid = int(r.group(1))
                if entry.obsolete and lid in self._by_id:
                    was_obsolete += 1
                    continue
                label = Label(lid, text, ctx=self._entry_ctx(entry))
            self._add_label(label, used=False)
            if entry.obsolete:
                was_obsolete += 1
        return GenerateStats(new=0, moved=0, obsolete=was_obsolete)

    def scan(self):
        """Scan all loaded XML files."""
        # 1. translations (strings.po) must be loaded
        # 2. scan current inputs (xml)
        # 3. merge id and text labels
        ...  # TODO: do it – for sure? I don't think so.

    def _rename_orphan_ids(self) -> None:
        """Reuse existing IDs whose old text is no longer referenced.

        For each pending new label (`label.id is None, label.ref is L1`):
          - if L1's old text has no remaining source references (`L1.nodes`
            empty),
          - and the new text isn't already claimed by another concrete ID,
          then take L1's ID for the new text instead of generating a new one.
        Renames are recorded in `_renamed_ids` so `translate()` can update
        the matching `msgid` in each language PO (translation becomes fuzzy).
        """
        for new_key, lst in list(self._by_text.items()):
            for label in list(lst):
                if label.id is not None or label.ref is None:
                    continue
                L1 = label.ref
                # Guard: a `ref` is only set in `_add_label` when L1 had a
                # non-empty text and an id — defensively narrow types here.
                if L1.id is None or L1.text is None:
                    continue
                if L1.referenced or L1.id in self._refs:
                    continue                  # 'old' still referenced (also by number), it's a collision, not an edit
                # Don't rename onto a text that already has its own concrete ID.
                if any(lb.id is not None and lb is not label for lb in lst):
                    continue
                old_key = L1.key
                old_id: int = L1.id
                # 1. Remove L1 from _by_text[old_key].
                old_lst = self._by_text.get(old_key)
                if old_lst is not None and L1 in old_lst:
                    old_lst.remove(L1)
                    if not old_lst:
                        del self._by_text[old_key]
                # 2. Rename L1 in place — it keeps its id, gets the new text (and context)
                #    and absorbs the pending label's nodes/trans.
                L1.ctx, L1.text = new_key
                L1.nodes |= label.nodes
                L1.trans.extend(label.trans)
                L1.ref = None
                # 3. Replace the pending label in lst with L1, mark resolved.
                lst[lst.index(label)] = L1
                label.id = old_id
                label.ref = L1
                self._renamed_ids[old_id] = new_key
                if self.dry_run:
                    print(f' rename id: {old_id}: {old_key[1]!r} → {new_key[1]!r}')

    def _readonly_path(self, use: NodeValue | Trans) -> Path | None:
        """Path of the read-only source of a label use (XML node or python L() occurrence), None if it is written."""
        if isinstance(use, Trans):
            if isinstance(use.file, PyInput):
                return use.file.path if use.file.readonly else None
            if not isinstance(use.file, XmlValueInput):
                return None
            use = use.file.node
        return self._readonly_roots.get(use.node.getroottree().getroot()) if self._readonly_roots else None

    def _drop_readonly_new(self) -> None:
        """New texts (no ID yet) used in read-only sources (B30) get no ID: their uses there are dropped, warned."""
        if not self._readonly_roots and not any(f.readonly for f in self.py_inputs):
            return
        dropped: dict[Path, list[str | None]] = {}
        for lst in self._by_text.values():
            for label in lst:
                if label.id is not None:
                    continue
                paths = {p for use in (*label.nodes, *label.trans) if (p := self._readonly_path(use)) is not None}
                if paths:
                    label.nodes = {n for n in label.nodes if self._readonly_path(n) is None}
                    label.trans = [tr for tr in label.trans if self._readonly_path(tr) is None]
                    for path in paths:
                        dropped.setdefault(path, []).append(label.text)
        for path, texts in sorted(dropped.items()):
            more = f', … (+{len(texts) - 3})' if len(texts) > 3 else ''
            logger.warning(f'{path}: {len(texts)} new text(s) not assigned, read-only source (symlink outside the addon): '
                           f'{", ".join(map(repr, texts[:3]))}{more}')

    def _compact(self) -> tuple[int, int]:
        """Renumber own IDs one after another from `id-from` (`--compact-ids`), return (moved IDs, new IDs).

        Order: used IDs (as they are), new texts (scan order), unused labels (only in PO; removed with
        `--obsolete remove`) — the same order next time, so a second run changes nothing.
        Kept in place: IDs used by number (`getLocalizedString(N)`, `$LOCALIZE[N]`, … — can't be rewritten), labels
        without text, IDs below `id-from`; their numbers (and `--id-reserve`, Kodi core references) are skipped.
        Translations move with the ID (PO entry renumbered in place, like `--id-reserve`).
        """
        edited = {lb.ref.id for lst in self._by_text.values() for lb in lst if lb.id is None and lb.ref is not None}
        paths = {inp.tree.getroot(): inp.path for inp in self.xml_inputs if not inp.readonly}

        def pinned(mid: int, label: Label) -> bool:
            """ID used by number somewhere kolang can't rewrite (XML number with the node attached is rewritten)."""
            if mid not in self._refs:
                return False
            nodes = {(paths.get(n.node.getroottree().getroot()), n.node.sourceline) for n in label.nodes}
            locations = self._ref_locations.get(mid, set())
            return not locations or any(loc not in nodes for loc in locations)

        own = sorted(mid for mid, lb in self._by_id.items() if mid >= self.id_from and lb.text and not pinned(mid, lb))
        used = [mid for mid in own if mid in self._ids or self._by_id[mid].referenced or mid in edited]
        unused = sorted(set(own) - set(used))
        new = [lb for lst in self._by_text.values() for lb in lst if lb.id is None and lb.referenced]
        orig = {new_id: old for old, new_id in self._moved_ids.items() if new_id is not None}  # `--id-reserve` moves first
        if self.obsolete is ObsoleteAction.REMOVE:
            for mid in unused:
                label = self._by_id.pop(mid)
                self._moved_ids[orig.get(mid, mid)] = None
                if self.dry_run:
                    print(f' remove id: {mid}: {label.text!r}')
            unused = []
        old_ids = set(used + unused)
        taken = (set(self._by_id) | self._ids) - old_ids
        slots = (n for n in count(self.id_from) if n not in taken and n not in self.reserved_ids)
        existing = [self._by_id[mid] for mid in used]
        renumbered: dict[int, int] = {}
        for label in (*existing, *new, *(self._by_id[mid] for mid in unused)):
            old, label.id = label.id, next(slots)
            if old is None:
                if label.id > self.id_max:
                    raise NoFreeIdError(f'No free label ID in {self.id_from}-{self.id_max} for new texts; raise --id-max')
                self._ids.add(label.id)
                if self.dry_run:
                    print(f' add id: {label.id}: {label.text!r}')
            elif label.id != old:
                renumbered[old] = label.id
                self._moved_ids[orig.get(old, old)] = label.id
                if old in self._ids:
                    self._ids.discard(old)
                    self._ids.add(label.id)
                if self.dry_run:
                    print(f' move id: {old} → {label.id}: {label.text!r}')
        rest = {mid: lb for mid, lb in self._by_id.items() if mid not in old_ids}
        moved = [self._by_id[mid] for mid in sorted(old_ids)]
        self._by_id.clear()
        self._by_id.update(rest)
        self._by_id.update((label.id, label) for label in (*moved, *new))
        # renamed in place (`_rename_orphan_ids`) before the renumbering: PO entry is found under its new ID
        self._renamed_ids = {renumbered.get(mid, mid): key for mid, key in self._renamed_ids.items()}
        return len(renumbered), len(new)

    def _add_text_refs(self) -> None:
        """`$LOCALIZE[N]` inside the text of a used label is a numeric reference too (kept, not renumbered)."""
        for lst in self._by_text.values():
            for label in lst:
                if label.text and '$LOCALIZE[' in label.text and (label.referenced or label.id in self._ids):
                    for m in self._RE_LOCALIZE.finditer(label.text):
                        if m['id']:
                            self._add_ref(int(m['id']))

    def generate(self) -> GenerateStats:
        """Generate new lables. Return number of new translations."""
        self._drop_readonly_new()
        self._add_text_refs()
        def nextid():
            nonlocal lidgen, wrapped
            # `max` policy: above the last used ID; when the top of the range is full, gaps from `id-from`
            for n in chain(range(lidgen, self.id_max + 1), range(self.id_from, lidgen)):
                # _ids holds numeric references to IDs declared elsewhere
                # (Kodi core, other addons) — must not be reassigned.
                if n not in self._by_id and n not in self._ids and n not in self.reserved_ids:
                    if n < lidgen and not wrapped:
                        wrapped = True
                        logger.warning(f'No free ID above #{lidgen} (id-max {self.id_max}), new IDs fill gaps from #{self.id_from}')
                    lidgen = n
                    return n
            unused = sum(1 for mid, lb in self._by_id.items()
                         if self.id_from <= mid <= self.id_max and not lb.referenced and mid not in self._ids)
            raise NoFreeIdError(f'No free label ID in {self.id_from}-{self.id_max}; raise --id-max, '
                                f'or free IDs: --obsolete remove ({unused} unused PO entries hold IDs), --compact-ids')

        was_obsolete = len(set(self._by_id) - self._ids)
        if self.skin:
            lo, hi = self.SKIN_ID_RANGE
            for mid in sorted(mid for mid in self._refs & self._by_id.keys() if not lo <= mid <= hi):
                where = ', '.join(f'{p}:{n}' for p, n in sorted(self._ref_locations.get(mid, ())))
                logger.warning(f'Skin string #{mid} is used by number ({where}), Kodi finds skin strings by number only in {lo}-{hi}')
        if self.id_policy == 'min':
            lidgen = self.id_from
        else:
            # only own range: references to Kodi core strings (e.g. `$LOCALIZE[38031]`) are above `id-max`
            lidgen = max((n for n in chain(self._by_id, self._ids) if self.id_from <= n <= self.id_max), default=self.id_from)

        wrapped = False
        new_trans_count = 0
        collision = sorted(set(self.reserved_ids.ids()) & self._by_id.keys())
        if refs := [mid for mid in collision if mid in self._refs]:
            # numeric reference in a reserved range points to the reserved ID, moving would break it silently
            logger.error(f'Reserved IDs used by number (getLocalizedString, $LOCALIZE, label="N"): {refs}, '
                         f'not moved; fix the references or the reserved range')
            sys.exit(1)
        for mid in collision:
            label = self._by_id.pop(mid)
            self._ids.discard(mid)
            if not label.referenced:  # only in PO, nothing to move, entry is removed
                self._moved_ids[mid] = None
                if self.dry_run:
                    print(f' remove id: {mid}: {label.text!r}')
                continue
            label.id = nextid()
            self._by_id[label.id] = label
            self._moved_ids[mid] = label.id
            if self.dry_run:
                print(f' move id: {mid} → {label.id}: {label.text!r}')
        if self.rename:
            self._rename_orphan_ids()
        compacted = 0
        if self.compact_ids:
            compacted, new_trans_count = self._compact()
        for lst in self._by_text.values():
            for label in lst:
                if label.id is None and label.referenced:  # text only in PO (ID-less entry) waits for use
                    new_trans_count += 1
                    label.id = nextid()
                    if self.dry_run:
                        print(f' add id: {label.id}: {label.text!r}')
                    best = self._by_id.setdefault(label.id, label)
                    if label is not best:
                        best.nodes |= label.nodes
                        best.trans.extend(label.trans)
                    self._ids.add(label.id)
        # Apply Trans first — they reference offsets in the *original* value.
        # `set_label` (next loop) overwrites the whole node.text/attr, so it
        # must run after Trans-based fragment edits.
        trans = sorted(((label, tr) for label in self._by_id.values() for tr in label.trans),
                       key=lambda x: -x[1].start)
        for label, tr in trans:
            assert label.id is not None
            tr.replace(label)
            self._ids.add(label.id)
        for label in self._by_id.values():
            assert label.id is not None
            for node in label.nodes:
                if not node.python:
                    self._ensure_L_comment(node, label)
                    node.set_label(str(label.id), addon=self.addon_id)
                    self._ids.add(label.id)
        if self.cleanup_translate_comments:
            removed = sum(self._cleanup_translate_comments_in(inp.tree) for inp in self.xml_inputs)
            if removed:
                logger.info(f'Cleaned up {removed} redundant :translate=false: comment(s)')
        return GenerateStats(new=new_trans_count, moved=len(collision) + compacted, obsolete=was_obsolete)

    def reset_ids(self, ref: str, po_path: Path) -> GenerateStats:
        """Remove IDs new on this branch (`--reset-ids REF`), they are assigned again after merge into `ref`.

        New IDs are IDs not in base language PO `po_path` at `git merge-base HEAD ref`. Sources get the text back
        (`L(30150, 'New')` → `L('New')`, XML value, `ctx` → `:context[…]=…:`), PO entries lose `msgctxt` in
        `translate()`, so translations wait for the new ID. Kept: IDs with numeric references (can't be found
        by text) and texts with another ID (would mix translations). No new IDs are assigned in this run.
        """
        self._drop_readonly_new()
        root = _git_root(po_path.parent if po_path.parent.exists() else Path.cwd())
        if root is None:
            logger.error(f'--reset-ids: {po_path} is not in a git repository')
            sys.exit(1)

        def git(*args: str) -> str:
            """Run git command in the repository, return stdout."""
            return subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True, check=True).stdout

        try:
            base = git('merge-base', 'HEAD', ref).strip()
        except subprocess.CalledProcessError as exc:
            logger.error(f'--reset-ids {ref}: {exc.stderr.strip() or "no merge base"}')
            sys.exit(1)
        try:
            text = git('show', f'{base}:{po_path.resolve().relative_to(root).as_posix()}')
        except subprocess.CalledProcessError:
            text = ''  # no PO at merge base, all IDs are new
        base_ids = {int(r['id']) for e in polib.pofile(text) if (r := self._RE_LABEL_NUM.fullmatch(e.msgctxt or ''))} if text else set()
        reset: list[Label] = []
        for mid, label in sorted(self._by_id.items()):
            if mid in base_ids:
                continue
            if mid in self._refs or not label.text:
                print(f' keep id: {mid}: {label.text!r}, numeric reference')
            elif other := [lb.id for lb in self._by_text.get(label.key, ()) if lb is not label and lb.id is not None]:
                print(f' keep id: {mid}: {label.text!r}, the same text has ID {other[0]}')
            else:
                print(f' reset id: {mid}: {label.text!r}')
                reset.append(label)
        # Python `L(ID, …)`: from the end, offsets are in the original value; the same occurrence can be twice in trans
        spans = {(id(tr.file), tr.start): (lb, tr) for lb in reset for tr in lb.trans if tr.id_end is not None}
        for label, tr in sorted(spans.values(), key=lambda x: -x[1].start):
            dc_replace(tr, end=tr.id_end).replace(label, fmt='{before}{after}')
        for label in reset:
            assert label.id is not None and label.text is not None
            for node in label.nodes:
                if node.python:
                    continue
                if node.trans and node.attr is None and self._RE_ADDON.fullmatch(node.node.text or ''):
                    node.node.text = label.text  # whole `$ADDON[addon ID]` was a plain label
                else:
                    node.set_label(label.text)
                self._reset_L_comment(node, label.ctx)
            del self._by_id[label.id]
            self._ids.discard(label.id)
            self._reset_ids.add(label.id)
            label.id = None
        if reset:
            print(f'IDs reset: {len(reset)}, after merge into {ref} run kolang there to assign them again')
        return GenerateStats(new=0, obsolete=len(set(self._by_id) - self._ids))

    @staticmethod
    def _reset_L_comment(node_value: NodeValue, ctx: str) -> None:
        """Remove `L()` comment of `node_value` target (`--reset-ids`), context goes to `:context[…]=…:`."""
        target = _node_value_target(node_value)
        prev = node_value.node.getprevious()
        while isinstance(prev, etree._Comment):
            parsed = _parse_L_comment(prev.text or '')
            if parsed is not None and parsed[0] == target:
                if ctx:
                    prev.text = f' :context[{target or ""}]={ctx}: '
                elif (parent := prev.getparent()) is not None:
                    parent.remove(prev)
                return
            prev = prev.getprevious()

    def write(self):
        for input in self.xml_inputs:
            self._write_xml(input)
        for input in self.py_inputs:
            self._write_py(input)

    def _prepare_write_target(self, path: Path, *, base: Path | None) -> Path:
        if self.backup_pattern == '+':
            # write as new file
            return path.with_suffix(path.suffix + '.new')
        # backup and override
        if self.backup_pattern and self.backup_pattern != '{}':
            if base is None:
                base = path.parent
            else:
                base = base.resolve()
            try:
                relative = path.relative_to(base)
            except ValueError:
                relative = Path()
            pat = self.backup_pattern
            if '/' not in pat and '\\' not in pat:
                pat = f'{{folder}}/{pat}'
            bak = Path(pat.format(path.name, path=path, name=path.name, ext=path.suffix[1:],
                                  directory=path.parent, folder=path.parent,
                                  base=base, addon=base, relative=relative))
            # if not bak.is_relative_to(path.parent):
            #     ValueError('Backup path {bak} is outsiede of source {path}')
            root = _git_root(path) if shutil.which('git') else None
            if root is not None:
                if root not in self._git_clean_by_repo:
                    self._git_clean_by_repo[root] = _git_clean_files(root)
                if path in self._git_clean_by_repo[root]:
                    return path  # git restores it, no backup
            path.rename(bak)
            if root is not None and not self._backup_ignore_checked:
                self._backup_ignore_checked = True
                if subprocess.run(['git', 'check-ignore', '-q', str(bak)], cwd=str(root)).returncode == 1:
                    logger.warning(f'Backup {bak} is not ignored by git, add its pattern to .gitignore (e.g. "*~")')
        return path

    def _restore_start_tags(self, input: XmlInput, body: str) -> str:
        """Put back original start tags (lxml joins multi-line tags), with changed attribute values patched in place."""
        elems = iter(input.tree.iter(etree.Element))

        def restore(m: re.Match) -> str:
            new = m['tag']
            if not new:
                return m[0]
            old = input.start_tags.get(next(elems, None))
            if old is None or old == new or old.endswith('/>') != new.endswith('/>'):
                return new
            new_attrs = dict(self._RE_XML_ATTR.findall(new))
            if [a for a, _ in self._RE_XML_ATTR.findall(old)] != list(new_attrs):
                return new  # attribute added, removed or reordered
            return self._RE_XML_ATTR.sub(lambda a: a[0] if a[2][1:-1] == new_attrs[a[1]][1:-1] else f'{a[1]}={new_attrs[a[1]]}', old)

        return self._RE_XML_START_TAG.sub(restore, body)

    def _write_xml(self, input):
        decl = input.declaration or ''
        encoding = input.encoding

        def entity(m: re.Match) -> str:
            code = ord(m[0])
            return f'&#x{code:04x};'
        body = etree.tostring(input.tree, encoding=encoding, xml_declaration=False).decode(encoding)
        if input.start_tags:
            body = self._restore_start_tags(input, body)
        data = re.sub(r'[\u2000-\u200f]', entity, decl + body).encode(encoding)
        if input.readonly:
            if data != input.original:
                logger.warning(f'Not written: {input.path} -> {input.path.resolve()} (symlink outside the addon)')
            return
        if data != input.original:
            self.changed.append(input.path)
        if self.dry_run:
            logger.debug(f'Write xml: {input.path.resolve()}')
            if (logger.level or logging.root.level) <= logging.DEBUG - 2:
                # etree.indent(input.tree)
                debug_print(decl + etree.tostring(input.tree, xml_declaration=False).decode())
            if self.dump_output:
                body = etree.tostring(input.tree, encoding=encoding, xml_declaration=False)
                print((decl.encode(encoding) + body).decode(encoding))
        elif data != input.original:
            path = self._prepare_write_target(input.path.resolve(), base=input.base)
            path.write_bytes(data)

    def _write_py(self, input):
        if input.readonly:
            if input.data != input.original:
                logger.warning(f'Not written: {input.path} -> {input.path.resolve()} (symlink outside the addon)')
            return
        if input.data != input.original:
            self.changed.append(input.path)
        if self.dry_run:
            logger.debug(f'Write py:  {input.path.resolve()}')
            if self.dump_output:
                print(input.data)
        elif input.data != input.original:
            path = self._prepare_write_target(input.path.resolve(), base=input.base)
            with open(path, 'w', encoding=self.encoding, newline='') as f:
                f.write(input.data)

    def _write_locations(self, po: polib.POFile) -> None:
        """Set `#:` references of active entries from sources: existing ones kept in their order (no diff noise),
        new ones appended sorted, gone ones removed; free text in `#:` (Kodi files) moves to `#.` comment."""
        for entry in po:
            if entry.obsolete:
                continue
            # `#:` line read as one item (B24): more paths (xgettext style) or free text (a word without `/` or `.`)
            free, occurrences = [], []
            for f, line in entry.occurrences:
                if ' ' not in f:
                    occurrences.append((f, line))
                elif all('/' in t or '.' in t for t in f.split()):
                    occurrences += [(t, '') for t in f.split()]
                else:
                    free.append(f)
            if free:
                entry.comment = '\n'.join(filter(None, (entry.comment, *free)))
            used = []
            mid = int(r['id']) if (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None else None
            for path, line in self._locations.get(self._entry_key(entry), set()) | self._ref_locations.get(mid, set()):
                try:
                    rel = path.resolve().relative_to(self.root.resolve()) if self.root else path
                except ValueError:
                    rel = path
                used.append((f'{self._location_prefix}{rel.as_posix()}', str(line) if self.locations == 'line' and line else ''))
            new = set(used)
            kept = list(dict.fromkeys(o for o in occurrences if o in new))
            entry.occurrences = kept + sorted(new - set(kept))

    @classmethod
    def _entry_ctx(cls, entry: polib.POEntry) -> str:
        """Return text context of PO `entry` (`#. context: …` line), empty if none."""
        return next((m['ctx'] for ln in entry.comment.split('\n') if (m := cls._RE_CONTEXT_NOTE.fullmatch(ln))), '')

    @classmethod
    def _entry_key(cls, entry: polib.POEntry) -> tuple[str, str]:
        """Return identity of PO `entry` text: (context, msgid), like `Label.key`."""
        return cls._entry_ctx(entry), entry.msgid

    @classmethod
    def _set_entry_ctx(cls, entry: polib.POEntry, ctx: str) -> None:
        """Set (or remove if empty) `#. context: …` line of PO `entry`, the first `#.` line."""
        lines = [ln for ln in entry.comment.split('\n') if ln and not cls._RE_CONTEXT_NOTE.fullmatch(ln)]
        entry.comment = '\n'.join([f'context: {ctx}'] * bool(ctx) + lines)

    @staticmethod
    def _carry_translation(entry: polib.POEntry, old_msgid: str, old_msgstr: str, previous_msgid: str | None) -> None:
        """Carry translation of edited text `old_msgid` to `entry` as fuzzy with `#| msgid` (the last reviewed text).

        A copy of the text (base language, `--mark-translated`) is not a translation, it follows the new text.
        """
        if not old_msgstr:
            return
        if old_msgstr == old_msgid:
            entry.msgstr = entry.msgid
            return
        entry.msgstr = old_msgstr
        entry.previous_msgid = previous_msgid or old_msgid
        entry.fuzzy = True

    @staticmethod
    def _format_fields(text: str) -> set[str]:
        """Return placeholder names of `str.format()` in `text`, raise ValueError on broken format."""
        return {re.split(r'[.\[]', name)[0] for _, name, _, _ in string.Formatter().parse(text) if name is not None}

    def _nplurals(self, lang: str, po: polib.POFile) -> int:
        """Return number of plural forms of the language (PO header, kolang table), 0 if unknown."""
        rule = po.metadata.get('Plural-Forms') or self.lang_plural_forms(lang) or self.DEF_PLURAL_FORMS
        return int(mch[1]) if (mch := re.search(r'nplurals\s*=\s*(\d+)', rule)) else 0

    #: Numbers to compare plural rules on (covers `% 100` rules).
    PLURAL_CHECK_RANGE: range = range(1000)

    def _check_plural_header(self, lang: str, path: Path, po: polib.POFile) -> None:
        """Warn on `Plural-Forms` of the PO header that runtime `L()` can't use or that differs from the expected one.

        Expected: what kolang writes into a new PO (`po-header` from the config, the kolang table); unknown language
        (no table entry) isn't compared.
        """
        header = po.metadata.get('Plural-Forms', '')
        try:
            nplurals, rule = _parse_plural_forms(header)
        except ValueError as exc:
            logger.warning(f'{path}: Plural-Forms {header!r} is incorrect ({exc}), '
                           f'runtime L() uses gettext default n != 1')
            return
        used = {rule(n) for n in self.PLURAL_CHECK_RANGE}
        if max(used) >= nplurals or len(used) < nplurals:
            logger.warning(f'{path}: Plural-Forms {header!r} is inconsistent, nplurals={nplurals} but plural gives '
                           f'forms {sorted(used)}')
        expected = self.po_header.get('Plural-Forms') or self.lang_plural_forms(lang)
        if not expected or expected == header:
            return
        try:
            exp_nplurals, exp_rule = _parse_plural_forms(expected)
        except ValueError:
            return
        diff = next((n for n in self.PLURAL_CHECK_RANGE if rule(n) != exp_rule(n)), None)
        if exp_nplurals != nplurals or diff is not None:
            at = f', n={diff} → form {rule(diff)}, expected {exp_rule(diff)}' if diff is not None else ''
            logger.warning(f'{path}: Plural-Forms {header!r} differs from {expected!r} ({lang}){at}; '
                           f'fix the PO header')

    def _check_translations(self, lang: str, path: Path, po: polib.POFile) -> None:
        """Warn on translations broken at runtime: plural header, wrong number of `|||` forms, placeholders."""
        self._check_plural_header(lang, path, po)
        nplurals = self._nplurals(lang, po)
        for entry in po:
            if entry.obsolete or not entry.msgstr:
                continue
            where = f'{path}: {entry.msgctxt} {entry.msgid!r}'
            if nplurals and '|||' in entry.msgid and (count := entry.msgstr.count('|||') + 1) != nplurals:
                logger.warning(f'{where}: {count} plural forms, {lang} needs {nplurals}')
            try:
                fields = self._format_fields(entry.msgstr)
            except ValueError as exc:
                logger.warning(f'{where}: invalid format in {entry.msgstr!r}: {exc}')
                continue
            try:
                expected = self._format_fields(entry.msgid)
            except ValueError:
                continue  # source text is not a format string
            problems = []
            if extra := fields - expected:
                problems.append(f'{" ".join(f"{{{f}}}" for f in sorted(extra))} not in msgid')
            if missing := expected - fields:
                problems.append(f'{" ".join(f"{{{f}}}" for f in sorted(missing))} missing')
            if problems:
                logger.warning(f'{where}: placeholders {", ".join(problems)}')

    def translate(self, lang: str, path: str | Path, *,
                  stats: GenerateStats | None = None, old_stats: GenerateStats | None) -> None:
        """Translate to `lang` and write to `path` (or `strings.po` in current dir if None)."""
        path = Path(path)
        if self.dry_run:
            if not path.parent.exists():
                logger.debug(f'Make dir:  {path.parent}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
        now = local_now()
        polib._BaseEntry.SPLIT_LINES = self.multi_line_msg
        if path.exists():
            po = polib.pofile(path, wrapwidth=self.po_wrap_width)
        else:
            po = polib.POFile(wrapwidth=self.po_wrap_width)
        if not po.header.strip():
            po.header = self._header_comment
        # Missing header fields (also in existing files, Kodi ignores the header, msgfmt and PO editors need it):
        # .kolang.json `po-header`, addon.xml, defaults.
        header = {
            'Project-Id-Version': '1.0',
            'Report-Msgid-Bugs-To': 'dev@kodi-pl.net',
            'POT-Creation-Date': f'{now:%Y-%m-%d %H:%M:%S%z}',
            'PO-Revision-Date': f'{now:%Y-%m-%d %H:%M:%S%z}',
            'Last-Translator': 'KodiPL Team <dev@kodi-pl.net>',
            'Language-Team': '{language}',
            'Language': lang,
            'MIME-Version': '1.0',
            'Content-Type': 'text/plain; charset=utf-8',
            'Content-Transfer-Encoding': '8bit',
            'Plural-Forms': self.lang_plural_forms(lang) or self.DEF_PLURAL_FORMS,
            **self._addon_header,
            **self.po_header,
        }
        for key, value in header.items():
            if not po.metadata.get(key):
                po.metadata[key] = str(value).replace('{language}', self.lang_name(lang))
        # active entry wins over an obsolete one with the same ID (old text kept by Weblate)
        ie = {int(r['id']): e for e in sorted(po, key=lambda e: not e.obsolete)
              if (r := self._RE_LABEL_NUM.fullmatch(e.msgctxt or '')) is not None}
        # `--reset-ids`: ID removed, translation waits in an entry without ID (Kodi ignores it) for a new ID
        for mid in self._reset_ids & ie.keys():
            ie.pop(mid).msgctxt = None
        pending = {self._entry_key(e): e for e in po if not e.msgctxt and e.msgid}
        # `--id-reserve` / `--compact-ids`: entry of a moved ID is renumbered (translation, flags and comments stay);
        # all moved entries out first, a new ID can be the old ID of another moved entry (compact)
        moved = {new_id: entry for old_id, new_id in self._moved_ids.items()
                 if new_id is not None and (entry := ie.pop(old_id, None)) is not None}
        for new_id, entry in moved.items():
            entry.msgctxt = f'#{new_id}'
            ie[new_id] = entry
        # old IDs no label has now (a new text can take an old ID in the same run): their entries go away
        stale = set(self._moved_ids) - self._by_id.keys()
        # Apply in-place renames: existing entries whose label was reused for
        # a new text (because old text became unreferenced).
        for old_id, new_key in self._renamed_ids.items():
            entry = ie.get(old_id)
            if entry is not None and self._entry_key(entry) != new_key:
                old_msgid, entry.msgid = entry.msgid, new_key[1]
                self._set_entry_ctx(entry, new_key[0])
                self._carry_translation(entry, old_msgid, entry.msgstr, entry.previous_msgid)
        # Entries out of sync with the model (other msgid under the ID, e.g. language PO files renumbered
        # differently by the merge driver or edited by hand): translation moves to the ID of its text.
        misplaced: dict[tuple[str, str], polib.POEntry] = {}
        for mid, entry in ie.items():
            label = self._by_id.get(mid)
            if label is not None and label.text and self._entry_key(entry) != label.key and not entry.obsolete:
                logger.warning(f'{path}: #{mid} msgid {self._entry_key(entry)!r} != {label.key!r}, realign translation by text')
                misplaced[self._entry_key(entry)] = polib.POEntry(msgid=entry.msgid, msgstr=entry.msgstr, flags=list(entry.flags),
                                                                  previous_msgid=entry.previous_msgid)
                entry.msgid, entry.msgstr, entry.flags, entry.previous_msgid = label.text, '', [], None
                self._set_entry_ctx(entry, label.ctx)
        for mid, entry in ie.items():
            if (old := misplaced.pop(self._entry_key(entry), None)) is not None:
                entry.msgstr, entry.flags, entry.previous_msgid = old.msgstr, old.flags, old.previous_msgid
        for label in self._by_id.values():
            assert label.id is not None
            if label.id not in ie:
                comment = []
                if not label.text:
                    comment.append('[empty]')
                entry = polib.POEntry(
                    msgctxt=f'#{label.id}',
                    msgid=label.text or f'#{label.id}',
                    comment=' '.join(comment),
                    # occurrences=[('welcome.py', '12'), ('anotherfile.py', '34')]
                )
                self._set_entry_ctx(entry, label.ctx)
                # edited text, not a collision: old text is unreferenced or renamed by another edit (`#|` keeps it);
                # split: the same text with another context (meaning) gets a copy of the translation to review
                if (old := misplaced.pop(label.key, None)) is not None:
                    entry.msgstr, entry.flags, entry.previous_msgid = old.msgstr, old.flags, old.previous_msgid
                elif (label.ref is not None and label.ref.id in ie
                      and ((not label.ref.referenced and label.ref.id not in self._refs) or label.ref.id in self._renamed_ids
                           or label.ref.text == label.text)):
                    old = ie[label.ref.id]
                    self._carry_translation(entry, old.msgid, old.msgstr, old.previous_msgid)
                po.append(entry)
                ie[label.id] = entry
        # Translation waiting without ID (`--reset-ids`, merged from a branch) goes to the ID of its text,
        # unless the ID entry has its own translation.
        for label in self._by_id.values():
            if (old := pending.pop(label.key, None)) is not None and (entry := ie.get(label.id)) is not None:
                if not entry.msgstr:
                    entry.msgstr, entry.flags, entry.previous_msgid = old.msgstr, list(old.flags), old.previous_msgid
                elif old.msgstr and old.msgstr != entry.msgstr:
                    logger.warning(f'{path}: #{label.id} {label.text!r}: translation {old.msgstr!r} without ID dropped, '
                                   f'{entry.msgstr!r} kept')
                po.remove(old)
        # Translations moved away from an ID with no text to go to: keep them without ID.
        for key, old in misplaced.items():
            if key not in pending:
                self._set_entry_ctx(old, key[0])
                po.append(old)
                pending[key] = old
        # Texts without ID (`--reset-ids` run): entry without ID, so translators can translate them already.
        for lst in self._by_text.values():
            for label in lst:
                if label.id is None and label.referenced and label.ref is None and label.text and label.key not in pending:
                    entry = polib.POEntry(msgid=label.text)
                    self._set_entry_ctx(entry, label.ctx)
                    po.append(entry)
                    pending[label.key] = entry
        waiting = {lb.key for lst in self._by_text.values() for lb in lst if lb.id is None and lb.referenced}
        for key, entry in pending.items():
            if key in waiting:
                entry.obsolete = False
            elif self.obsolete is ObsoleteAction.MARK:
                entry.obsolete = True
            elif self.obsolete is ObsoleteAction.REMOVE:
                po.remove(entry)
        # fake translate: copy all EN entries as translated texts
        if self.mark_translated:
            for entry in po:
                if not entry.obsolete and not entry.msgstr:
                    entry.msgstr = entry.msgid
        # remove obsolete flag if ID used again
        for entry in po:
            if entry.obsolete and (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None:
                mid = int(r.group('id'))
                if mid in self._ids and ie.get(mid) is entry:
                    entry.obsolete = False
        # mark obsolete if ID is not used in XML nor PY (but skip if moved)
        if self.obsolete is ObsoleteAction.MARK:
            for entry in po:
                if (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None:
                    mid = int(r.group('id'))
                    if mid not in self._ids and mid not in stale:
                        entry.obsolete = True
        elif self.obsolete is ObsoleteAction.REMOVE:
            to_remove = [i for i, entry in enumerate(po)
                         if ((mch := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None
                             and ((mid := int(mch.group('id'))) in stale or mid not in self._ids))]
            for i in reversed(to_remove):
                del po[i]
        if self._moved_ids:
            # the entry of each live ID stays; other ones with a moved ID (removed labels, obsolete duplicates) go away
            kept = {id(e) for mid, e in ie.items() if mid in self._by_id}
            to_remove = [i for i, entry in enumerate(po)
                         if ((mch := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None
                             and int(mch.group('id')) in self._moved_ids and id(entry) not in kept)]
            for i in reversed(to_remove):
                del po[i]
        for entry in po:
            # placeholders in msgid → msgfmt -c and PO editors check them in translations
            try:
                has_fields = bool(self._format_fields(entry.msgid))
            except ValueError:
                has_fields = False
            if has_fields and 'python-brace-format' not in entry.flags:
                entry.flags.append('python-brace-format')
            elif not has_fields and 'python-brace-format' in entry.flags:
                entry.flags.remove('python-brace-format')
        if self.locations in ('file', 'line'):
            self._write_locations(po)
        # `#.` comment for translators on plural entries (kolang line is replaced, the rest of the comment kept)
        nplurals = self._nplurals(lang, po)
        plural_note = f'{nplurals} plural form{"s" if nplurals != 1 else ""} separated by |||'
        for entry in po:
            lines = [ln for ln in entry.comment.split('\n')
                     if ln and not self._RE_PLURAL_NOTE.fullmatch(ln) and not _RE_TRANSLATORS.match(ln)]
            if nplurals and '|||' in entry.msgid and not entry.obsolete:
                lines.append(plural_note)
            # `#. Translators: …` from sources after the context line
            notes = [] if entry.obsolete else [f'Translators: {note}' for note in self._notes.get(self._entry_key(entry), ())]
            at = 1 if lines and self._RE_CONTEXT_NOTE.fullmatch(lines[0]) else 0
            entry.comment = '\n'.join(lines[:at] + notes + lines[at:])
        self._check_translations(lang, path, po)
        for entry in po:
            if entry.obsolete or not entry.msgctxt:
                continue
            if 'fuzzy' in self.list_entries and entry.msgstr and entry.fuzzy:
                was = f' (was {entry.previous_msgid!r})' if entry.previous_msgid else ''
                print(f'{lang} fuzzy {entry.msgctxt} {entry.msgid!r}{was}: {entry.msgstr!r}')
            elif 'untranslated' in self.list_entries and not entry.msgstr and lang != BASE_LANG:
                print(f'{lang} untranslated {entry.msgctxt} {entry.msgid!r}')
        if self.stats:
            N = sum(1 for e in po if not e.obsolete)
            ob = len(set(self._by_id) - self._ids)
            # nw = len(self._ids) - len(ie)
            nw = mv = ''
            if stats:
                if old_stats and ob != old_stats.obsolete:
                    ob = f'{ob} ({ob - old_stats.obsolete:+})'
                nw = f', new: {stats.new}'
                if stats.moved:
                    mv = f', moved: {stats.moved}'
            tr = sum(1 for e in po if e.msgstr and not e.fuzzy and not e.obsolete)
            fz = sum(1 for e in po if e.msgstr and e.fuzzy and not e.obsolete)
            if fz:
                mv += f', fuzzy: {fz}'
            if pd := sum(1 for e in po if not e.msgctxt and not e.obsolete):
                mv += f', pending: {pd}'
            if lang == BASE_LANG:
                print(f'Language {lang}: translated: ---- ({tr}/{N}), obsolete: {ob}{nw}{mv}')
            else:
                percent = 100 * tr / (N or 1)
                percent = 0.0 if tr == 0 else 100.0 if tr == N else max(1.0, min(99.0, percent))
                print(f'Language {lang}: translated: {percent:3.0f}% ({tr}/{N}), obsolete: {ob}{nw}{mv}')
        if not path.exists() or path.read_text(encoding='utf-8').rstrip('\n') != po.__unicode__().rstrip('\n'):
            self.changed.append(path)
        if self.dry_run:
            logger.debug(f'Write po:  {path}')
            if (logger.level or logging.root.level) < logging.DEBUG:
                debug_print(po.__unicode__())
            if self.dump_translations and fnmatch(lang, self.dump_translations):
                print(po.__unicode__())
        else:
            po.save(path)

    @staticmethod
    def _skin_folders(path: Path) -> list[Path]:
        """Return XML folders of a skin addon: `<res folder=…>` of `xbmc.gui.skin` in addon.xml, `extras`, `shortcuts`."""
        if not (path / 'addon.xml').exists():
            return []
        folders = etree.parse(str(path / 'addon.xml')).xpath('//extension[@point="xbmc.gui.skin"]/res/@folder')
        if not folders:
            return []
        return [path / name for name in dict.fromkeys((*folders, 'extras', 'shortcuts'))]

    def _load_addon_id(self, path: Path) -> str | None:
        """Try to read addon ID from `path` (addon folder with addon.xml). Return ID if found, else None."""
        if (path / 'addon.xml').exists():
            atree = etree.parse(str(path / 'addon.xml'))
            aroot = atree.getroot()
            if aroot.tag == 'addon':
                if aroot.find('extension[@point="xbmc.gui.skin"]') is not None:
                    self.skin = True
                if not self._addon_header_loaded:
                    self._addon_header_loaded = True
                    info = {'Addon Name': aroot.get('name'), 'Addon id': aroot.get('id'), 'Addon Provider': aroot.get('provider-name')}
                    self._header_comment += ''.join(f'\n{k}: {v}' for k, v in info.items() if v)
                    meta = './/extension[@point="xbmc.addon.metadata"]/'
                    provider, email = aroot.get('provider-name'), aroot.findtext(f'{meta}email')
                    if provider:
                        self._addon_header['Last-Translator'] = f'{provider} <{email}>' if email else provider
                    if bugs := email or aroot.findtext(f'{meta}source'):
                        self._addon_header['Report-Msgid-Bugs-To'] = bugs
                return aroot.get('id')
        return None

    def load_addon_files(self, path: Path | str, *, addon_id: str | None = None) -> AddonConf:
        path = Path(path or '')
        paths: list[Path] = []
        settings_path = path / 'resources' / 'settings.xml'
        if settings_path.exists():
            paths.append(settings_path)
        else:
            logger.info(f'No settring.xml in addon {path!r}')
        paths.extend(path.glob('*.py'))
        for p in (
            path / 'resources' / 'lib',
            path / 'lib',
            path / 'resources' / 'skins',
            *self._skin_folders(path),
        ):
            if p.exists():
                paths.append(p)
        if addon_id is None:
            addon_id = self._load_addon_id(path)
        return AddonConf(id=addon_id or '', paths=paths)

    def load_addon_config(self, path: Path) -> AddonConf | None:
        """
        Load addon config from `path` (either addon folder or .kolang.json or path to kolang config) and return it.
        Return None if no config found (e.g. no .kolang.json in folder).
        """
        def l8paths(paths: list[str] | str | None) -> set[Path] | None:
            if not paths:
                return None
            if isinstance(paths, str):
                paths = [paths]
            return {p for pp in paths for p in base.glob(pp)}

        # cache config by resolved path to avoid re-reading for multiple sources in the same addon
        key = path.resolve()
        addon_id: str = ''
        if key in self._config_cache:
            return self._config_cache[key]
        # read default addon id from addon.xml
        if path.is_dir():
            base = path
            path = path / '.kolang.json'
        else:
            base = path.parent
        if (base / 'addon.xml').exists():
            addon_id = self._load_addon_id(base) or ''
            if self.addon_id is None:
                self.addon_id = addon_id
        # read options for config file
        if not path.exists():
            return None
        logger.debug(f'Reading config {path}')
        with open(path, encoding='utf8') as f:
            conf = json.load(f)
        options = dict(conf.get('options', {}))
        for attr in ('id-from', 'id-min', 'id-max', 'id-policy', 'mark-translated',
                     'backup-pattern', 'addon-id', 'po-wrap-width', 'encoding', 'multi-line-msg',
                     'git-only', 'extra-translate-attrs', 'extra-translate-tags', 'rename', 'po-header', 'locations'):
            if (val := options.pop(attr, None)) is not None and attr not in self._cli_options:
                setattr(self, attr.replace('-', '_'), val)
        # python-tags/python-attrs additively extend defaults (set semantics).
        for tag in options.pop('python-tags', ()):
            self.python_tags.add(tag)
        for entry in options.pop('python-attrs', ()):
            if isinstance(entry, str):
                self.python_attrs.add((None, entry))
            elif isinstance(entry, dict):
                name = entry.get('name')
                tags = entry.get('tags')
                if not name:
                    continue
                if not tags:
                    self.python_attrs.add((None, name))
                else:
                    for tag in tags:
                        self.python_attrs.add((tag, name))
        if (val := options.pop('mark-obsoleted', None)) is not None:
            logger.warning('Option "mark-obsoleted" is deprecated, use "obsolete" instead')
            self.obsolete = ObsoleteAction.MARK if val else ObsoleteAction.KEEP
        if val := options.pop('obsolete', None):
            self.obsolete = ObsoleteAction(val)
        if (val := options.pop('get-localized-string', None)) is not None:
            self.handle_getLocalizedString = bool(val)
        paths = []
        for source in conf.get('sources', []):
            if isinstance(source, str):
                source = {'path': source}
            if (addon := source.get('addon')):
                ac = self.load_addon_files(base / addon, addon_id=addon_id)
                paths.extend(ac.paths)
            elif (p := source.get('path')):
                p = base / Path(p)
                if p.exists():
                    paths.append(p)
                else:
                    logger.warning(f'Source {str(p)!r} does not exist')
            elif (p := source.get('glob')):
                p = Path(p)
                paths.extend((base / p.parent).glob(p.name))
        skip = {p for pp in conf.get('skip', []) for p in base.glob(pp)}
        langs = {self.lang_code(L) for L in conf.get('languages', ())}
        l8funcs = []
        for fitem in conf.get('localized-functions', []):
            if isinstance(fitem, str):
                fitem = {'name': fitem}
            ftype = fitem.get('type')
            if ftype:
                ftype = FuncType[ftype]
            if (pat := fitem.get('regex')):
                l8funcs.append(L8Func(pat, paths=l8paths(fitem.get('path'))))
            elif (name := fitem.get('name')):
                l8funcs.append(L8Func(re.escape(name), paths=l8paths(fitem.get('path'))))
        result = AddonConf(id=addon_id, paths=paths, langs=langs, skip=skip, l8funcs=l8funcs)
        self._config_cache[key] = result
        if options:
            logger.warning(f'Unknown config options in {path}: {", ".join(sorted(options.keys()))}')
        return result

    def load_addon(self, path, *, skip: set[Path] = set(), l8funcs: list[L8Func] | None = None) -> None:
        """Load addon from `path` and keep data. `path` can be either addon folder (with addon.xml) or config file (.kolang.json)."""
        if not (path / 'addon.xml').exists():
            logger.warning(f'Invalid addon folder {path!r}, no addon.xml')
        conf = self.load_addon_config(path)
        if conf is None:
            conf = self.load_addon_files(path)
        if (path / 'addon.xml').exists():
            # e.g. `kodi.context.item` menu `<label>30150</label>`: own string used by number
            for node in etree.parse(str(path / 'addon.xml')).iter('label'):
                if (node.text or '').strip().isdigit():
                    self._add_ref(int(node.text), path / 'addon.xml', node.sourceline)
        if conf is not None:
            # `load_addon_config` already sets self.addon_id from addon.xml; cover
            # the no-config path here so skin label scan stays enabled.
            if self.addon_id is None and conf.id:
                self.addon_id = conf.id
            skip = set(Path(s) for s in skip or ()) | conf.skip
            skip = {s.resolve() for s in skip}
            for p in conf.paths:
                self.load_input(p, skip=skip, l8funcs=l8funcs, root=path)


@overload
def unescape(text: str) -> str:  ...


@overload
def unescape(text: Literal[None]) -> None:  ...


def unescape(text: str | None) -> str | None:
    """Unescape string from Python source."""
    if text is None:
        return None
    return text.encode('latin-1', 'backslashreplace').decode('unicode-escape')


def process(inputs, *, args, langs=None, output=None):
    trans = Translate(dry_run=args.dry_run or args.check, dump_output=args.debug_cat_output,
                      dump_translations=args.debug_cat_translation, list_entries=args.list or (),
                      id_from=args.id_from, id_min=args.id_min, id_max=args.id_max,
                      id_policy=args.id_policy, addon_id=args.addon_id,
                      handle_getLocalizedString=args.gls, backup_pattern=args.backup_pattern,
                      mark_translated=args.mark_translated, multi_line_msg=args.multi_line_msg,
                      po_wrap_width=args.po_wrap_width, reserved_ids=args.id_reserve,
                      git_only=args.git_only,
                      cleanup_translate_comments=args.cleanup_translate_comments,
                      rename=args.rename, compact_ids=args.compact_ids,
                      )
    trans.skin = args.type == 'skin'
    if args.verbose:
        logging.basicConfig(level=args.verbose)
    else:
        logging.basicConfig()

    if args.config:
        trans.load_addon_config(args.config)
    langs = {trans.lang_code(L) for L in langs or ()}
    l8funcs = [L8Func(re.escape(name)) for name in args.localized_functions or ()]
    base = ''
    conf = None
    if not output:
        for path in inputs:
            path = Path(path).resolve()
            if path.is_dir() and (path / 'addon.xml').exists():
                base = path
                conf = trans.load_addon_config(path)
                if conf:
                    langs |= conf.langs
                    l8funcs += conf.l8funcs
                logger.info(f'Language storage is in {path}')
                break

    addon_type = 'resources/language/resource.language.{lang_lower}/strings.po'
    skin_type = 'language/resource.language.{lang_lower}/strings.po'
    atype = args.type
    output = Path(output or base)
    pattern = ''
    if output.is_dir():
        if atype == 'addon':
            pattern = addon_type
        elif atype == 'skin':
            pattern = skin_type
        else:
            if (output / 'language').is_dir():
                pattern = skin_type
            elif (output / 'resources' / 'language').is_dir():
                pattern = addon_type
            else:
                # pattern = 'resource.language.{lang_lower}/strings.po'
                logger.info("Unsure addon type, guess it's plugin/module")
                pattern = addon_type
        disk: set[str] = set()
        for lpath in output.glob(pattern.replace('{lang_lower}', '*')):
            lpath = lpath.resolve()
            pat = re.escape(pattern.replace('{lang_lower}', '__LANG__')).replace('__LANG__', '(.*?)').replace('/', r'[/\\]')
            r = re.fullmatch(fr'.*[/\\]{pat}', str(lpath))
            if r is not None:
                try:
                    disk.add(trans.lang_case(r.group(1)))
                except ValueError:
                    logger.warning(f'{lpath}: folder is not a language code, skipped')
    langs = _kodi_language_folders(langs, disk, pattern)

    was: dict[str, GenerateStats] = {}
    for lang in sorted(langs, key=lambda lang: (lang != BASE_LANG, lang)):  # base first: it wins if PO files are out of sync
        path = output
        if pattern:
            path = output / pattern.format(lang=lang, lang_lower=lang.lower())
        if path.exists():
            was[lang] = trans.load_translate(path, base=lang == BASE_LANG)

    for path in inputs:
        path = Path(path).absolute()  # not resolved: a symlinked file must be seen as a link (B30)
        if path.is_dir():
            path = path.resolve()
            if (path / 'addon.xml').exists():
                trans.load_addon(path, skip=args.skip, l8funcs=l8funcs)
            else:
                logger.warning(f'There is NOT an addon in {path}, skipping')
        else:
            trans.load_input(path, l8funcs=l8funcs)

    # override settings from command-line
    if args.obsolete is not None:
        trans.obsolete = args.obsolete

    # `--obsolete mark/remove` with nothing scanned would mark/remove every string (e.g. unknown source layout)
    if trans.obsolete is not ObsoleteAction.KEEP and not (trans.xml_inputs or trans.py_inputs):
        logger.error(f'No source file scanned, --obsolete {trans.obsolete.value} would make every string obsolete; '
                     f'check sources (addon layout, .kolang.json)')
        sys.exit(1)

    trans.root = Path(base) if base else Path.cwd()
    if args.locations is not None:
        trans.locations = args.locations

    # do the job
    trans.scan()
    if args.reset_ids:
        if not pattern:
            logger.error('--reset-ids needs an addon or skin directory (language PO files)')
            sys.exit(1)
        stats = trans.reset_ids(args.reset_ids, output / pattern.format(lang=BASE_LANG, lang_lower=BASE_LANG.lower()))
    else:
        if args.compact_ids and not trans.dry_run:
            po_files = [output / pattern.format(lang=lang, lang_lower=lang.lower()) if pattern else output for lang in langs]
            if dirty := trans.uncommitted([*(f.path for f in (*trans.xml_inputs, *trans.py_inputs) if not f.readonly),
                                           *(p for p in po_files if p.exists())]):
                logger.error(f'--compact-ids rewrites every source and PO file, commit first (git restores them): '
                             f'{", ".join(map(str, dirty[:5]))}{" …" if len(dirty) > 5 else ""}')
                sys.exit(1)
        try:
            stats = trans.generate()
        except NoFreeIdError as exc:
            logger.error(exc)
            sys.exit(1)
    if langs:
        trans.write()
    else:
        logger.warning('No languages defined, skip file writting. Use -L ...')

    for lang in sorted(langs):
        path = output
        if pattern:
            path = output / pattern.format(lang=lang, lang_lower=lang.lower())
        trans.translate(lang, path, stats=stats, old_stats=was.get(lang))
    if args.check:
        for path in trans.changed:
            print(f'would change: {path}')
        if trans.changed:
            sys.exit(1)


def copy_kolang_py(output: Path = Path(), *, backup_pattern: str | None = '{}~') -> None:
    """Write the runtime `L()` helper (`kolang.py`) into `output` (works from a package dir and from pyz).

    An existing different file is overwritten like any file kolang rewrites (backup unless git restores it).
    """
    from importlib.resources import files
    content = files(__package__).joinpath('kolang.py').read_text(encoding='utf8')
    output /= 'kolang.py'
    if output.exists():
        if output.read_text(encoding='utf8') == content:
            print(f'{output}: up to date')
            return
        print(f'{output}: updated')
        output = Translate(backup_pattern=backup_pattern)._prepare_write_target(output.resolve(), base=None)
    with open(output, 'w', encoding='utf8', newline='') as f:
        f.write(content)


def _kodi_language_folders(langs: set[str], disk: set[str], pattern: str) -> set[str]:
    """Return languages to write: configured `langs` and PO folders on `disk`, warn on folders Kodi doesn't load.

    Kodi loads `resource.language.<Kodi language ID>` only. A configured language without its folder, but with an
    existing folder of the same language that isn't a Kodi language (old kolang guess like `he_he`), keeps using it
    (no split of translations) until it's renamed.
    """
    def short(lang: str) -> str:
        code = re.split('[_@]', lang.lower())[0]
        return TranslateBase._LANG_ALIAS.get(code, code)

    folder = (pattern or 'resource.language.{lang_lower}/').partition('{lang_lower}')[0]
    on_disk = {d.lower() for d in disk}
    result = set(disk)
    kept: set[str] = set()
    for lang in sorted(langs):
        if lang.lower() not in on_disk and lang.lower() in KODI_LANGUAGES:
            if old := sorted(d for d in disk if short(d) == short(lang) and d.lower() not in KODI_LANGUAGES):
                kept.add(old[0])
                logger.warning(f'{folder}{old[0].lower()} is not a Kodi language folder, Kodi loads '
                               f'{folder}{lang.lower()} only; kept until renamed: '
                               f'git mv {folder}{old[0].lower()} {folder}{lang.lower()}')
                continue
        result.add(lang)
    for lang in sorted(result - kept):
        if lang.lower() not in KODI_LANGUAGES:
            logger.warning(f'{folder}{lang.lower()}: Kodi has no such language add-on, it never loads this PO')
    return result


def parse_lang_arg(ss: str) -> list[str]:
    """Parse comma separated language codes (`pl`, `pt_BR`, `sr_RS@latin`), raise ValueError on a malformed one."""
    ss = [s.strip() for s in ss.split(',') if s.strip()]
    for s in ss:
        TranslateBase.lang_case(s)
    return ss


def parse_ranges(ss):
    def make(v):
        if '-' in v:
            a, _, b = v.partition('-')
            return range(int(a), int(b)+1)
        if '#' in v:
            a, _, b = v.partition('#')
            return range(int(a), int(a) + int(b))
        return range(int(v), int(v) + 1)
    return ranges(make(v.strip()) for v in ss.split(','))


class ConstIncAction(argparse.Action):

    def __init__(self,
                 option_strings,
                 dest,
                 const=0,
                 default=None,
                 required=False,
                 help=None,
                 metavar=None,
                 inc=1):
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            const=const,
            default=default,
            required=required,
            help=help)
        self.inc = inc

    def __call__(self, parser, namespace, values, option_string=None):
        val = getattr(namespace, self.dest, None)
        if val is None:
            setattr(namespace, self.dest, self.const)
        else:
            setattr(namespace, self.dest, val + self.inc)


def merge_po(base: Path, ours: Path, theirs: Path) -> int:
    """Merge `theirs` PO into `ours` (git merge driver: %O %A %B), return number of translation conflicts.

    Entries are matched by ID (`msgctxt "#ID"`), text is (`#. context: …`, msgid). Same ID with a different text
    on both sides (both branches took the next free ID) is a collision: theirs entry goes to the ID its text already has in ours or gets
    a new free ID. Run kolang after the merge, it moves the colliding source labels to that ID (by text).
    Entries without ID (`--reset-ids`) are matched by text.
    Translations are merged 3-way against `base`; changed on both sides → conflict: ours is kept as fuzzy
    with theirs in a translator comment (the merge doesn't stop, kolang counts fuzzy entries).
    """
    def entries(po: polib.POFile) -> dict[int, polib.POEntry]:
        """Return entries with ID."""
        return {int(r['id']): e for e in po if (r := Translate._RE_LABEL_NUM.fullmatch(e.msgctxt or '')) is not None}

    key = Translate._entry_key

    def merge_msgstr(e: polib.POEntry, t: polib.POEntry, b: polib.POEntry | None) -> int:
        """Merge theirs msgstr into ours entry (same text), return 1 on conflict (ours fuzzy, theirs in comment)."""
        old = b.msgstr if b is not None and key(b) == key(e) else ''
        if t.msgstr in (e.msgstr, '', old):
            return 0
        if e.msgstr in ('', old):
            e.msgstr = t.msgstr
            return 0
        print(f'{ours}: {e.msgctxt} {e.msgid!r}: translation conflict, ours {e.msgstr!r} kept as fuzzy, theirs {t.msgstr!r}',
              file=sys.stderr)
        e.fuzzy = True
        e.tcomment = '\n'.join(filter(None, (e.tcomment, f'theirs: {t.msgstr}')))
        return 1

    polib._BaseEntry.SPLIT_LINES = False
    po_base, po_ours, po_theirs = (polib.pofile(str(p), wrapwidth=999999) for p in (base, ours, theirs))
    b_ids, o_ids, t_ids = entries(po_base), entries(po_ours), entries(po_theirs)
    o_text = {key(e): e for e in o_ids.values()}
    # New IDs are max+1, same in every language if all PO files have the same IDs (kolang writes them so),
    # otherwise kolang realigns translations by text on the next run.
    free = max(o_ids.keys() | t_ids.keys(), default=0) + 1
    conflicts = 0
    for mid, t in sorted(t_ids.items()):
        e, b = o_ids.get(mid), b_ids.get(mid)
        if e is None:
            po_ours.append(t)
        elif key(e) == key(t):
            conflicts += merge_msgstr(e, t, b)
        elif b is not None and key(b) == key(e):  # text edited in theirs only
            e.msgid, e.msgstr, e.comment = t.msgid, t.msgstr, t.comment
        elif b is not None and key(b) == key(t):  # text edited in ours only
            pass
        elif (e := o_text.get(key(t))) is not None:  # collision, text has an ID in ours
            conflicts += merge_msgstr(e, t, None)
        else:  # collision, new ID for theirs text
            t.msgctxt = f'#{free}'
            free += 1
            po_ours.append(t)
            o_text[key(t)] = t
    b_pend, o_pend = ({key(e): e for e in po if not e.msgctxt and e.msgid} for po in (po_base, po_ours))
    for k, t in ((key(t), t) for t in po_theirs if not t.msgctxt and t.msgid):
        if (e := o_pend.get(k)) is None:
            po_ours.append(t)
        else:
            conflicts += merge_msgstr(e, t, b_pend.get(k))
    po_ours.save(str(ours))
    return conflicts


#: Marker line of the post-merge hook written by `--git-setup` (an existing other hook is not overwritten).
GIT_HOOK_MARK: str = '# kolang post-merge hook'


def _kolang_command() -> str:
    """Return shell command running this kolang (pyz / script, or `python -m kolang` with PYTHONPATH)."""
    script = Path(sys.argv[0]).resolve()
    if script.name == '__main__.py':
        return f'PYTHONPATH={shlex.quote(str(script.parent.parent))} {shlex.quote(sys.executable)} -m kolang'
    return f'{shlex.quote(sys.executable)} {shlex.quote(str(script))}'


def git_setup(paths: list[Path]) -> None:
    """`--git-setup`: `.gitattributes` (strings.po merge=kolang), merge driver config, post-merge hook.

    The hook runs kolang on `paths` only on the default branch (`origin/HEAD`, else `main`): merging the default branch
    into a feature branch must not assign IDs there (B15). Changed files are listed, nothing is committed.
    """
    root = _git_root(paths[0].resolve())
    if root is None:
        logger.error(f'--git-setup: {paths[0]} is not in a git repository')
        sys.exit(1)

    def git(*args: str) -> str:
        """Run git in the repository, return stdout."""
        return subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True, check=True).stdout.strip()

    attrs = root / '.gitattributes'
    lines = attrs.read_text(encoding='utf-8').splitlines() if attrs.exists() else []
    if 'strings.po merge=kolang' not in lines:
        attrs.write_text('\n'.join([*lines, 'strings.po merge=kolang']) + '\n', encoding='utf-8')
        print(f'{attrs}: strings.po merge=kolang (commit it)')
    cmd = _kolang_command()
    git('config', 'merge.kolang.name', 'kolang strings.po merge driver')
    git('config', 'merge.kolang.driver', f'{cmd} --merge-po %O %A %B')
    print(f'git config merge.kolang.driver: {cmd} --merge-po %O %A %B')
    hook = root / git('rev-parse', '--git-path', 'hooks/post-merge')
    if hook.exists() and GIT_HOOK_MARK not in hook.read_text(encoding='utf-8', errors='replace'):
        logger.warning(f'{hook} exists and is not kolang\'s, not changed; add: {cmd} <addon>')
        return
    dirs = ' '.join(shlex.quote(os.path.relpath(p.resolve(), root)) for p in paths)
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f'''#!/bin/sh
{GIT_HOOK_MARK}: assign IDs of merged texts on the default branch only (written by kolang --git-setup)
default=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's@^origin/@@')
[ "$(git symbolic-ref --short HEAD 2>/dev/null)" = "${{default:-main}}" ] || exit 0
cd "$(git rev-parse --show-toplevel)" || exit 0
{cmd} {dirs} || exit 0
if [ -n "$(git status --porcelain -- {dirs})" ]; then
    echo "kolang: translations updated after merge, commit the result:"
    git status --short -- {dirs}
fi
''', encoding='utf-8')
    hook.chmod(0o755)
    print(f'{hook}: runs kolang on {dirs} after merge on the default branch')


def plural_expr(code: str) -> None:
    """Print plural rule of the language (`plural.py`) and its form index for n 0–30, like runtime `L()` (gettext)."""
    info = TranslateBase.plural_info(code)
    if info is None:
        logger.error(f'Unknown language {code!r}')
        sys.exit(1)
    print(f'{info.code} ({info.name}): {info.forms}')
    try:
        _nplurals, rule = _parse_plural_forms(info.forms)
    except ValueError as exc:
        logger.error(f'Incorrect plural rule: {exc}')
        sys.exit(1)
    for n in range(31):
        print(f'{n:3} → {rule(n)}')


def main(argv=None):
    p = argparse.ArgumentParser(description='Translate tool for Kodi XML (like gettext)')
    p.add_argument('--version', action='version', version=__version__)
    p.add_argument('--type', choices=('addon', 'skin'), help='add-on folder structure')
    p.add_argument('-t', '--translation', metavar='PATH', type=Path,
                   help='path string.po or folder with it or to resource folder, default "."')
    p.add_argument('-L', '--language', metavar='LANG', action='extend', type=parse_lang_arg,
                   help='new language like "en", "en_US", "pl"')
    p.add_argument('--mark-translated', action='store_true', help='copy original string to all non-translated entries')
    p.add_argument('--remove', action='store_const', const='remove', dest='obsolete',
                   help='remove unused translations (alias for --obsolete=remove)')
    p.add_argument('--id-from', metavar='NUM', type=int, default=None,
                   help=f'lowest label ID (start from) [{Translate.ID_FROM_DEFAULT}, skin {Translate.SKIN_ID_FROM_DEFAULT}]')
    p.add_argument('--id-min', metavar='NUM', type=int, default=None,
                   help=f'warn if any label ID is below NUM [--id-from, skin {Translate.SKIN_ID_RANGE[0]}]')
    p.add_argument('--id-max', metavar='NUM', type=int, default=None,
                   help=f'highest label ID for new entries [{Translate.ID_MAX_DEFAULT}, skin {Translate.SKIN_ID_RANGE[1]}]')
    p.add_argument('--id-policy', choices=('max', 'min'), default='max', help='new label ID policy [max]')
    p.add_argument('--id-reserve', metavar='ID[-ID]...', type=parse_ranges,
                   help='reserve IDs, move another to keep the range empty')
    p.add_argument('--get-localized-string', dest='gls', action='store_true', default=True,
                   help='handle getLocalizedString() [default]')
    p.add_argument('--no-get-localized-string', dest='gls', action='store_false',
                   help='skip getLocalizedString()')
    p.add_argument('-f', '--localized-function', dest='localized_functions', metavar='FUNC', action='append',
                   help='extra get-localized-string function name')
    p.add_argument('--addon-id', metavar='ADDON.ID', help='force addon id for $ADDON[]')
    p.add_argument('--no-addon-id', dest='addon_id', action='store_const', const=False,
                   help='disable addon id, skip $ADDON[]')
    p.add_argument('--obsolete', choices=('keep', 'mark', 'remove'),
                   help='what to do with obsolete/non-used translations [keep]')
    p.add_argument('-s', '--skip', metavar='PATH', action='append', help='skip path')
    p.add_argument('--backup-pattern', metavar='PATTERN', default='{}~', help='pattern for backup files [{}~]')
    p.add_argument('--no-backup-pattern', action='store_const', const=False, dest='backup_pattern',
                   help='no backup files')
    p.add_argument('--encoding', default='utf8', help='force files encoding [utf8]')
    p.add_argument('--po-wrap-width', metavar='WIDTH', default=999999, type=int, help='.po wrap width [999999]')
    p.add_argument('-c', '--config', type=Path, help='load config [ADDON/.kolang.json]')
    p.add_argument('--single-line-msg', action='store_false', dest='multi_line_msg',
                   help='write po messages in single line [default]')
    p.add_argument('--multi-line-msg', action='store_true', dest='multi_line_msg',
                   help='write po messages in many lines if \\n is used')
    p.set_defaults(multi_line_msg=False)
    p.add_argument('--git-only', action='store_true', default=False,
                   help='scan only files tracked by git (in the index)')
    p.add_argument('--no-rename', dest='rename', action='store_false', default=True,
                   help='disable in-place ID rename when text edits would otherwise '
                        'orphan an untranslated entry (default: rename when safe)')
    p.add_argument('--cleanup-translate-comments', action='store_true', default=False,
                   help='one-time cleanup: drop redundant :translate=false: XML comments')
    p.add_argument('--verbose', action='store_const', const=logging.INFO, help='be more verbose')
    p.add_argument('--debug', action=ConstIncAction, const=logging.DEBUG, inc=-1, dest='verbose',
                   help='be much more verbose')
    p.add_argument('--dry-run', action='store_true', help='do not modify anything')
    p.add_argument('--debug-cat-output', action='store_true', help='print output file if --dry-run')
    p.add_argument('--debug-cat-translation', metavar='LOCALE', help='print output translation if --dry-run')
    p.add_argument('--check', action='store_true',
                   help='write nothing, list files that would change, exit 1 if any (CI, hooks; with --reset-ids REF too)')
    p.add_argument('--git-setup', action='store_true',
                   help='set up git for PATH: .gitattributes + merge driver (--merge-po), post-merge hook running kolang '
                        'on the default branch')
    p.add_argument('--locations', choices=('none', 'file', 'line'),
                   help='`#:` references in PO: where texts are used [derived from the base language PO]')
    p.add_argument('--compact-ids', action='store_true',
                   help='renumber own IDs one after another from --id-from (translations move with them); IDs used by number '
                        'stay; needs committed sources and PO (git)')
    p.add_argument('--reset-ids', metavar='REF',
                   help='remove IDs new on this branch (not in PO at merge base with REF) before merge into REF, '
                        'translations wait in PO without ID; run kolang on REF after the merge')
    p.add_argument('--list', action='append', choices=('fuzzy', 'untranslated'),
                   help='list fuzzy or untranslated entries per language (repeatable), with --dry-run nothing is written')
    p.add_argument('--test-plural', help='test plural form and exit')
    p.add_argument('--generate-kolang-py', action='store_true',
                   help='generate kolang.py to use its L() in addon/plugin')
    p.add_argument('--merge-po', nargs=3, metavar=('BASE', 'OURS', 'THEIRS'), type=Path,
                   help='merge PO files into OURS and exit, git merge driver: "kolang --merge-po %%O %%A %%B"')
    p.add_argument('input', metavar='PATH', nargs='*', type=Path, help='path XML or PY file or addon folder')
    args = p.parse_args(argv)
    if args.merge_po:
        merge_po(*args.merge_po)
        return
    if args.test_plural:
        plural_expr(args.test_plural)
        return
    if not args.input:
        p.error('the following arguments are required: PATH')
    if args.obsolete is not None:
        args.obsolete = ObsoleteAction(args.obsolete)
    # print(args); exit()

    if args.generate_kolang_py:
        copy_kolang_py(args.input[0], backup_pattern=args.backup_pattern)
        return
    if args.git_setup:
        git_setup(args.input)
        return
    process(args.input, output=args.translation, langs=args.language, args=args)


if __name__ == '__main__':
    main()
