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
from dataclasses import dataclass, field
from itertools import chain
from typing import Union, Optional, Any, Literal, overload, TYPE_CHECKING
from pathlib import Path
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from fnmatch import fnmatch
import json
import argparse
if TYPE_CHECKING:
    from lxml import etree
    from lxml.etree import _ElementTree as ElementTree
    from lxml.etree import _Element as Element
    # from xml.etree.ElementTree import ElementTree
    # from xml.etree.Element import Element
else:
    try:
        # faster implementation
        from lxml import etree
    except ImportError:
        # standard implementation
        from xml.etree import ElementTree as etree
from . import polib
from .plural import plural_forms

import logging
import logging.config
logger = logging.Logger('kolang')


__author__ = 'rysson'
__version__ = '0.1.13'


# Monkey Patching

def _BaseFile_metadata_as_entry(self):
    entry = _real_BaseFile_metadata_as_entry(self)
    try:
        comment = self.metadata_comment
    except AttributeError:
        pass
    else:
        entry.comment = comment
    return entry


_real_BaseFile_metadata_as_entry = polib._BaseFile.metadata_as_entry
polib._BaseFile.metadata_as_entry = _BaseFile_metadata_as_entry


@dataclass(frozen=True)
class GenerateStats:
    new: int
    moved: int = 0
    obsolete: int = 0


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
    #: Funtion type (LL / getLocalizedString)
    type: FuncType = FuncType.GetLocalizedString
    #: Where this function is allowed.
    paths: set[Path] = None

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
    #: Paths to scan.
    paths: list[Path]
    #: Extra languages.
    langs: set[str] = field(default_factory=set)
    #: Paths to skip.
    skip: set[str] = field(default_factory=set)
    #: Extra python localzed function/method to detect.
    l8funcs: list[L8Func] = field(default_factory=list)


@dataclass(frozen=True)
class XmlInput:
    path: Path
    tree: ElementTree
    base: Path
    declaration: str = None


@dataclass
class PyInput:
    path: Path
    data: str = field(repr=False)
    base: Path

    def replace(self, fmt: str, label: Label, start: int, end: int) -> None:
        self.data = fmt.format(before=self.data[:start], after=self.data[end:], label=label)


@dataclass
class XmlValueInput:
    """Value in XML file, used only in PY in XML."""
    node: NodeValue

    def replace(self, fmt: str, label: Label, start: int, end: int) -> None:
        node = self.node.node
        if self.node.attr is None:
            text = node.text or ''
            node.text = fmt.format(before=text[:start], after=text[end:], label=label)
        else:
            text = node.get(self.node.attr, '')
            node.set(self.node.attr, fmt.format(before=text[:start], after=text[end:], label=label))


def local_now():
    tz = timezone(timedelta(seconds=round((datetime.now() - datetime.utcnow()).total_seconds())))
    return datetime.now(tz)


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


def node_error(node: Element, msg: Optional[str] = None) -> None:
    """Log XML node error."""
    try:
        lno: int = node.sourceline
        if msg:
            msg = f': {msg}'
        else:
            msg = ''
        logger.warning(f'Node {node.tag} (line {lno}) error{msg}')
    except AttributeError:
        logger.warning(f'Node {node.tag} error{msg}')


#: Source file (.py) translate info / translate in NodeValue
@dataclass(frozen=True)
class Trans:
    file: PyInput | XmlValueInput | None
    start: int
    end: int
    fmt: str = '{label.id}'

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
    trans: list[Trans] | None = None
    #: Python source node text ar attribute.
    python: bool = False

    def __getattr__(self, key):
        return getattr(self.node, key)

    def replace(self, text: str, value: str, *, addon: Optional[str] = None) -> str:
        for tr in self.trans or ():
            if tr.fmt is not None:
                value = tr.fmt.format(value=value, id=value, addon=addon)
            text = f'{text[:tr.start]}{value}{text[tr.end:]}'
        return text

    def set_label(self, value: str, addon: Optional[str] = None) -> None:
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

    DEF_LANG = {c.partition('_')[0]: c for c in (
        'sq_AL', 'ar_EG', 'be_BY', 'bn_IN', 'ca_ES', 'zh_CN', 'cs_CZ', 'da_DK', 'en_GB', 'et_EE',
        'el_GR', 'iw_IL', 'hi_IN', 'in_ID', 'ga_IE', 'ja_JP', 'ko_KR', 'ms_MY', 'sr_RS', 'sl_SI',
        'sv_SE', 'uk_UA', 'vi_VN')}

    @classmethod
    def lang_code(cls, code: str) -> str:
        """Return language code like "en_US". Try guess, ex "pl" -> "pl_PL"."""
        if '_' not in code:
            try:
                code = cls.DEF_LANG[code]
            except KeyError:
                code = f'{code.lower()}_{code.upper()}'
        return code


class Translate(TranslateBase):
    """Whole translate process handler."""

    DEF_PLURAL_FORMS = 'nplurals=2; plural=(n != 1);'
    # see
    # - https://doc.qt.io/archives/qq/qq19-plurals.html
    # - http://docs.translatehouse.org/projects/localization-guide/en/latest/l10n/pluralforms.html
    PLURAL_FORMS = {TranslateBase.lang_code(p.code): p.forms for p in plural_forms}

    _RE_LABEL_NUM = re.compile(r'#(?P<id>\d+)')
    _RE_READ_PO = re.compile(r'(?:^|\n)(?P<var>(?:msgctxt|msgid|msgstr))[ \t]*'
                             r'(?:[ \t]*[\n]"(?P<val>(?:\\.|[^"])*))+"')
    _RE_PO_VAL = re.compile(r'\s*"((?:\\.|[^"])*)"')
    _RE_LOCALIZE = re.compile(r'\$LOCALIZE\[(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|[^]])*))\]')
    _RE_ADDON = re.compile(r'\$ADDON\[(?:(?P<addon>[A-Za-z]\w*(?:\.\w+)+)\s+)?'
                           r'(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|[^]])*))\]')
    #                        r'(?:\s*(?P<id>\d+)\s*|(?P<text>(?:\[[^]*]|"[^"]*"|(?<!\$ADDON)[^]])*))\]')
    _RE_SKIP_LABEL = re.compile(r'\$(?:LOCALIZE|ADDON)\[')

    _RE_XML_DECL: re.Pattern = re.compile(r'''\s*<\?(?:"(?:\.|[^"])*"|'(?:\.|[^'])*'|[^>])*>\s*''')

    def __init__(self, *,
                 dry_run: bool = False,
                 dump_output: bool = False,
                 dump_translations: str | None = None,
                 stats: bool = True,
                 id_from: int = 30100,
                 id_policy: Literal['min', 'max'] = 'max',
                 handle_getLocalizedString: bool = True,
                 addon_id: Optional[str] = None,
                 mark_translated: bool = False,
                 obsolete: ObsoleteAction = ObsoleteAction.KEEP,
                 backup_pattern: Optional[str] = '{}~',
                 po_wrap_width: int = 999999,
                 encoding: str = 'utf8',
                 reserved_ids: Optional[ranges] = None,
                 multi_line_msg: bool = False,
                 ) -> None:
        self.xml_inputs: list[XmlInput] = []
        self.py_inputs: list[PyInput] = []
        self._ids: set[int] = set()
        self._by_id: dict[int, Label] = {}
        self._by_text: dict[str, LabelList] = {}
        self.dry_run = dry_run
        self.dump_output = dump_output
        self.dump_translations = dump_translations
        self.stats = stats
        self.handle_getLocalizedString = handle_getLocalizedString
        #: Lowest avaliable ID.
        self.id_from = id_from
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
        #: Moved IDs  - existings IDs if they were in reserved_ids.
        self._moved_ids: set[int] = set()
        #: True if po msg are splited into mulitple lines.
        self.multi_line_msg: bool = multi_line_msg

    def _add_label(self, label: Label, *, used=True):
        """Add label to existing data (by ID and by TEXT)."""
        L1 = L2 = None
        lst = []
        if label is None:
            return
        if label.id is not None:
            if label.id < 30000:  # TODO: make option
                logger.warning(f'Label #{label.id} < #30000')
            L1 = self._by_id.setdefault(label.id, label)
            L1.nodes |= label.nodes  # XXX XXX XXX
        if label.text:
            lst = self._by_text.setdefault(label.text, LabelList())
            L2 = lst.add(label)
        if L1 is not None and L2 is not None and L1 is not L2:
            if L2.id is None:
                label = Label(L1.id or L2.id, L1.text or L2.text, L1.nodes | L2.nodes, L1.trans + L2.trans)
                assert label.id is not None
                self._by_id[label.id] = label
                lst[lst.index(L2)] = label
            else:
                assert L1.id is None or L1.id == L2.id
                if L1.text and L1.text != L2.text:
                    L0 = label
                    if (L2 is L0 or not used or (L2.id == L0.id and L2.text == L0.text)) and L1.id is not None:
                        # text mismatch in the same ID, force to generate new ID (or find another existing)
                        for lb in lst:
                            if lb.id is not None and lb.id != L2.id:
                                L2.id = lb.id
                                break
                        else:
                            L2.id = None  # need to generate new ID
                            L2.ref = L1
                            return L2
                    else:
                        raise ValueError(f'Label #{L2.id}: text mismatch: {L1.text!r} != {L2.text!r}')
                L2.nodes |= L1.nodes
                L2.trans.extend(L1.trans)
                assert label.id is not None
                self._by_id[label.id] = label = L2
        elif L1 is not None:
            label = L1
        elif L2 is not None:
            label = L2
        if used and label.id is not None:
            self._ids.add(label.id)
        return label

    def _scan_xml(self, tree: ElementTree, xtype: XmlType = XmlType.Auto, *,
                  path: Path | None = None):
        """Scan single XML."""
        def add(text: str, node: NodeValue) -> None:
            if text is None:
                node_error(node, 'Empty node/attr (string expected)')
                return
            if text.isdigit():
                label = Label(int(text))
            else:
                label = Label(None, text)
            if label is not None:
                label.nodes.add(node)
                self._add_label(label)

        def is_enabled(node: Element) -> bool:
            # if node.attrib.get('translate') == 'false':
            #     return False
            prev = node.getprevious()
            if not isinstance(prev, etree._Comment):
                return True
            opt = {k.strip(): v.strip()
                   for op in rx_opt_split.split(prev.text) if op
                   for k, sep, v in (op.partition('='),) if sep}
            return opt.get('translate') != 'false'

        rx_opt_split = re.compile(r'\s*:\s*')
        # rx_opt_split = re.compile(r'\s*:\s*')
        node: Element
        root = tree.getroot()
        if xtype == XmlType.Auto:
            if root.tag == 'settings':
                xtype = XmlType.Settings
            elif root.tag == 'window':
                xtype = XmlType.Window

        # -- settings.xml
        if xtype == XmlType.Settings:
            for node in root.iterfind('.//heading'):
                logger.debug(f'  found set.XML heading, value {node.text!r}')
                add(node.text, NodeValue(node, None))
            for attr in ('label', 'help'):
                for node in root.iterfind(f'.//*[@{attr}]'):
                    text = node.get(attr)
                    if text:
                        logger.debug(f'  found set.XML node {node.tag} attr {attr}, value {text!r}')
                    add(text, NodeValue(node, attr))
            for node in root.iterfind('.//*[@lvalues]'):
                for i, text in enumerate(node.get('lvalues').split('|')):
                    logger.debug(f'  found set.XML lvalue {text!r}')
                    add(text, NodeValue(node, 'lvalues', index=i))
        # -- skin/window.xml
        elif xtype == XmlType.Window:
            # <label>TEXT</label>, w/o `$LOCALIZE[`
            if self.addon_id:
                for node in root.xpath('.//label|.//hinttext'):
                    if is_enabled(node) and node.text and not self._RE_SKIP_LABEL.search(node.text):
                        logger.debug(f'  found win.XML label, value {node.text!r}')
                        add(node.text, NodeValue(node, None, trans=(Trans(None, start=0, end=len(node.text),
                                                                          fmt='$ADDON[{addon} {id}]'),)))
            # <any>$LOCALIZE[...]</any>
            if False:  # skins, not supported yet. skipping..
                for node in root.xpath('.//*[text()[contains(.,"$LOCALIZE[")]]'):
                    if is_enabled(node):
                        text = node.text
                        mm = list(self._RE_LOCALIZE.finditer(text))
                        for m in reversed(mm):  # from the end to avoid span move on text replace
                            logger.debug(f'  found win.XML $LOCALIZE[], value {m[0]!r}')
                            start, end = m.span('id') if m['id'] else m.span('text')
                            add(text[start:end], NodeValue(node, None, trans=(Trans(None, start, end, fmt=None),)))

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
            # python templates <ff:vars/> and any in {}
            # for node in root.xpath('.//*[text()[contains(.,"{") and contains(.,"}")]]'):
            if 1:  # XXX  to now, just replace on load as a text
                def xml_py(node: Element):
                    if node.text:
                        nd = NodeValue(node, python=True)
                        if node.text is not None:
                            self._replace_py(node.text, file=XmlValueInput(nd), node=nd, path=path)
                    for attr, value in node.attrib.items():
                        nd = NodeValue(node, attr, python=True)
                        self._replace_py(value, file=XmlValueInput(nd), node=nd, path=path)
                    for elem in node:
                        xml_py(elem)
                # rx = re.compile('')
                xml_py(root)

    def load_xml(self, path: Union[str, Path], base: Optional[Union[str, Path]] = None):
        """Load XML and keep data."""
        path = Path(path)
        if base is not None:
            base = Path(base)
        content = path.read_text(encoding=self.encoding)
        tree = etree.parse(str(path))
        m: re.Match = self._RE_XML_DECL.match(content)
        decl: str = m and m[0]
        self.xml_inputs.append(XmlInput(path, tree, base, declaration=decl))
        self._scan_xml(tree, path=path)
        return tree

    def load_py(self, path: Union[str, Path], base: Optional[Union[str, Path]] = None, *,
                l8funcs: Optional[list[L8Func]] = None) -> None:
        """Load strings from Python source and keep data."""
        path = Path(path)
        if base is not None:
            base = Path(base)
        with open(path, encoding=self.encoding, newline='') as f:
            data = f.read()
        file = PyInput(path, data, base)
        self.py_inputs.append(file)
        self._replace_py(data, file=file, l8funcs=l8funcs, path=path)

    def _replace_py(self,
                    data: str,
                    *,
                    file: PyInput | XmlValueInput | None,
                    l8funcs: Optional[list[L8Func]] = None,
                    node: NodeValue | None = None,
                    path: Path | None = None,
                    ) -> None:
        """Scan single Python source data."""

        def rstr(name='str'):
            pat = '|'.join((
                fr'"""(?P<{name}1>(?:\\.|[^"]|"(?!""))*)"""',   # """..."""
                fr"'''(?P<{name}2>(?:\\.|[^']|'(?!''))*)'''",   # '''...'''
                fr'"(?P<{name}3>(?:\\.|[^"])*)"',     # "..."
                fr"'(?P<{name}4>(?:\\.|[^'])*)'",     # '...'
            ))
            return f'(?:{pat})'

        def rval(r, name='str'):
            for i in range(4):
                if (s := r[f'{name}{i+1}']) is not None:
                    return s

        def rstart(r, name='str'):
            for i in range(4):
                if (s := r.start(f'{name}{i+1}')) != -1:
                    return s

        _R_CM = r'#[^\S\r\n]*(?P<comment>[^\r\n]+)'
        _R_LL = fr'\b(?P<label>LL?)\s*(?P<label_bracket>\()\s*(?:(?P<mid>\d+)\s*,\s*)?{rstr("msg")}\s*(?:,.*?)?\)'
        pat = f'{_R_CM}|{rstr()}|{_R_LL}'
        l8funcs = list(l8funcs or ())
        if self.handle_getLocalizedString:
            l8funcs.append(L8Func('getLocalizedString'))
        gls_funcs = [f for f in l8funcs
                     if f.type == FuncType.GetLocalizedString and (path is None or f.is_allowed(path))]
        if gls_funcs:
            ff = '|'.join(fr'(?:{f})' for f in gls_funcs)
            pat += fr'|\b(?P<gls_func>{ff})\s*\(\s*(?P<gls>(?:(?P<gls_id>\d+)|{rstr("gls_text")}))\s*[),]'
        R = re.compile(pat)
        RS = re.compile(r'\$LOCALIZE\[(?:(?P<id>\d+)|(?P<text>(?:[\\%].|\[(?:[\\%].|[^]])*\]|[^]])+))\]')
        RS_ESC = re.compile(r'[\\%](.)')
        for r in R.finditer(data):
            if r['comment'] is not None:  # skip comments
                continue
            label: Optional[Label] = None
            tr = None
            s, msg = rval(r), rval(r, 'msg')
            sstart = rstart(r)
            # L()
            if msg is not None:
                mid = r['mid']
                if mid is None:
                    offset = r.end('label_bracket')
                    tr = Trans(file, start=offset, end=offset, fmt='{label.id}, ')
                else:
                    mid = int(mid)
                    tr = Trans(file, start=r.start('mid'), end=r.end('mid'))
                label = Label(mid, unescape(msg))
            # " $LOCALIZE[] "
            elif s is not None:
                for r in RS.finditer(s):
                    mid = r['id']
                    if mid is not None:
                        mid = int(mid)
                    if r['text'] is not None:
                        tr = Trans(file, start=sstart + r.start('text'), end=sstart + r.end('text'))
                        text = RS_ESC.sub(r'\1', r['text'])
                        label = Label(mid, unescape(text))
                    elif mid is not None:
                        self._ids.add(mid)  # mark as used
            # getLocalizedString()
            elif r['gls'] is not None:
                mid = r['gls_id']
                func = r['gls_func']
                text = rval(r, 'gls_text')
                logger.debug(f'  found func {func!r}, id {mid}, text {text!r}')
                if mid is None:
                    tr = Trans(file, start=r.start('gls'), end=r.end('gls'))
                else:
                    mid = int(mid)
                label = Label(mid, unescape(text))
            if label is not None:
                if tr is not None:
                    label.trans.append(tr)
                if node is not None:
                    label.nodes.add(node)
                self._add_label(label)

    def _load_input(self, path: Path, *, l8funcs: Optional[list[L8Func]] = None) -> None:
        """Load single file (XML / py) and keep data."""
        logger.info(f'Loading source {path}')
        if path.suffix == '.py':
            return self.load_py(path, l8funcs=l8funcs)
        return self.load_xml(path)

    def load_input(self,
                   path: Union[str, Path],
                   *,
                   skip: set[Path] = set(),
                   l8funcs: Optional[list[L8Func]] = None) -> None:
        """Load input file / py-dir (XML / py) and keep data."""
        res = None
        path = Path(path)
        if not path.exists():
            logger.warning('Path does not exist: {!r}, skipping.'.format(str(path)))
        elif path.is_dir():
            for p in chain(path.glob('**/*.xml'), path.glob('**/*.py')):
                if any(p.resolve().is_relative_to(s) for s in skip):
                    pass
                else:
                    res = self._load_input(p, l8funcs=l8funcs)
        else:
            res = self._load_input(path, l8funcs=l8funcs)
        return res

    # def load_settings(self, path: Optional[Union[str, Path, None]] = None):
    #     path = Path(path or '')
    #     return self.load_input(path / 'resources' / 'settings.xml')

    def load_translate(self, path: Union[str, Path]) -> GenerateStats:
        """Load XML and keep data."""
        pofile = polib.pofile(path)
        was_obsolete = 0
        for entry in pofile:
            text = entry.msgid
            if self._RE_LABEL_NUM.fullmatch(text) and '[empty]' in entry.comment:
                text = None
            if (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is None:
                label = Label(None, text)
            else:
                label = Label(int(r.group(1)), text)
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

    def generate(self) -> GenerateStats:
        """Generate new lables. Return number of new translations."""
        def nextid():
            nonlocal lidgen
            for n in range(lidgen, 99999):
                if n not in self._by_id and n not in self.reserved_ids:
                    lidgen = n
                    return n
            raise ValueError('No new label ID avaliable')

        was_obsolete = len(set(self._by_id) - self._ids)
        if self.id_policy == 'min':
            lidgen = self.id_from
        else:
            lidgen = max(self._by_id, default=self.id_from)

        new_trans_count = 0
        if collision := set(self.reserved_ids.ids()) & self._by_id.keys():
            for mid in collision:
                label = self._by_id.pop(mid)
                label.id = nextid()
                self._by_id[label.id] = label
                self._ids.discard(mid)
                self._moved_ids.add(mid)
                if self.dry_run:
                    print(f' move id: {mid} → {label.id}: {label.text!r}')
        for lst in self._by_text.values():
            for label in lst:
                if label.id is None:
                    new_trans_count += 1
                    label.id = nextid()
                    if self.dry_run:
                        print(f' add id: {label.id}: {label.text!r}')
                    best = self._by_id.setdefault(label.id, label)
                    if label is not best:
                        best.nodes |= label.nodes
                        best.trans.extend(label.trans)
                    self._ids.add(label.id)
        for label in self._by_id.values():
            for node in label.nodes:
                if not node.python:
                    node.set_label(str(label.id), addon=self.addon_id)
                    self._ids.add(label.id)
        trans = sorted(((label, tr) for label in self._by_id.values() for tr in label.trans),
                       key=lambda x: -x[1].start)
        for label, tr in trans:
            # fmt = f'{{before}}{tr.fmt}{{after}}'
            # tr.file.data = fmt.format(before=tr.file.data[:tr.start], after=tr.file.data[tr.end:], label=label)
            tr.replace(label)
            self._ids.add(label.id)
        return GenerateStats(new=new_trans_count, moved=len(collision), obsolete=was_obsolete)

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
            path.rename(bak)
        return path

    def _write_xml(self, input):
        decl = input.declaration or ''
        if self.dry_run:
            logger.debug(f'Write xml: {input.path.resolve()}')
            if (logger.level or logging.root.level) <= logging.DEBUG - 2:
                # etree.indent(input.tree)
                debug_print(decl + etree.tostring(input.tree).decode())
            if self.dump_output:
                print((decl.encode(self.encoding) + etree.tostring(input.tree, encoding=self.encoding)).decode(self.encoding))
        else:
            def entity(m: re.Match) -> str:
                code = ord(m[0])
                return f'&#x{code:04x};'
            path = self._prepare_write_target(input.path.resolve(), base=input.base)
            data: str = decl + etree.tostring(input.tree, encoding=self.encoding).decode(self.encoding)
            data = re.sub(r'[\u2000-\u200f]', entity, data)
            path.write_bytes(data.encode(self.encoding))
            # input.tree.write(str(path), encoding='utf-8', xml_declaration=False)

    def _write_py(self, input):
        if self.dry_run:
            logger.debug(f'Write py:  {input.path.resolve()}')
            if self.dump_output:
                print(input.data)
        else:
            path = self._prepare_write_target(input.path.resolve(), base=input.base)
            with open(path, 'w', encoding=self.encoding, newline='') as f:
                f.write(input.data)

    def translate(self, lang: str, path: Optional[Union[str, Path, None]] = None, *,
                  stats: GenerateStats | None = None, old_stats: GenerateStats | None) -> None:
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
            po.metadata = {
                'Project-Id-Version': '1.0',
                'Report-Msgid-Bugs-To': 'dev@kodi-pl.net',
                'POT-Creation-Date': f'{now:%Y-%m-%d %H:%M:%S%z}',
                'PO-Revision-Date': f'{now:%Y-%m-%d %H:%M:%S%z}',
                'Last-Translator': 'KodiPL Team <dev@kodi-pl.net>',
                # 'Language-Team': 'English <yourteam@example.com>',
                'Language': lang,
                'MIME-Version': '1.0',
                'Content-Type': 'text/plain; charset=utf-8',
                'Content-Transfer-Encoding': '8bit',
                'Plural-Forms': self.PLURAL_FORMS.get(lang, self.DEF_PLURAL_FORMS),
            }
            po.metadata_args = {
                'tcomment': ('Kodi Media Center language file'
                             '\nAddon Name: {addon.name}'
                             '\nAddon id: {addon.id}'
                             '\nAddon Provider: {addon.provider}'),
            }
        ie = {int(r['id']): e for e in po if (r := self._RE_LABEL_NUM.fullmatch(e.msgctxt or '')) is not None}
        for label in self._by_id.values():
            assert label.id is not None
            if label.id not in ie:
                comment = []
                if not label.text:
                    comment.append('[empty]')
                msgstr = ''
                if label.ref is not None and label.ref.id in ie:
                    msgstr = ie[label.ref.id].msgstr
                entry = polib.POEntry(
                    msgctxt=f'#{label.id}',
                    msgid=label.text or f'#{label.id}',
                    # msgstr=label.text or '',
                    msgstr=msgstr,
                    comment=' '.join(comment),
                    # occurrences=[('welcome.py', '12'), ('anotherfile.py', '34')]
                )
                po.append(entry)
        # fake translate: copy all EN entries as translated texts
        if self.mark_translated:
            for entry in po:
                if not entry.obsolete and not entry.msgstr:
                    entry.msgstr = entry.msgid
        # remove obsolete flag if ID used again
        for entry in po:
            if entry.obsolete and (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None:
                mid = int(r.group('id'))
                if mid in self._ids:
                    entry.obsolete = False
        # mark obsolete if ID is not used in XML nor PY (but skip if moved)
        if self.obsolete is ObsoleteAction.MARK:
            for entry in po:
                if (r := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None:
                    mid = int(r.group('id'))
                    if mid not in self._ids and mid not in self._moved_ids:
                        entry.obsolete = True
        elif self.obsolete is ObsoleteAction.REMOVE:
            to_remove = [i for i, entry in enumerate(po)
                         if ((mch := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None
                             and ((mid := int(mch.group('id'))) in self._moved_ids or mid not in self._ids))]
            for i in reversed(to_remove):
                del po[i]
        if self._moved_ids:
            to_remove = [i for i, entry in enumerate(po)
                         if ((mch := self._RE_LABEL_NUM.fullmatch(entry.msgctxt or '')) is not None
                             and int(mch.group('id')) in self._moved_ids)]
            for i in reversed(to_remove):
                del po[i]
        if self.stats:
            N = len(po)
            ob = len(set(self._by_id) - self._ids)
            # nw = len(self._ids) - len(ie)
            nw = mv = ''
            if stats:
                if old_stats and ob != old_stats.obsolete:
                    ob = f'{ob} (+{ob - old_stats.obsolete})'
                nw = f', new: {stats.new}'
                if stats.moved:
                    mv = f', moved: {stats.moved}'
            tr = sum(1 for e in po if e.msgstr)
            if lang == 'en_GB':  # base language (no translation needed)
                print(f'Language {lang}: translated: ---- ({tr}/{N}), obsolete: {ob}{nw}{mv}')
            else:
                print(f'Language {lang}: translated: {100 * tr / (N or 1):3.0f}% ({tr}/{N}), obsolete: {ob}{nw}{mv}')
        if self.dry_run:
            logger.debug(f'Write po:  {path}')
            if (logger.level or logging.root.level) < logging.DEBUG:
                debug_print(po.__unicode__())
            if self.dump_translations and fnmatch(lang, self.dump_translations):
                print(po.__unicode__())
        else:
            po.save(path)

    def load_addon_files(self, path: Union[Path, str]) -> AddonConf:
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
        ):
            if p.exists():
                paths.append(p)
        return AddonConf(paths=paths)

    def load_addon_config(self, path: Path) -> AddonConf:
        def l8paths(paths: Union[list[str], str]) -> set[Path]:
            if not paths:
                return None
            if isinstance(paths, str):
                paths = [paths]
            return {p for pp in paths for p in Path(base.parent).glob(pp)}

        # read options for config file
        if path.is_dir():
            path = path / '.kolang.json'
            if not path.exists():
                return None
        with open(path, encoding='utf8') as f:
            conf = json.load(f)
        options = conf.get('options', {})
        for attr in ('id-from', 'id-policy', 'mark-translated', 'backup-pattern',
                     'addon-id', 'po-wrap-width', 'encoding', 'multi-line-msg'):
            if attr in options:
                setattr(self, attr.replace('-', '_'), options[attr])
        if (val := options.get('mark-obsoleted')) is not None:
            self.obsolete = ObsoleteAction.MARK if val else ObsoleteAction.KEEP
        if val := options.get('obsolete'):
            self.obsolete = ObsoleteAction(val)
        if 'get-localized-string' in options:
            self.handle_getLocalizedString = options['get-localized-string']
        base = path.parent
        paths = []
        for source in conf.get('sources', []):
            if isinstance(source, str):
                source = {'path': source}
            if (addon := source.get('addon')):
                ac = self.load_addon_files(base / addon)
                paths.extend(ac.paths)
            elif (path := source.get('path')):
                path = base / Path(path)
                if path.exists():
                    paths.append(path)
                else:
                    logger.warning(f'Source {str(path)!r} does not exist')
            elif (pat := source.get('glob')):
                pat = Path(pat)
                path = base / pat.parent
                paths.extend(path.glob(pat.name))
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
        # read default addon id from addon.xml
        if self.addon_id is None and (base / 'addon.xml').exists():
            atree = etree.parse(str(base / 'addon.xml'))
            aroot = atree.getroot()
            if aroot.tag == 'addon':
                aid = aroot.attrib.get('id')
                if aid:
                    self.addon_id = aid
        return AddonConf(paths=paths, langs=langs, skip=skip, l8funcs=l8funcs)

    def load_addon(self, path, *, skip: set[Path] = set(), l8funcs: Optional[list[L8Func]] = None) -> None:
        if not (path / 'addon.xml').exists():
            logger.warning(f'Invalid addon folder {path!r}, no addon.xml')
        conf = self.load_addon_config(path)
        if conf is None:
            conf = self.load_addon_files(path)
        if conf is not None:
            skip = set(Path(s) for s in skip or ()) | conf.skip
            skip = {s.resolve() for s in skip}
            for p in conf.paths:
                self.load_input(p, skip=skip, l8funcs=l8funcs)


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
    trans = Translate(dry_run=args.dry_run, dump_output=args.debug_cat_output,
                      dump_translations=args.debug_cat_translation,
                      id_from=args.id_from, id_policy=args.id_policy, addon_id=args.addon_id,
                      handle_getLocalizedString=args.gls, backup_pattern=args.backup_pattern,
                      mark_translated=args.mark_translated, multi_line_msg=args.multi_line_msg,
                      po_wrap_width=args.po_wrap_width, reserved_ids=args.id_reserve,
                      )
    if args.verbose:
        logging.basicConfig(level=args.verbose)
        if logger.parent is None:
            logger.parent = logging.root
    else:
        logging.basicConfig()

    if not getattr(args, 'enable_xml_etree', None):
        try:
            from lxml import etree as _  # noqa: F401
        except ImportError:
            logger.fatal(' Missing lxml module, try `pip install lxml` or use --enable-xml-etree')
            sys.exit(1)

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
        for lpath in output.glob(pattern.replace('{lang_lower}', '*')):
            lpath = lpath.resolve()
            pat = re.escape(pattern.replace('{lang_lower}', '__LANG__')).replace('__LANG__', '(.*?)').replace('/', r'[/\\]')
            r = re.fullmatch(fr'.*[/\\]{pat}', str(lpath))
            if r is not None:
                L = r.group(1)
                L, sep, C = L.partition('_')
                langs.add(f'{L}{sep}{C.upper()}')

    was: dict[str, GenerateStats] = {}
    for lang in langs:
        path = output
        if pattern:
            path = output / pattern.format(lang=lang, lang_lower=lang.lower())
        if path.exists():
            was[lang] = trans.load_translate(path)

    for path in inputs:
        path = Path(path).resolve()
        if path.is_dir():
            if (path / 'addon.xml').exists():
                trans.load_addon(path, skip=args.skip, l8funcs=l8funcs)
            else:
                logger.warning(f'There is NOT an addon in {path}, skipping')
        else:
            trans.load_input(path, l8funcs=l8funcs)

    # override settings from command-line
    if args.obsolete is not None:
        trans.obsolete = args.obsolete

    # do the job
    trans.scan()
    stats = trans.generate()
    if langs:
        trans.write()
    else:
        logger.warning('No languages defined, skip file writting. Use -L ...')

    for lang in sorted(langs):
        path = output
        if pattern:
            path = output / pattern.format(lang=lang, lang_lower=lang.lower())
        trans.translate(lang, path, stats=stats, old_stats=was.get(lang))


def copy_kolang_py(output: Path = Path()) -> None:
    mod = Path(__file__).parent.parent
    if mod.is_file():  # pyz
        from zipfile import ZipFile
        with ZipFile(str(mod)) as z:
            with z.open('kolang/kolang.py') as f:
                content = f.read().decode()
    else:
        content = (mod / 'kolang' / 'kolang.py').read_text(encoding='utf8')
    output /= 'kolang.py'
    if output.exists():
        logger.error(f'{output} already exists, remove it if you want get generate new kolang.py')
    else:
        output.write_text(content, encoding='utf8')


def parse_lang_arg(ss):
    rlang = re.compile(r'[a-z]{2,3}(?:_[a-zA-Z]{2})?')
    ss = [s.strip() for s in ss.split(',') if s.strip()]
    for s in ss:
        if not rlang.fullmatch(s):
            raise ValueError(f'Unknown language fomrat {s!r}')
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


def plural_expr(code: str) -> None:
    from simpleeval import simple_eval
    info = next(iter(p for p in plural_forms if p.code == code))
    print(simple_eval(info.forms))


def main(argv=None):
    p = argparse.ArgumentParser(description='Translate tool for Kodi XML (like gettext)')
    p.add_argument('--version', action='version', version=__version__)
    p.add_argument('--type', choices=('addon', 'skin'), help='add-on folder structure')
    p.add_argument('-t', '--translation', metavar='PATH', type=Path,
                   help='path string.po or folder with it or to resource folder, default "."')
    p.add_argument('-L', '--language', metavar='LANG', action='extend', type=parse_lang_arg,
                   help='new language like "en", "en_US", "pl"')
    p.add_argument('--mark-translated', action='store_true', help='copy original string to all non-translated entries')
    p.add_argument('--remove', action='store_true', help='remove unsused translations : IGNORED')
    p.add_argument('--id-from', metavar='NUM', type=int, default=30100, help='lowest label ID (start from) [30100]')
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
    p.add_argument('--single-line-msg', action='store_false', dest='multi_line_msg', default=False, help='write po messages in single line [default]')
    p.add_argument('--multi-line-msg', action='store_true', default=False, help='write po messages in many lines if \\n is used')
    p.add_argument('--verbose', action='store_const', const=logging.INFO, help='be more verbose')
    p.add_argument('--debug', action=ConstIncAction, const=logging.DEBUG, inc=-1, dest='verbose',
                   help='be much more verbose')
    p.add_argument('--dry-run', action='store_true', help='do not modify anything')
    p.add_argument('--debug-cat-output', action='store_true', help='print output file if --dry-run')
    p.add_argument('--debug-cat-translation', metavar='LOCALE', help='print output translation if --dry-run')
    p.add_argument('--test-plural', help='test plural form and exit')
    # p.add_argument('--enable-xml-etree', action='store_true',
    #                help='allow use xml.etree, XML comment are NOT supported')
    p.add_argument('--generate-kolang-py', action='store_true',
                   help='generate kolang.py to use its L() in addon/plugin')
    p.add_argument('input', metavar='PATH', nargs='+', type=Path, help='path XML or PY file or addon folder')
    args = p.parse_args(argv)
    if args.obsolete is not None:
        args.obsolete = ObsoleteAction(args.obsolete)
    # print(args); exit()

    if args.test_plural:
        plural_expr(args.test_plural)
        return
    if args.generate_kolang_py:
        copy_kolang_py(args.input[0])
        return
    process(args.input, output=args.translation, langs=args.language, args=args)


if __name__ == '__main__':
    main()
