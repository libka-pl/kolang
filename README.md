## kolang — Kodi translation tool

A pragmatic gettext-like helper for Kodi addons and skins. It scans your `.py`
sources and `*.xml` files (settings + skin), assigns numeric IDs that Kodi
expects, and keeps `strings.po` in sync.

License: MIT.

Used modules:
  - [polib](https://github.com/izimobil/polib) (MIT) — vendored.
  - [lxml](https://lxml.de/) — required.

---

### Install

Use `kolang.pyz` standalone, or:

```bash
git clone …
cd kolang
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # installs lxml
```

---

### Quick start

Drop a `.kolang.json` at the addon root (or pass `-c CONFIG`), then:

```bash
python kolang.pyz path/to/addon
```

What kolang does on each run:

1. Reads existing `resources/language/resource.language.*/strings.po`.
2. Scans XML and PY sources for translatable strings.
3. Assigns IDs to new strings, rewrites sources to use IDs, updates PO files.
4. Adds documentation comments next to IDs in XML (so the source text stays
   visible in the markup).

Idempotent: re-running on unchanged sources changes nothing.

Edited text keeps its ID. An existing translation is kept but marked
`#, fuzzy` with the previous text in `#| msgid "…"`; Kodi ignores the flag
(shows the translation), kolang counts fuzzy entries separately. Remove the
flag and `#|` line after review. Same ID with two different texts in sources
is a collision (not an edit): the other text gets a new ID.

---

### How translatable strings are spotted

#### In Python (`.py`)

Before kolang:
```python
from kolang import L

L('Welcome')                          # no ID yet
L(30100, 'Welcome')                   # already assigned
L('item|||items', n=cnt)              # plural, no ID yet
getLocalizedString(30200)             # numeric reference — try to avoid, use L() instead
```

After kolang:
```python
L(30100, 'Welcome')                   # ID inserted
L(30100, 'Welcome')                   # unchanged (id matches)
L(30101, 'item|||items', n=cnt)       # ID inserted, n= passes through
getLocalizedString(30200)             # unchanged — only marked as used
```

PO gets one entry per unique text:
```
msgctxt "#30100"
msgid "Welcome"
msgctxt "#30101"
msgid "item|||items"
```

Custom L-like functions can be declared in config (see below).

#### Plural forms (`|||`)

Forms inside one `msgid` are separated by `|||`. The number of forms must
match the language's `Plural-Forms` rule (kolang seeds the PO header with
the right rule for the declared `--language`).

Source (English declaration):
```python
L('file|||files', n=count)
```

After kolang assigns an ID:
```python
L(30100, 'file|||files', n=count)
```

PO entries — note the form count differs per language:

```
# resources/language/resource.language.en_gb/strings.po
# Plural-Forms: nplurals=2; plural=(n != 1);
msgctxt "#30100"
msgid "file|||files"
msgstr "file|||files"

# resources/language/resource.language.pl_pl/strings.po
# Plural-Forms: nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);
msgctxt "#30100"
msgid "file|||files"
msgstr "plik|||pliki|||plików"
```

At runtime, `L(30100, '...', n=count)` picks the right form:
- EN, `n=1` → `"file"`; `n=0`, `n=2`, … → `"files"`.
- PL, `n=1` → `"plik"`; `n=2/3/4/22/…` → `"pliki"`; rest → `"plików"`.

`{n}` inside the form is substituted with the value (kolang's runtime calls
`form.format(n=n, **kwargs)`):

```python
L(30100, '{n} file|||{n} files', n=count)   # EN: "1 file" / "5 files"
```

#### In XML — three independent layers

**Plain text / attribute** (settings & skin standard places):

Before:
```xml
<setting label="Movies"/>
<heading>General</heading>
<label>Plain caption</label>
```

After (settings + skin label rewrite differs — skin gets an `$ADDON[]`
wrapper so Kodi resolves the right addon at runtime):
```xml
<!-- L[label](30100, 'Movies') -->
<setting label="30100"/>

<!-- L(30101, 'General') -->
<heading>30101</heading>

<!-- L(30102, 'Plain caption') -->
<label>$ADDON[your.addon.id 30102]</label>
```

PO gets the texts; documentation comments preserve them next to the IDs.

**Numeric reference** (no text — ID points elsewhere):

```xml
<setting label="32310"/>            <!-- Kodi-core string, untouched -->
<label>$LOCALIZE[31000]</label>     <!-- skin runtime substitution, untouched -->
```

kolang only marks the IDs as used; no PO entry is created and the XML is
not rewritten.

**Templates** (skin only — see Templates section).

---

### Comments that control kolang

Three comment shapes, all parsed by kolang from XML comments preceding an
element. Free-form developer comments between them are skipped.

#### `:translate=…:` — should this go to PO?

```xml
<!-- :translate=false: -->          <!-- skip whole element -->
<!-- :translate=true: -->           <!-- force translate (override automat) -->
<!-- :translate[label]=false: -->   <!-- only the `label` attr -->
<!-- :translate[help]=true: -->     <!-- only the `help` attr -->
<!-- :translate[]=false: -->        <!-- only text content (empty []) -->
<!-- :translate[lvalues#0]=false: --> <!-- single value of lvalues -->
```

Granularity wins over general; defaults come from kolang's automat
(letter-based heuristic that ignores Kodi format tags `[B]`/`[/B]`/`[CR]`/…
and runtime placeholders `$INFO[…]`/`$VAR[…]`/…).

You can combine on one line:

```xml
<!-- :translate[label]=true: :translate[help]=false: -->
<setting label="Movies" help="$INFO[Window.Property(help)]">
```

#### `:python=…:` — should kolang look for L() calls inside?

```xml
<!-- :python=false: -->     <!-- no python scan at all -->
<!-- :python=true: -->      <!-- treat the value as raw Python source -->
<!-- :python=fstring: -->   <!-- only scan {…} expressions (default in skin) -->
<!-- :python[value]=true: -->   <!-- per-attribute -->
```

Defaults: `fstring` everywhere in skin XML, `false` everywhere in settings —
plus a built-in whitelist of tags/attrs that get raw scan automatically (see
Templates).

`:translate` and `:python` are independent. `:translate=false:` does not
disable a python scan; if you want to hide template `{…}` from kolang too,
add `:python=false:`.

#### `<!-- L(...) -->` — documentation marker

After the first scan, every translated value gets a documentation comment
that pairs the ID with the source text. Editing the text in the comment is
the same as editing `L(N, 'text')` in Python — text becomes the new source
of truth on the next run.

```xml
<!-- L(30100, 'General') -->
<heading>30100</heading>

<!-- L[label](32310, 'General') -->
<!-- L[help](30605, 'Help text') -->
<setting label="32310" help="30605"/>

<!-- L[lvalues#0](30100, 'Action') -->
<!-- L[lvalues#1](30101, 'Drama') -->
<setting type="enum" lvalues="30100|30101"/>
```

The bracket form `L[name]` works for any XML attribute name including
namespaced ones (e.g. `L[xmlns:foo]`, `L[font-size]`).

XML comments cannot contain `--`, so kolang escapes every `-` in any
run of 2+ dashes as `-` (Python‑style unicode escape) **inside the
comment only**. Single `-` is left alone, and the PO `msgid` keeps the
original `--` verbatim (PO is plain text, no XML restrictions).

Source text `--- sekcja ---` produces:

```xml
<!-- L(30100, '--- sekcja ---') -->
```

```
msgctxt "#30100"
msgid "--- sekcja ---"
```

`ast.literal_eval` parses the comment back to the original `--- sekcja ---`,
so subsequent runs are idempotent.

When kolang encounters a comment **and** a different *text* (not number) in
the XML, it refuses with a hard error — there are two sources of truth and
kolang won't silently discard either. Either fix the XML to a number or
remove/edit the comment.

---

### Templates (skin XML)

Kodi skin authors often need runtime composition. kolang understands two
template idioms.

#### F-string blocks `{…}` in skin XML

Inside `<label>`, attributes, anywhere in skin XML.

Before:
```xml
<label>Welcome {L('user')}</label>
<label>Hello {L('world', n=count)}</label>
```

After:
```xml
<label>Welcome {L(30100, 'user')}</label>
<label>Hello {L(30101, 'world', n=count)}</label>
```

PO contains only the inner strings (`'user'` → #30100, `'world'` → #30101).
The whole `<label>` value (with `Welcome ` / `Hello ` static prefix) is
**not** added to PO — your runtime template engine composes the final
text. Use `{{` / `}}` for literal braces (Python f-string convention).

#### Raw Python tags / attributes

For elements where the entire content is Python.

Before:
```xml
<ff:vars>x = L('vars'); y = some_func()</ff:vars>
<ff:set value="L('attr')"/>
<ff:include ff:args="L('arg1'), L('arg2')"/>
```

After:
```xml
<ff:vars>x = L(30100, 'vars'); y = some_func()</ff:vars>
<ff:set value="L(30101, 'attr')"/>
<ff:include ff:args="L(30102, 'arg1'), L(30103, 'arg2')"/>
```

kolang scans the value as full Python source. Built-in default whitelist:

| Tag | Attributes |
|---|---|
| `ff:vars` | text content |
| `ff:define` | `args` |
| `ff:include` | `ff:args` |
| `ff:set` | `value` |

Extend via `python-tags` / `python-attrs` in `.kolang.json` (see below).

#### Decision summary (skin)

| Element shape | Default behavior |
|---|---|
| `<label>Plain text</label>` | translate as label |
| `<label>{L('user')}</label>` | template scan only — `'user'` to PO; whole label not |
| `<label>Welcome {L('user')}</label>` | same as above; `Welcome ` is not extracted |
| `<label>$LOCALIZE[31000]</label>` | reference — mark 31000 used; no PO entry |
| `<label>Hello $LOCALIZE[31000]</label>` | translate whole label literally; reference marked |
| `<ff:vars>x = L('foo')</ff:vars>` | raw scan — `'foo'` to PO |
| `<x attr="L('foo')"/>` | nothing (not whitelisted, no `{…}`) — add `:python[attr]=true:` to opt in |

Settings XML behaves like skin but `:python=false:` is the default — only
the explicit whitelist (or `:python=…:` override) triggers a scan.

---

### CLI

```
python kolang.pyz [OPTIONS] PATH [PATH …]
```

Most-used options:

| Flag | Meaning |
|---|---|
| `-L LANG`, `--language LANG` | declare a target language (e.g. `en`, `pl_PL`) |
| `--type {addon,skin}` | force layout (else auto-detected) |
| `-c CONFIG` | use specific `.kolang.json` |
| `-s PATH`, `--skip PATH` | skip a file/dir |
| `--id-from NUM` | lowest ID for newly assigned strings (default 30100) |
| `--id-min NUM` | warn when label ID below NUM (default = `--id-from`) |
| `--id-max NUM` | upper bound for new IDs (default 33999) |
| `--id-policy {max,min}` | strategy for picking next free ID |
| `--id-reserve A-B,C` | mark ID ranges as reserved (existing labels there get moved) |
| `--addon-id ID` | force `$ADDON[ID …]` prefix in skin labels (else read from `addon.xml`) |
| `--no-addon-id` | don't add `$ADDON[]` prefix at all |
| `--obsolete {keep,mark,remove}` | how to treat PO entries no longer referenced |
| `--remove` | alias for `--obsolete=remove` |
| `--mark-translated` | copy `msgid` into empty `msgstr` (fake translation) |
| `--git-only` | scan only files tracked by git (in the index) |
| `--cleanup-translate-comments` | one-time cleanup of redundant `:translate=false:` |
| `--single-line-msg` / `--multi-line-msg` | PO line wrapping |
| `--encoding ENCODING` | encoding for `.py` / `.po` and as fallback for XML without declaration |
| `--backup-pattern PAT` | source backup naming (`{}~` by default; `+` writes `.new` instead) |
| `--no-backup-pattern` | disable backup |
| `-f FUNC`, `--localized-function FUNC` | extra L-like function name (CLI shortcut) |
| `--get-localized-string` / `--no-get-localized-string` | toggle scanning `getLocalizedString()` |
| `--dry-run` | do not modify anything |
| `--verbose` / `--debug` | more output |
| `--generate-kolang-py` | drop `kolang.py` (the runtime `L()` helper) into the addon |

Run `python kolang.pyz --help` for the complete list.

---

### Configuration (`.kolang.json`)

Lives at the addon root by default. All sections are optional.

```json
{
    "options": {
        "addon-id": null,
        "id-from": 30100,
        "id-min": null,
        "id-max": 33999,
        "id-policy": "max",
        "mark-translated": false,
        "get-localized-string": true,
        "obsolete": "mark",
        "backup-pattern": "{}~",
        "po-wrap-width": 999999,
        "encoding": "utf-8",
        "git-only": false,
        "extra-translate-attrs": ["tooltip"],
        "extra-translate-tags": ["altlabel"],
        "python-tags": ["ff:script"],
        "python-attrs": [
            "value",
            {"name": "expr", "tags": ["ff:if"]}
        ]
    },

    "languages": ["en", "pl"],

    "sources": [
        "path/to/dir",
        "path/to/file.py",
        {"path": "resources/settings.xml"},
        {"glob": "path/to/**/files*.py"},
        {"addon": "../path/to/another/addon"}
    ],

    "skip": [
        "path/to/skipped/file.py",
        "path/to/skipped/folder",
        "path/**/glob/*sss"
    ],

    "localized-functions": [
        "locale_func_name",
        {"name": "locale_func_name"},
        {"regex": "locale_\\w+_regex"},
        {"name": "locale_func_name", "path": "only/**/in/this/*glob.py"}
    ]
}
```

Notes:

* `options` — defaults; everything also available as a CLI flag (see `--help`).
* `languages` — codes like `pl`, `en_US`. Country defaults guessed if you
  give just the language part.
* `sources` — directories, single files, globs, or other addons. A bare
  string is shorthand for `{"path": "…"}`.
* `skip` — path globs to omit when walking directories.
* `localized-functions` — declare your own L‑like functions (the runtime
  ones, not XML markup).
    * `regex` — function-name regex.
    * `name` — plain name.
    * `path` — glob limiting where this function is recognised.
    * `type` — `L` (number + text), `GetLocalizedString` (number-only,
      default), or `Localize` (skin `$LOCALIZE[…]`-like extraction).
* `extra-translate-attrs`, `extra-translate-tags` — additional XML
  attributes/tags scanned for label-translation (in addition to the
  built-ins `label`, `help`, `lvalues`, `<heading>`, `<label>`,
  `<hinttext>`).
* `python-tags`, `python-attrs` — additional whitelist for raw Python
  scanning (in addition to the built-ins listed above). Each `python-attrs`
  entry is either a bare string (global, any tag) or
  `{"name": "...", "tags": [...]}` (limited to the listed tags).

---

### Git: merging branches

Every branch takes the next free ID, so two branches give the same ID to
different texts and `strings.po` always conflicts. Register kolang as the
merge driver for PO files (once per clone; `.gitattributes` is committed):

```bash
echo 'strings.po merge=kolang' >> .gitattributes
git config merge.kolang.driver 'python /path/to/kolang.pyz --merge-po %O %A %B'
```

The driver merges PO by ID:
- new entries from both sides are kept,
- same ID with different texts (collision): theirs text goes to the ID it
  already has, or gets a new free ID, translations are kept,
- translations are merged 3-way; changed on both sides → ours is kept as
  fuzzy with theirs in a `# theirs: …` comment, the conflict is printed but
  the merge doesn't stop (kolang reports the fuzzy count).

Then resolve source conflicts (if any; usually take both sides) and run
kolang. It moves the colliding labels in sources (`L()`, XML `L[]` comments
and numeric attributes) to the IDs of their texts.

If both branches added an identical element at the same place, git keeps one
element with two `L[]` comments above it. kolang stops with an error on the
second comment for the same target — restore the lost element by hand.

---

### Examples

#### Bare addon, first run

```
addon/
├── addon.xml
├── default.py        # contains  L('Hello')
└── resources/
    └── settings.xml  # contains  <setting label="Movies"/>
```

```bash
python kolang.pyz addon
```

After:

```python
# default.py
L(30100, 'Hello')
```

```xml
<!-- resources/settings.xml -->
<settings>
  <!-- L[label](30101, 'Movies') -->
  <setting label="30101"/>
</settings>
```

```
# resources/language/resource.language.en_gb/strings.po
msgctxt "#30100"
msgid "Hello"
msgstr ""

msgctxt "#30101"
msgid "Movies"
msgstr ""
```

#### Skin label with template

Source:
```xml
<label>Welcome {L('user')}</label>
<label>$LOCALIZE[31000]</label>     <!-- Kodi-core "OK" string -->
<label>Plain text</label>
```

After `kolang`:
```xml
<label>Welcome {L(30100, 'user')}</label>
<label>$LOCALIZE[31000]</label>     <!-- untouched; 31000 marked as used -->
<!-- L(30101, 'Plain text') -->
<label>$ADDON[your.addon.id 30101]</label>
```

PO contains `'user'` (#30100) and `'Plain text'` (#30101). The `Welcome `
prefix and `$LOCALIZE[31000]` reference are not extracted.

#### Suppressing a false positive

```xml
<!-- :translate=false: -->
<setting id="hidden" label="Internal: do not translate"/>
```

#### Adding a custom raw-Python attribute

`.kolang.json`:
```json
{"options": {"python-attrs": [{"name": "onclick", "tags": ["button"]}]}}
```

Then:
```xml
<button onclick="L('action')"/>     <!-- → onclick="L(30200, 'action')" -->
```

---

### Technical notes

The flow on each invocation:

1. **Load PO** — every existing `strings.po` is parsed; entries become
   `Label(id, text)` records in the in-memory store, not yet marked as
   "used".
2. **Scan sources** — each `.py` and `.xml` file is parsed:
    * Python source goes through a regex-based tokenizer that finds `L()`,
      `getLocalizedString()`, `$LOCALIZE[…]` and any custom L-functions.
    * XML goes through two passes per element:
        1. **Python pass** — `:python=…:` mode resolution
           (`true`/`fstring`/`false`); raw or `{…}` block scan triggers the
           Python tokenizer on the value.
        2. **Translate pass** — settings: `<heading>` text and
           `label`/`help`/`lvalues` attrs (+ extras); skin: `<label>` and
           `<hinttext>` text (+ extras). `:translate=…:` and the letter-test
           heuristic decide whether the value goes to PO.
3. **Generate IDs** — newly seen texts get an ID via
   `nextid()` (skips `_by_id`, used IDs and reserved ranges, bounded by
   `--id-max`). Reserved-range IDs already in use get moved.
4. **Write back** — for each label, kolang:
    * Inserts a documentation `<!-- L(...) -->` comment if missing
      (idempotent — does nothing if the marker already matches).
    * Replaces the source value with the assigned ID (Python: edits the
      `L(...)` call site; XML: rewrites the text/attribute).
5. **Save PO** — for each declared language, ensures every label in
   `_by_id` is present in that language's `strings.po`. Texts in PO are
   never silently overwritten — kolang only adds new entries and (with
   `--obsolete=mark/remove`) flags or drops unreferenced ones.

#### Decision tree per scanned XML value

```
1. :python override? → respected
   - true   → scan whole value as raw Python
   - fstring → extract balanced {…} blocks, scan each
   - false  → no python scan
   (modifies value in-place via Trans records)
2. :translate override? → respected
   - true   → translate (matrix below)
   - false  → do not translate
   - (none) → automat:
     * if :python=fstring is active and text contains {…} → don't translate
       (template runtime composes; PO would be redundant)
     * else: letter test (Unicode `isalpha()` after stripping Kodi format
       tags and runtime placeholders)
3. Translate matrix (when active and a value goes to PO):
   - text + no L() comment       → new declaration, generate ID
   - number + no L() comment     → reference, mark ID as used; if PO has it,
                                    auto-add the L() comment (migration)
   - number + matching L()       → OK
   - number + L() with diff. ID  → warning, comment wins, XML rewritten
   - text + L() (same text)      → warning, replace XML with the ID
   - text + L() (diff. text)     → hard error (two sources of truth)
```

#### Files of interest

* `kolang/__init__.py` — main module, all of the logic above.
* `kolang/kolang.py` — runtime helper (`L(...)`, `KodiLabels`) intended to
  be dropped into addons via `--generate-kolang-py`.
* `kolang/plural.py` — gettext plural rules.
* `kolang/polib.py` — vendored PO file library.
* `kolang/release.py` — builds `kolang.pyz`.
* `tests/` — pytest suite (`pytest tests/` from project root).
