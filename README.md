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

Use the single-file `kolang-X.Y.Z.pyz` (`python kolang.pyz …`, Linux and Windows). It needs lxml: if the
interpreter has none, the first run installs it with pip into a private cache (`~/.cache/kolang/` or
`%LOCALAPPDATA%\kolang\`, per Python version and platform). Without pip or network install lxml yourself
(`sudo apt install python3-lxml` or `python -m pip install lxml`).

Or from the source:

```bash
git clone …
cd kolang
python -m venv .venv
source .venv/bin/activate
pip install -e .                  # installs lxml, `kolang` command
```

Build `dist/kolang-X.Y.Z.pyz` (version from `kolang/__init__.py`):

```bash
make            # build the pyz
make release    # clean tree only: tag vX.Y.Z and build (push is up to you)
make clean
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

Idempotent: re-running on unchanged sources changes nothing. Only changed
files are written. A changed file gets a backup (`{}~` by default) unless it
is tracked by git without local changes (git can restore it); a warning is
printed if the backup is not ignored by git.

Translations are checked on each run (warning only): number of `|||` forms
must match `nplurals` of the language (`Plural-Forms` header), placeholders
`{name}` must be the same as in `msgid`. Entries with placeholders get the
`#, python-brace-format` flag, so `msgfmt -c` and PO editors check them too.
Plural entries get a `#. 3 plural forms separated by |||` comment with the
form count of the language. New and existing PO files get the header comment
like Kodi addons have (`# Kodi Media Center language file`, addon name, id,
provider) if it is missing.
Review list without gettext tools: `kolang --dry-run --list fuzzy --list untranslated .`

Edited text keeps its ID. An existing translation is kept but marked
`#, fuzzy` with the previous text in `#| msgid "…"`; Kodi ignores the flag
(shows the translation), kolang counts fuzzy entries separately. Remove the
flag and `#|` line after review. Same ID with two different texts in sources
is a collision (not an edit): the other text gets a new ID.

---

### Sources

Without `sources` in `.kolang.json` kolang scans `resources/settings.xml`,
`*.py` in the addon root, `resources/lib`, `lib`, `resources/skins` and, for a
skin (`xbmc.gui.skin` in `addon.xml`), the `<res folder=…>` folders plus
`extras` and `shortcuts`. XML with `<window>` or `<includes>` root is scanned
as skin, `<settings>` as settings; `$LOCALIZE[N]` in any XML and skin
`<viewtype label="N">` / `<fontset idloc="N">` mark the ID as used.
`--obsolete mark/remove` stops with an error when no source file was scanned
(it would make every string obsolete).

A source that is a symlink leaving the addon (e.g. a skin file linked to a
user's debug file, kept as a link by `cp -r`) is read-only: its IDs count as
used, but it is never written and its new texts get no ID (warning). A link
whose target is inside the addon is written through. To translate such a file,
replace the link by a copy.

### References `#:` in PO

`--locations none|file|line` (or `"locations"` in `.kolang.json`) writes where
each text is used (`#: resources/lib/main.py` or `…main.py:12`), in all
language files; IDs used by number (`$LOCALIZE[N]`, `getLocalizedString(N)`)
count too. Default is derived from the base language PO: no `#:` there → none,
`#:` without line numbers → file (Kodi style, also its `/` prefix), with line
numbers → line. Existing references keep their order, new ones are appended,
gone ones removed. Free text in `#:` (seen in Kodi files) moves to `#.`.
Line numbers change with every edit above the text — prefer `file`.

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

The first argument must be a plain string literal; the call may span lines and
adjacent literals are one text (Python concatenation, comments between them
are fine). `L(30200)` / `L(30200, n=…)` without text only marks the ID as used.
`L(f'…')`, `L('a' + x)`, `L('a' % x)` can't be translated: kolang warns
(`L() text is not a plain string literal`). `L(variable)` is silent.

```python
L('Long text, first part, '            # → L(30101, 'Long text, …'
  'second part', n=count)
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

The rule is the `Plural-Forms` header of the addon PO for the Kodi language
(`resources/language/resource.language.<ll_cc>/strings.po`, any folder of the
language, then `en_gb`), evaluated with Python's `gettext`. A text without
translation (Kodi shows the English source) uses the English rule. Missing or
broken header: gettext default `n != 1` and a warning in the Kodi log.
`rules.json` from older `kolang.py` versions is not used, remove it after
refreshing `kolang.py`. `python kolang.pyz --test-plural pl` shows the forms
of a language for n 0–30.

`{n}` inside the form is substituted with the value (kolang's runtime calls
`form.format(n=n, **kwargs)`):

```python
L(30100, '{n} file|||{n} files', n=count)   # EN: "1 file" / "5 files"
```

#### Context (`ctx=`)

The same English text can have different meanings (and translations). One text
gets one ID, unless the context differs (like Qt disambiguation):

```python
L(30100, 'Open')                       # verb
L(30101, 'Open', ctx='adjective')      # other ID, other translation
L(30101, 'Open', n=1, ctx='adjective') # same context → same ID
```

`ctx` is for kolang only: runtime `L()` ignores it, so it can't be a `{ctx}`
placeholder. PO keeps the context in a translator comment (Kodi ignores it):

```
#. context: adjective
msgctxt "#30101"
msgid "Open"
```

Adding a context to some occurrences of an ID splits them to a new ID, the
translation is copied as `#, fuzzy` (review it). Changing only the context of
an ID keeps the ID, the translation becomes fuzzy like on text edit.
`getLocalizedString('text')` and `$LOCALIZE[text]` have no context.

#### Notes for translators (`Translators:`)

A comment starting with `Translators:` (any case, gettext convention) right
above the line with `L()` (consecutive comment lines are one note) or at the
end of that line goes to PO as `#. Translators: …`. It doesn't change IDs.

```python
# Translators: button in the main menu,
#   keep it short
L(30100, 'Open')
L(30101, 'Close')  # Translators: closes the dialog
```

In XML `<!-- Translators: … -->` before the element is for all its values,
`<!-- Translators[label]: … -->` for one target (`[]` text content). It also
covers `L()` in `{…}` / raw Python values of the element. The same text used in
more places gets all its notes. PO lines follow the sources on every run;
other `#.` lines are kept.

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

Four comment shapes (and `Translators:` notes, see Python), all parsed by kolang from XML comments preceding an
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

#### `:context=…:` — text context of a new text

```xml
<!-- :context=verb: -->                <!-- all targets of the element -->
<!-- :context[label]=adjective: -->    <!-- only the `label` attr ([] is text content) -->
<setting label="Open"/>
```

After the ID is assigned the context moves to the `L()` marker and the
directive is removed: `<!-- L[label](30101, 'Open', ctx='adjective') -->`.
Edit the context there. `:context:` next to an `L()` marker is like a text
next to it: the same context is removed with a warning, a different one is an
error (two sources of truth). The value can't contain `:`.

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
| `--id-from NUM` | lowest ID for newly assigned strings (default 30100, skin 31100) |
| `--id-min NUM` | warn when label ID below NUM (default = `--id-from`, skin 31000) |
| `--id-max NUM` | upper bound for new IDs (default 32999, skin 31999) |
| `--id-policy {max,min}` | strategy for picking next free ID |
| `--id-reserve A-B,C` | mark ID ranges as reserved (existing labels there get moved with translations; error if an ID there is used by number) |
| `--compact-ids` | renumber own IDs one after another from `--id-from` (translations move with them; IDs used by number stay); needs committed sources and PO |
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
| `--check` | write nothing, list files that would change, exit 1 if any (CI) |
| `--git-setup` | `.gitattributes`, merge driver, `post-merge` hook (see Git) |
| `--reset-ids REF` | remove IDs new on the branch before merge into `REF` (see Git) |
| `--list WHAT` | list `fuzzy` or `untranslated` entries per language (repeatable); with `--dry-run` it's a read-only report |
| `--verbose` / `--debug` | more output |
| `--generate-kolang-py` | drop `kolang.py` (the runtime `L()` helper) into PATH, a changed one is overwritten (backup unless git restores it) |

Run `python kolang.pyz --help` for the complete list.

ID range defaults follow the addon type: a skin (`xbmc.gui.skin` in `addon.xml` or `--type skin`) gets 31100–31999,
because Kodi finds skin strings by number (`$LOCALIZE[N]`, `<label>N</label>`) only in 31000–31999 — a numeric
reference to an own string outside it is reported. Other addons get 30100–32999 (33000–33999 are Kodi core strings).
`--id-from` / `--id-min` / `--id-max` on the command line win over `.kolang.json`.

New IDs go above the highest used one (`--id-policy max`); when the top of the range is full, they fill gaps from
`--id-from` (warning). With no free ID at all kolang stops with a hint: raise `--id-max`, free IDs held by unused PO
entries (`--obsolete remove`) or renumber with `--compact-ids`.

`--compact-ids` renumbers own IDs (from `--id-from` up) one after another in their current order, PO entries are
renumbered in place in all languages (translation, fuzzy, comments stay). IDs used by number (`getLocalizedString(N)`,
`L(N)`, `$LOCALIZE[N]`, `label="N"` without `L()` comment, `<label>N</label>` in `addon.xml`) stay, the rest is
numbered around them. Unused PO entries follow the used ones (`--obsolete remove` drops them). Before running it:
merge or `--reset-ids` other branches (every ID line changes), check that no other addon or skin uses the strings by
number (kolang can't see them), commit (kolang refuses uncommitted sources/PO). `L()` in comments is not rewritten.
Try `--dry-run --compact-ids` first (`move id: old → new`).

---

### Configuration (`.kolang.json`)

Lives at the addon root by default. All sections are optional.

```json
{
    "options": {
        "addon-id": null,
        "id-from": 30100,
        "id-min": null,
        "id-max": 32999,
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
* `options.po-header` — PO header fields, e.g.
  `{"Last-Translator": "Me <me@x.org>", "Language-Team": "{language} team"}`
  (`{language}` is the language name). Missing header fields are added to
  new and existing PO files (existing values are kept) from: this option,
  `addon.xml` (`provider-name`, `<email>`, `<source>`), defaults
  (`Language-Team` is the language name). Kodi ignores the header, it's for
  `msgfmt` and PO editors.

---

### Git: merging branches

Every branch takes the next free ID, so two branches give the same ID to
different texts and `strings.po` always conflicts. Once per clone:

```bash
python kolang.pyz --git-setup .
```

It adds `strings.po merge=kolang` to `.gitattributes` (commit it), registers
the merge driver below and a `post-merge` hook: after a merge on the default
branch (`origin/HEAD`, else `main`) it runs kolang (new IDs for merged texts,
see `--reset-ids`) and lists changed files to commit. On other branches the
hook does nothing (merging main into a feature branch must not assign IDs).
An existing foreign `post-merge` hook is not changed. By hand:

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
and numeric attributes) to the IDs of their texts. If a language PO has
another text under an ID than the model (e.g. hand edits), kolang moves the
translation to the ID of its text and prints a warning.

If both branches added an identical element at the same place, git keeps one
element with two `L[]` comments above it. kolang stops with an error on the
second comment for the same target — restore the lost element by hand.

#### Before merge: `--reset-ids REF`

Collisions can be avoided before the merge: remove IDs that are new on the
branch (not in the base language PO at `git merge-base HEAD REF`), then IDs
are assigned once, on `REF` after the merge.

```bash
python kolang.pyz --reset-ids main .     # on the branch, commit the result
git checkout main && git merge feature
python kolang.pyz .                      # on main: new IDs, translations kept
```

- Sources get the text back: `L(30150, 'New')` → `L('New')`, XML values and
  `lvalues` items → text, whole skin `$ADDON[addon 30150]` → text, `L()`
  comment removed (its `ctx` → `:context[…]=…:`).
- PO entries (all languages) lose `msgctxt "#ID"`: translation waits in an
  entry without ID (Kodi ignores it, so on the branch the English text is
  shown). The next normal run gives the text an ID and takes the translation;
  texts waiting for an ID are reported as `pending: N`.
- Kept (reported): IDs used by number (`getLocalizedString(30150)`,
  `$LOCALIZE[30150]`, `label="30150"` without `L()` comment) and texts that
  have another ID too.
- The run assigns no new IDs. Run it again if the branch changes.

#### CI: `--check`

`--check` writes nothing, prints `would change: FILE` and exits with 1 if a
run would change anything. Web merges (GitHub/GitLab) run no hooks and no
merge driver, so check in CI, e.g. GitHub Actions:

```yaml
- run: git fetch origin main
- if: github.event_name == 'pull_request'     # branch has no new IDs
  run: python kolang.pyz --check --reset-ids origin/main .
- if: github.ref == 'refs/heads/main'          # nothing pending / out of sync
  run: python kolang.pyz --check .
```

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
* `Makefile` — builds `dist/kolang-X.Y.Z.pyz`.
* `tests/` — pytest suite (`pytest tests/` from project root).
